"""Clippy's brain — calls Claude with web_search tool for research jobs."""

import anthropic
import urllib.request
import urllib.parse
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime
import requests
from dotenv import load_dotenv
load_dotenv()


OPENROUTER_MODEL = "qwen/qwen3-235b-a22b"
FALLBACK_MODEL = "claude-haiku-4-5-20251001"


# ── Data Fetchers (no API keys needed) ────────────────────────────────────

def fetch_hn_stories(n: int = 15) -> str:
    """
    Fetch top Hacker News stories via Firebase API.
    No API key needed — public endpoint.
    """
    try:
        url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        with urllib.request.urlopen(url, timeout=10) as r:
            ids = json.loads(r.read())[:n]

        stories = []
        for sid in ids:
            try:
                item_url = f"https://hacker-news.firebaseio.com/v0/item/{sid}.json"
                with urllib.request.urlopen(item_url, timeout=5) as r:
                    item = json.loads(r.read())
                if item and item.get("type") == "story":
                    title = item.get("title", "")
                    link = item.get("url", f"https://news.ycombinator.com/item?id={sid}")
                    score = item.get("score", 0)
                    stories.append(f"- [{title}]({link}) ({score} pts)")
            except Exception:
                continue

        if stories:
            return "## Hacker News Top Stories\n" + "\n".join(stories)
        return ""
    except Exception as e:
        return f"[HN fetch failed: {e}]"


def fetch_arxiv_papers(query: str = "AI agents LLM reasoning", max_results: int = 6) -> str:
    """
    Fetch recent arXiv papers via their public API.
    No API key needed.
    """
    try:
        q = urllib.parse.quote(query)
        url = (
            f"http://export.arxiv.org/api/query"
            f"?search_query=all:{q}&start=0&max_results={max_results}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )

        with urllib.request.urlopen(url, timeout=15) as r:
            xml_data = r.read()

        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        papers = []
        for entry in entries:
            title = entry.find("atom:title", ns)
            summary = entry.find("atom:summary", ns)
            link = entry.find("atom:id", ns)
            if title is not None and summary is not None:
                t = title.text.strip().replace("\n", " ")
                s = summary.text.strip().replace("\n", " ")[:200]
                l = link.text.strip() if link is not None else ""
                papers.append(f"- **{t}**\n  {s}…")

        if papers:
            return "## Recent arXiv Papers\n" + "\n".join(papers)
        return ""
    except Exception as e:
        return f"[arXiv fetch failed: {e}]"

def load_voice_corrections() -> str:
    """Load voice correction examples to guide Clippy's writing style."""
    from pathlib import Path
    path = Path.home() / "clippy" / "voice-corrections.md"
    if path.exists():
        content = path.read_text().strip()
        if len(content) > 200:  # only inject if there are actual corrections
            return content
    return ""

def fetch_brave_search(query: str, count: int = 5) -> str:
    """
    Search the web via Brave Search API.
    Better quality results than generic web search for specific queries.
    """
    try:
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return "[Brave Search: no API key]"

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
        params = urllib.parse.urlencode({"q": query, "count": count})
        req = urllib.request.Request(f"{url}?{params}", headers=headers)

        import gzip
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            data = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)

        results = data.get("web", {}).get("results", [])
        if not results:
            return f"[Brave Search: no results for '{query}']"

        lines = [f"## Brave Search: {query}"]
        for item in results:
            title = item.get("title", "")
            link = item.get("url", "")
            desc = item.get("description", "")[:150]
            lines.append(f"- **{title}**\n  {desc}\n  {link}")

        return "\n".join(lines)
    except Exception as e:
        return f"[Brave Search failed: {e}]"


def fetch_github_releases(repos: list = None) -> str:
    """
    Check a list of GitHub repos for releases in the last 48 hours.
    repos: list of 'owner/repo' strings
    No API key needed for public repos, but token increases rate limit.
    """
    if repos is None:
        repos = [
            "anthropics/anthropic-sdk-python",
            "modelcontextprotocol/servers",
            "BerriAI/litellm",
            "openai/openai-python",
            "tauri-apps/tauri",
        ]

    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        from datetime import timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        new_releases = []

        for repo in repos:
            try:
                url = f"https://api.github.com/repos/{repo}/releases/latest"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as r:
                    release = json.loads(r.read())

                published = release.get("published_at", "")
                if published:
                    pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if pub_dt > cutoff:
                        name = release.get("name") or release.get("tag_name", "")
                        html_url = release.get("html_url", "")
                        body = release.get("body", "")[:200].replace("\n", " ")
                        new_releases.append(f"- **{repo}** — {name}\n  {body}\n  {html_url}")
            except Exception:
                continue

        if new_releases:
            return "## New GitHub Releases (last 48h)\n" + "\n".join(new_releases)
        return "## GitHub Releases: no new releases in tracked repos"

    except Exception as e:
        return f"[GitHub releases failed: {e}]"

# ── Core Research Function ─────────────────────────────────────────────────

def research(job_name: str, prompt: str, walnut_context: str = "", project_context: str = "") -> str:
    """Run a research job using Claude with web_search tool."""
    today = datetime.now().strftime("%Y-%m-%d")

    system_prompt = (
        "You are Clippy, a direct and efficient AI research agent. "
        "No fluff. Be concise and actionable.\n\n"
        "Every brief you produce starts with:\n"
        f'"📎 Clippy | {job_name} | {today}"\n\n'
        "Rules:\n"
        "- Bulleted findings, tight, max 400 words per brief\n"
        "- Always end with one '→ Action:' line: what Robert should do or watch\n"
        "- Use web_search to find current information\n"
        "- Be specific: include names, dates, links when available\n"
    )

    if project_context:
        system_prompt += (
            "\n\n== ROBERT'S ACTIVE PROJECTS ==\n"
            "Use this context to make your research relevant to what Robert is actually building. "
            "Flag findings that directly relate to his current tasks or blockers.\n\n"
            f"{project_context[:3000]}"
        )

    if walnut_context:
        system_prompt += (
            "\n\n== PREVIOUS FINDINGS (avoid repeating) ==\n"
            f"{walnut_context[-2000:]}"
        )

    corrections = load_voice_corrections()
    if corrections:
        system_prompt += (
            "\n\n== VOICE CORRECTIONS ==\n"
            "These are specific edits made to your past output. Avoid these patterns:\n\n"
            f"{corrections[-2000:]}"
        )

    messages = [{"role": "user", "content": prompt}]
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

    # Try OpenRouter (Qwen 3.6 Plus) first — note: no web_search tool, Qwen uses its own
    # For web search capability we fall back to Claude Haiku via Anthropic
    # Qwen handles the synthesis; Claude handles tool-based search jobs
    if openrouter_key:
        try:
            or_messages = [{"role": "system", "content": system_prompt}] + messages
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://clippy.local",
                    "X-Title": "Clippy Research Agent",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": or_messages,
                    "max_tokens": 4096,
                    "temperature": 0,
                    "plugins": [{"id": "web", "max_results": 5}],
                },
                timeout=60,
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            pass  # fall through to Anthropic fallback

    # Fallback: Claude Haiku via Anthropic SDK (supports web_search tool)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=FALLBACK_MODEL,
        max_tokens=4096,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=messages,
    )

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
            model=FALLBACK_MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages,
        )

    return "".join(b.text for b in response.content if hasattr(b, "text"))


# ── Research Jobs ──────────────────────────────────────────────────────────

def ai_fringe_research(walnut_context: str = "", project_context: str = "") -> str:
    """07:45 daily — AI & Fringe Science research with pre-fetched HN + arXiv + Brave data."""

    hn_data = fetch_hn_stories(n=15)
    arxiv_ai = fetch_arxiv_papers("AI agents LLM reasoning tool use", max_results=6)
    arxiv_frontier = fetch_arxiv_papers("robotics embodied AI manipulation locomotion", max_results=4)
    arxiv_quantum = fetch_arxiv_papers("quantum computing neuromorphic mathematics breakthrough formal proofs", max_results=4)
    arxiv_neuro = fetch_arxiv_papers("neuroscience brain-computer interface neural coding AI", max_results=4)
    arxiv_physics = fetch_arxiv_papers("physics AI implications protein folding computational discovery", max_results=4)
    arxiv_math = fetch_arxiv_papers("pure mathematics topology algebra number theory breakthrough", max_results=4)
    arxiv_stats = fetch_arxiv_papers("statistics probability inference causal discovery", max_results=4)
    arxiv_quantbio = fetch_arxiv_papers("quantitative biology systems biology computational genomics", max_results=4)
    arxiv_quantfin = fetch_arxiv_papers("quantitative finance market microstructure algorithmic trading", max_results=4)
    arxiv_econ = fetch_arxiv_papers("economics mechanism design game theory complexity", max_results=4)
    arxiv_ee = fetch_arxiv_papers("electrical engineering signal processing neuromorphic hardware", max_results=4)
    arxiv_systems = fetch_arxiv_papers("systems science complexity emergence self organization", max_results=4)
    arxiv_cs = fetch_arxiv_papers("computer science complexity theory cryptography distributed systems", max_results=4)
    brave_ai = fetch_brave_search("AI breakthrough today")
    brave_robotics = fetch_brave_search("robotics research 2026")
    brave_quantum = fetch_brave_search("quantum computing news")
    github_data = fetch_github_releases()

    prompt = (
        "Research the latest AI and fringe science news for today.\n\n"
        "I've pre-fetched these data sources — use them as primary input:\n\n"
        f"{hn_data}\n\n"
        f"## arXiv: AI & LLMs\n{arxiv_ai}\n\n"
        f"## arXiv: Robotics & Embodied AI\n{arxiv_frontier}\n\n"
        f"## arXiv: Quantum, Neuromorphic & Math\n{arxiv_quantum}\n\n"
        f"## arXiv: Neuroscience × AI\n{arxiv_neuro}\n\n"
        f"## arXiv: Physics & Computational Discovery\n{arxiv_physics}\n\n"
        f"## arXiv: Pure Mathematics\n{arxiv_math}\n\n"
        f"## arXiv: Statistics & Probability\n{arxiv_stats}\n\n"
        f"## arXiv: Quantitative Biology\n{arxiv_quantbio}\n\n"
        f"## arXiv: Quantitative Finance\n{arxiv_quantfin}\n\n"
        f"## arXiv: Economics\n{arxiv_econ}\n\n"
        f"## arXiv: Electrical Engineering\n{arxiv_ee}\n\n"
        f"## arXiv: Systems Science\n{arxiv_systems}\n\n"
        f"## arXiv: Computer Science\n{arxiv_cs}\n\n"
        f"{brave_ai}\n\n"
        f"{brave_robotics}\n\n"
        f"{brave_quantum}\n\n"
        f"{github_data}\n\n"
        f"Today is {datetime.now().strftime('%B %d, %Y')}. "
        "Use ONLY the pre-fetched data above for all specific prices, figures, and market levels — "
        "do NOT use your training data for any market figures as it is outdated. "
        "The data above is live and current.\n\n"
        "Based on the above:\n"
        "1. Pick the most relevant HN stories (AI, LLMs, coding tools, agent frameworks, science)\n"
        "2. Pick the most interesting arXiv papers across ALL categories — AI, robotics, "
        "quantum, neuro, physics, math, statistics, biology, economics, electrical "
        "engineering, systems science, computer science, quantitative finance. "
        "Cast wide. The most interesting finding might come from any domain.\n"
        "3. Use web_search for any breaking news NOT covered above\n\n"
        "Summarize top 5-6 findings total. For each finding:\n"
        "- Title + 80 word summary of what it is\n"
        "- One line: 'Assumption it challenges:' — what accepted belief does this push back on?\n"
        "- One line: 'Cross-domain signal:' — what other field does this remind you of or connect to?\n"
        "- One line: 'Open question:' — what would you need to know to evaluate if this is real?\n\n"
        "Do NOT flag for specific projects. Stay curious and broad.\n"
        "End with: '→ Darwin seed:' — one sentence on the most interesting unresolved "
        "question across ALL findings today. Something nobody has answered yet."
    )
    return research("AI & Fringe Science", prompt, walnut_context, project_context)


def finance_geo_research(walnut_context: str = "") -> str:
    """16:00 daily — Finance & Geopolitics research via Brave Search + arXiv."""

    brave_markets = fetch_brave_search("financial markets today")
    brave_central = fetch_brave_search("Federal Reserve Bank of Canada ECB news today")
    brave_energy = fetch_brave_search("OPEC oil price energy markets news today")
    brave_geopolitics = fetch_brave_search("trade war sanctions geopolitical conflict today")
    brave_indices = fetch_brave_search("S&P 500 bond yields commodities today")
    arxiv_econ = fetch_arxiv_papers("monetary policy financial markets macroeconomics", max_results=4)

    prompt = (
        "Research finance and geopolitics news for today.\n\n"
        "I've pre-fetched these data sources — use them as primary input:\n\n"
        f"{brave_markets}\n\n"
        f"{brave_central}\n\n"
        f"{brave_energy}\n\n"
        f"{brave_geopolitics}\n\n"
        f"{brave_indices}\n\n"
        f"{arxiv_econ}\n\n"
        f"Today is {datetime.now().strftime('%B %d, %Y')}. "
        "Use ONLY the pre-fetched data above for all prices and market levels — do NOT use your training data for any market figures. "
        "The data above is live and current. Your training data for prices is outdated.\n\n"
        "Based on the above:\n"
        "1. Identify the most significant market moves and central bank actions\n"
        "2. Flag geopolitical developments with market implications\n"
        "3. Use web_search for any breaking financial news NOT covered above\n\n"
        "Summarize top 2-3 findings, each with title + 100 word summary max.\n"
        "Flag anything relevant to Robert's portfolio "
        "(he holds energy ETFs, gold, Canadian equities).\n"
        "End with a single → Action line."
    )
    return research("Finance & Geopolitics", prompt, walnut_context)


def cre_market_research(walnut_context: str = "", project_context: str = "") -> str:
    """Monday 10:00 — CRE Weekly research, guided by Klaus + CRE-LLM project context."""

    brave_cre = fetch_brave_search("Canadian commercial real estate news this week")
    brave_renx = fetch_brave_search("RENx.ca commercial real estate")
    brave_storeys = fetch_brave_search("Storeys commercial real estate Canada")
    brave_cmhc = fetch_brave_search("CMHC housing market Canada")
    brave_caprate = fetch_brave_search("cap rate Canada 2026")
    brave_invest = fetch_brave_search("Canadian CRE investment 2026")

    prompt = (
        "Research Canadian commercial real estate (CRE) news for this week.\n\n"
        "I've pre-fetched these data sources — use them as primary input:\n\n"
        f"{brave_cre}\n\n"
        f"{brave_renx}\n\n"
        f"{brave_storeys}\n\n"
        f"{brave_cmhc}\n\n"
        f"{brave_caprate}\n\n"
        f"{brave_invest}\n\n"
        f"Today is {datetime.now().strftime('%B %d, %Y')}. "
        "Use ONLY the pre-fetched data above for all specific prices, figures, and market levels — "
        "do NOT use your training data for any market figures as it is outdated. "
        "The data above is live and current.\n\n"
        "Based on the above:\n"
        "1. Identify major CRE transactions, policy changes, market trends\n"
        "2. Track cap rate movements and investment activity\n"
        "3. Use web_search for any breaking CRE news NOT covered above\n\n"
        "Summarize top 5-6 articles, each with title + 100 word summary max.\n"
        "Flag anything relevant to Klaus or CRE-LLM.\n"
        "End with a single → Action line."
    )
    return research("CRE Weekly", prompt, walnut_context, project_context)


def deep_dive(ai_context: str = "", finance_context: str = "", cre_context: str = "", project_contexts: dict = None) -> str:
    """21:00 daily — Deep dive on the most impactful finding across all topics."""
    project_contexts = project_contexts or {}
    project_block = "".join(
        f"\n=== {name.upper()} ===\n{ctx[:800]}\n"
        for name, ctx in project_contexts.items() if ctx
    )

    prompt = (
        "You are doing a deep dive on the single most intellectually interesting "
        "finding from today's research. Not the most actionable — the most "
        "*interesting*. The one that makes you question something you thought was settled.\n\n"
        "Pick it from the findings below. Then:\n\n"
        "1. What is it? (50 words max)\n"
        "2. What assumption does it challenge? Be specific about what the field "
        "currently believes and why this finding puts pressure on that belief.\n"
        "3. Is this theory or practice? What would it take to move from one to the other?\n"
        "4. What does this connect to in a completely different domain? "
        "Think across physics, biology, mathematics, economics, cognition — "
        "not just tech. The best insights are cross-domain.\n"
        "5. What's the strongest argument AGAINST this finding? "
        "Play devil's advocate seriously, not politely.\n"
        "6. If this is real and it compounds over 5 years — what exists that "
        "doesn't exist today? Be specific and imaginative.\n\n"
        "Write 350-450 words. No project flags. No action items. "
        "End with one '→ Open question:' that Darwin should sit with.\n\n"
        f"Today's AI & Fringe Science findings:\n{ai_context[:2000]}\n\n"
        f"Today's Finance & Geopolitics findings:\n{finance_context[:1000]}\n\n"
        f"Today's CRE findings:\n{cre_context[:1000]}\n\n"
    )
    return research("Deep Dive", prompt)


def weekly_summary(ai_context: str = "", finance_context: str = "", cre_context: str = "", project_contexts: dict = None) -> str:
    """Monday 08:00 — Weekly intel summary with project-specific action items."""
    project_contexts = project_contexts or {}
    project_block = "".join(
        f"\n=== {name.upper()} ===\n{ctx[:600]}\n"
        for name, ctx in project_contexts.items() if ctx
    )

    prompt = (
        "Synthesize the past week's research into a weekly intelligence summary.\n\n"
        "Structure:\n"
        "1. **Top AI & Fringe Science Themes** — 3 biggest developments this week\n"
        "2. **Top Finance & Geopolitics Themes** — 3 biggest developments this week\n"
        "3. **Top CRE Themes** — 3 biggest CRE developments\n"
        "4. **Project Relevance** — For each active project (Agent Network, Klaus, CRE-LLM), "
        "what from this week's research is most relevant? One bullet per project.\n"
        "5. **Action Items** — What should Robert act on this week?\n"
        "6. **Watch List** — What to monitor going forward?\n\n"
        f"AI & Fringe Science findings from this week:\n{ai_context[-3000:]}\n\n"
        f"Finance & Geopolitics findings from this week:\n{finance_context[-3000:]}\n\n"
        f"CRE findings from this week:\n{cre_context[-3000:]}\n\n"
        f"Active project context:\n{project_block}"
    )
    return research("Weekly Intel Summary", prompt)