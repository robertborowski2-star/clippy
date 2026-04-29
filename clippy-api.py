"""
clippy-api.py — Clippy's HTTP API layer
=========================================
Runs alongside nova-api.py on port 8766.
Exposes a /chat endpoint for Helm to talk to Clippy interactively.

Run with:
    cd ~/clippy-src
    uvicorn clippy-api:app --host 0.0.0.0 --port 8766

Endpoints:
    POST /chat      — send a message, get Clippy's response
    GET  /walnuts   — return all project walnut summaries
    GET  /health    — ping
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import FastAPI, HTTPException, Header, Depends
import os
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
import memory

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clippy.api")

API_KEY = os.getenv("AGENT_API_KEY", "")

def verify_key(x_api_key: str = Header(...)):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

app = FastAPI(title="Clippy API", version="1.0.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Clippy, a direct and efficient AI research agent.
You research AI/tech news, Canadian CRE markets, and monitor developments 
relevant to Robert's active projects: Klaus (CRE underwriting platform), 
CRE-LLM (Canadian CRE language model), and the Agent Network (Nova, Clippy, Helm).

Be concise and actionable. No fluff. Use web search when you need current information.
Always flag findings relevant to Robert's active projects."""


class ChatRequest(BaseModel):
    message: str
    agent_id: Optional[str] = "clippy"


class ChatResponse(BaseModel):
    response: str
    agent_id: str
    timestamp: str


@app.get("/health")
def health():
    return {"status": "ok", "agent": "clippy", "timestamp": datetime.now().isoformat()}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, _=Depends(verify_key)):
    log.info(f"Chat request: {req.message[:80]}...")
    try:
        # Load project context for relevant walnuts
        project_context = ""
        for project in ["agent-network", "klaus", "cre-llm"]:
            ctx = memory.read_project_context(project)
            if ctx:
                project_context += f"\n=== {project.upper()} ===\n{ctx[:600]}\n"

        system = SYSTEM_PROMPT
        if project_context:
            system += f"\n\n== ROBERT'S ACTIVE PROJECTS ==\n{project_context}"

        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": req.message}],
        )

        # Handle tool use loop
        messages = [{"role": "user", "content": req.message}]
        while response.stop_reason == "tool_use":
            tool_results = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": t.id, "content": ""}
                    for t in tool_results
                ],
            })
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=system,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=messages,
            )

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        return ChatResponse(
            response=text,
            agent_id="clippy",
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        log.exception("Error in chat endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/walnuts")
def get_walnuts():
    """Return current state of all project walnuts."""
    result = {}
    for project in ["agent-network", "klaus", "cre-llm"]:
        result[project] = {
            "now": memory.read_project_walnut(project, "now"),
            "tasks": memory.read_project_walnut(project, "tasks"),
        }
    return result

@app.get("/latest")
def get_latest():
    """Return the most recent research log entry."""
    try:
        logs = memory.get_recent_logs(days=7)
        if logs:
            timestamp, job_name, summary = logs[0]
            return {"content": summary, "job_name": job_name, "created_at": timestamp}
        return {"content": None, "job_name": None, "created_at": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
