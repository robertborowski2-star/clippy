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


# Primary model via OpenRouter. Reverted 2026-05-06 from qwen3-30b-a3b back
# to qwen3-235b-a22b — the 30B was hallucinating training-data figures
# instead of grounding in the pre-fetched Brave/arXiv context (finance-geo
# briefs were inventing Fed/BoC rates and oil prices that weren't in any
# pre-fetched snippet). If 235B still shows the same drift, escalate to
# Claude Sonnet 4.6 with the real web_search_20250305 tool.
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


def fetch_arxiv_by_category(categories: list, max_results: int = 50) -> str:
    """
    Fetch recent arXiv papers from specific categories.
    categories: list of arXiv cat strings, e.g. ['math.NT', 'math.AG'] or ['math.*'].
    """
    try:
        cat_query = " OR ".join(f"cat:{c}" for c in categories)
        q = urllib.parse.quote(cat_query)
        url = (
            f"http://export.arxiv.org/api/query"
            f"?search_query={q}&start=0&max_results={max_results}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )

        with urllib.request.urlopen(url, timeout=20) as r:
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
                s = summary.text.strip().replace("\n", " ")[:250]
                l = link.text.strip() if link is not None else ""
                papers.append(f"- **{t}** ({l})\n  {s}…")

        if papers:
            return "\n".join(papers)
        return ""
    except Exception as e:
        return f"[arXiv category fetch failed: {e}]"


def fetch_chemrxiv(max_results: int = 50, days_back: int = 14) -> str:
    """
    Fetch recent ChemRxiv preprints via Crossref's public API, filtered by
    ChemRxiv's DOI prefix (10.26434).

    ChemRxiv's own API sits behind Cloudflare and rejects automated requests,
    so we use Crossref as the source of truth. Crossref records carry titles
    and DOIs but not abstracts for ChemRxiv deposits — title-only is fine for
    a curated roundup.
    """
    try:
        from datetime import date, timedelta
        since = (date.today() - timedelta(days=days_back)).isoformat()
        url = (
            f"https://api.crossref.org/works"
            f"?filter=prefix:10.26434,from-pub-date:{since}"
            f"&rows={max_results}&sort=published&order=desc"
            f"&mailto=clippy@local"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())

        items = data.get("message", {}).get("items", [])
        papers = []
        for item in items[:max_results]:
            title_list = item.get("title") or [""]
            title = title_list[0].strip().replace("\n", " ") if title_list else ""
            doi = item.get("DOI", "")
            link = f"https://doi.org/{doi}" if doi else ""
            pub = item.get("published", {}).get("date-parts", [[None]])[0]
            pub_str = "-".join(str(p) for p in pub if p) if pub and pub[0] else ""
            if title:
                papers.append(f"- **{title}** ({link}) [{pub_str}]")

        if papers:
            return "\n".join(papers)
        return ""
    except Exception as e:
        return f"[ChemRxiv fetch failed: {e}]"


def fetch_eartharxiv(max_results: int = 50) -> str:
    """
    Fetch recent EarthArxiv preprints via OSF's public API.
    EarthArxiv is hosted on OSF; no API key needed.
    """
    try:
        url = (
            f"https://api.osf.io/v2/preprints/"
            f"?filter[provider]=eartharxiv"
            f"&page[size]={max_results}"
            f"&sort=-date_published"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())

        papers = []
        for entry in data.get("data", [])[:max_results]:
            attrs = entry.get("attributes", {})
            title = (attrs.get("title") or "").strip().replace("\n", " ")
            desc = (attrs.get("description") or "").strip().replace("\n", " ")[:250]
            link = entry.get("links", {}).get("html", "")
            if title:
                papers.append(f"- **{title}** ({link})\n  {desc}…")

        if papers:
            return "\n".join(papers)
        return ""
    except Exception as e:
        return f"[EarthArxiv fetch failed: {e}]"


def load_voice_corrections() -> str:
    """Load voice correction examples to guide Clippy's writing style."""
    from pathlib import Path
    path = Path.home() / "clippy" / "voice-corrections.md"
    if path.exists():
        content = path.read_text().strip()
        if len(content) > 200:  # only inject if there are actual corrections
            return content
    return ""

def fetch_brave_search(query: str, count: int = 8, freshness: str = "pw") -> str:
    """
    Search the web via Brave Search API. Returns a markdown section with
    title, age, full description, and up to 2 extra snippets per result.

    count: number of results (1–20, default 8).
    freshness: time filter — 'pd' (past day), 'pw' (past week, default),
               'pm' (past month), 'py' (past year), or 'all' to disable.
               Tighter freshness = fewer stale snippets the LLM can mistake
               for current data. Default 'pw' is the safe middle ground;
               finance jobs should pass 'pd' for breaking-news queries.

    Each result is rendered with the age tag when present, the full
    description (no 150-char cap — that was strangling the LLM's grounding),
    and up to 2 extra_snippets per result. This gives ~500–1500 chars of
    real text per result, so the LLM has substance to ground in instead of
    pattern-matching from training data.
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
        params_dict = {
            "q": query,
            "count": min(count, 20),
            "extra_snippets": 1,
        }
        if freshness and freshness != "all":
            params_dict["freshness"] = freshness
        params = urllib.parse.urlencode(params_dict)
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
            desc = item.get("description", "")
            age = item.get("age", "")
            extras = item.get("extra_snippets", []) or []

            block = f"- **{title}**"
            if age:
                block += f" _(age: {age})_"
            if desc:
                block += f"\n  {desc}"
            for snip in extras[:2]:
                if snip:
                    block += f"\n  · {snip}"
            block += f"\n  {link}"
            lines.append(block)

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
                    "max_tokens": 8192,
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
        max_tokens=8192,
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
            max_tokens=8192,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages,
        )

    return "".join(b.text for b in response.content if hasattr(b, "text"))


# ── Research Jobs ──────────────────────────────────────────────────────────

def ai_fringe_research(walnut_context: str = "", project_context: str = "") -> str:
    """07:45 daily — AI & Fringe Science research with pre-fetched HN + arXiv + Brave data.

    Rebuilt 2026-05-21 with the same grounding treatment finance-geo got on
    2026-05-08. The prior version fetched 13 broad arXiv categories and 3
    generic undated Brave queries ("AI breakthrough today", "robotics
    research 2026", "quantum computing news"), then asked for 10-12 findings.
    The volume swamped the LLM and the undated Brave snippets left it
    pattern-matching from training data instead of grounding.

    Now: 6 focused arXiv categories, ~8 date-anchored Brave queries with
    `freshness="pw"` (weekly — AI moves slower than market data, daily
    would starve the model), 6-8 findings, and STRICT GROUNDING RULES
    matching finance-geo's. The per-finding analysis structure
    (Assumption / Cross-domain signal / Open question) stays — that's
    the synthesis layer Robert values; the fix is grounding the facts
    underneath it.
    """

    today = datetime.now()
    month_year = today.strftime("%B %Y")

    hn_data = fetch_hn_stories(n=15)

    # 6 load-bearing arXiv categories. The earlier 13 included stats,
    # quant-bio, quant-fin, econ, EE, systems, and generic CS — those rarely
    # produced selected findings and their volume crowded out the strong
    # categories. Kept: the 5 that consistently surfaced selectable papers
    # plus a dedicated "computational discovery" slot for AI-driven science
    # (protein folding, materials, drug discovery) that used to be folded
    # into the physics query.
    arxiv_ai = fetch_arxiv_papers("AI agents LLM reasoning tool use", max_results=6)
    arxiv_robotics = fetch_arxiv_papers("robotics embodied AI manipulation locomotion", max_results=4)
    arxiv_neuro = fetch_arxiv_papers("neuroscience brain-computer interface neural coding AI", max_results=4)
    arxiv_math = fetch_arxiv_papers("pure mathematics topology algebra number theory breakthrough", max_results=4)
    arxiv_physics = fetch_arxiv_papers("physics theoretical condensed matter quantum field", max_results=4)
    arxiv_compdisc = fetch_arxiv_papers("computational discovery protein folding materials drug discovery AI", max_results=4)

    # Date-anchored Brave queries with freshness=pw (past week). AI/science
    # news moves slower than markets, so weekly is the right window —
    # `freshness="pd"` would return mostly empty for queries like
    # "AI safety alignment research" on any given day. Month-anchoring
    # forces the LLM to ground in current content rather than recall.
    brave_queries = [
        f"AI research breakthrough {month_year}",
        f"large language model release {month_year}",
        f"AI agent framework news {month_year}",
        f"AI safety alignment research {month_year}",
        f"robotics research news {month_year}",
        f"quantum computing breakthrough {month_year}",
        f"neuroscience research news {month_year}",
        f"computational biology breakthrough {month_year}",
    ]
    brave_data = "\n\n".join(
        fetch_brave_search(q, count=8, freshness="pw") for q in brave_queries
    )

    github_data = fetch_github_releases()

    prompt = (
        "Research the latest AI and fringe science news for this week.\n\n"
        f"Today is {today.strftime('%A, %B %d, %Y')}.\n\n"
        "I've pre-fetched these data sources (HN + arXiv + fresh Brave Search "
        "results filtered to past week + recent GitHub releases). Use them as "
        "your PRIMARY and ONLY source for specific figures, dated claims, and "
        "named people/labs/papers:\n\n"
        f"{hn_data}\n\n"
        f"## arXiv: AI & LLMs\n{arxiv_ai}\n\n"
        f"## arXiv: Robotics & Embodied AI\n{arxiv_robotics}\n\n"
        f"## arXiv: Neuroscience × AI\n{arxiv_neuro}\n\n"
        f"## arXiv: Pure Mathematics\n{arxiv_math}\n\n"
        f"## arXiv: Physics\n{arxiv_physics}\n\n"
        f"## arXiv: Computational Discovery\n{arxiv_compdisc}\n\n"
        f"{brave_data}\n\n"
        f"{github_data}\n\n"
        "STRICT GROUNDING RULES — these are not suggestions:\n"
        "1. Every specific figure (benchmark scores, parameter counts, "
        "training compute, funding amounts, dates) MUST appear verbatim or "
        "near-verbatim in the data above. If you cannot find a figure in the "
        "data, OMIT it. Do NOT fill in plausible-sounding numbers from "
        "training memory.\n"
        "2. Every dated event (paper release, model launch, lab "
        "announcement, conference result) MUST be findable in the data and "
        "dated within the last 30 days. If you cannot find a recent date, "
        "do NOT mention the event.\n"
        "3. Every named person, lab, or company MUST appear in the data. "
        "Do NOT name researchers, founders, or executives from memory — "
        "people change roles and your training data is stale.\n"
        "4. Every cited source URL must come from the data above. One URL "
        "per finding minimum. If you cannot cite, you do not have grounding "
        "for that finding — drop it.\n"
        "5. Do NOT use template phrases that you would write regardless of "
        "this week's actual news. Forbidden examples: 'rapid progress "
        "continues', 'the field is moving fast', 'scaling laws hold', "
        "'capabilities are accelerating'. These are tells of training-data "
        "padding, not current reporting.\n"
        "6. If the data is thin on a topic, write fewer findings or drop "
        "the topic. A 4-finding brief grounded in real data beats an "
        "8-finding brief padded with fabrications.\n\n"
        "Based on the data above, summarize 6-8 findings. Cast wide — the "
        "most interesting finding might come from any category, not just "
        "AI/LLM. For each finding:\n"
        "- Title + 80 word summary built from the data\n"
        "- At least one source URL in parentheses\n"
        "- One line: 'Assumption it challenges:' — what accepted belief does "
        "this push back on?\n"
        "- One line: 'Cross-domain signal:' — what other field does this "
        "remind you of or connect to?\n"
        "- One line: 'Open question:' — what would you need to know to "
        "evaluate if this is real?\n\n"
        "Do NOT flag for specific projects. Stay curious and broad.\n"
        "End with: '→ Darwin seed:' — one sentence on the most interesting "
        "unresolved question across ALL findings today. Something nobody "
        "has answered yet."
    )
    return research("AI & Fringe Science", prompt, walnut_context, project_context)


def finance_geo_research(walnut_context: str = "") -> str:
    """16:00 daily — Finance & Geopolitics research via Brave Search + arXiv.

    Pre-fetches a broad set of date-anchored Brave queries with `freshness=pd`
    (past day) so the LLM has 50+ KB of fresh, grounded snippets to work
    from. Generic queries like "financial markets today" returned thin
    headlines that the LLM would pad with hallucinated training-data figures
    (e.g., inventing Fed rates, oil prices, and "incoming Chair Warsh"
    narratives that hadn't been true in years). Date-anchored queries with
    full descriptions + extra snippets force the model to ground in real
    current data or write a shorter brief.
    """

    today = datetime.now()
    month_year = today.strftime("%B %Y")

    brave_queries = [
        f"Federal Reserve interest rate decision {month_year}",
        f"Bank of Canada interest rate {month_year}",
        f"ECB monetary policy {month_year}",
        "S&P 500 close today",
        "Nasdaq close today",
        "TSX index close today",
        "Brent crude oil price today",
        "WTI crude oil price today",
        "gold price today",
        "10 year Treasury yield today",
        "Canadian dollar USD exchange rate today",
        f"OPEC meeting {month_year}",
        "China economy news today",
        "Middle East geopolitics news today",
        "Canadian energy stocks news today",
    ]
    brave_data = "\n\n".join(
        fetch_brave_search(q, count=8, freshness="pd") for q in brave_queries
    )

    arxiv_econ = fetch_arxiv_papers(
        "monetary policy financial markets macroeconomics", max_results=4
    )

    prompt = (
        "Research finance and geopolitics news for today.\n\n"
        f"Today is {today.strftime('%A, %B %d, %Y')}.\n\n"
        "I've pre-fetched fresh web search results below (Brave Search, "
        "filtered to past 24 hours). Use these as your PRIMARY and ONLY "
        "source for current figures.\n\n"
        f"{brave_data}\n\n"
        f"{arxiv_econ}\n\n"
        "STRICT GROUNDING RULES — these are not suggestions:\n"
        "1. Every specific figure (rates, prices, index levels, yields, "
        "spreads) MUST appear verbatim or near-verbatim in the Brave Search "
        "snippets above. If you cannot find a figure in the snippets, OMIT "
        "it. Do NOT fill in plausible-sounding numbers from training data.\n"
        "2. Every dated event (meetings, decisions, reports, speeches) MUST "
        "be findable in the snippets and dated within the last 30 days. If "
        "you cannot find a recent date, do NOT mention the event.\n"
        "3. Every named person (officials, executives, politicians) MUST "
        "appear in the snippets. Do NOT name people from memory — "
        "leadership turns over and your training data is stale.\n"
        "4. Do NOT use template phrases that you would write regardless of "
        "today's news. Forbidden examples: 'Middle East tensions remain "
        "elevated', 'tariff risks loom', 'rotate Canadian equities into "
        "energy/materials', 'maximum pressure', 'wartime highs'. These are "
        "tells of training-data padding, not current reporting.\n"
        "5. Cite at least one source URL per finding. If you cannot cite, "
        "you do not have grounding for that finding — drop it.\n"
        "6. If the snippets are thin or contradictory, write a shorter "
        "brief or fewer findings. A 2-finding brief grounded in real "
        "snippets is infinitely better than a 5-finding brief padded with "
        "fabricated specifics.\n\n"
        "Summarize the top 3-5 findings. For each:\n"
        "- Title + 80-120 word summary built from the snippets\n"
        "- At least one source URL in parentheses\n"
        "Flag anything relevant to Robert's portfolio (he holds energy "
        "ETFs, gold, Canadian equities) — but only if you can substantiate "
        "the connection from real snippet content.\n"
        "End with a single → Action line that follows from the findings, "
        "not from generic portfolio advice."
    )
    return research("Finance & Geopolitics", prompt, walnut_context)


def deep_dive(ai_context: str = "", finance_context: str = "", project_contexts: dict = None) -> str:
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
        f"Today's AI & Fringe Science findings:\n{ai_context[:8000]}\n\n"
        f"Today's Finance & Geopolitics findings:\n{finance_context[:5000]}\n\n"
    )
    return research("Deep Dive", prompt)


def science_roundup_research(walnut_contexts: dict = None) -> str:
    """
    Saturday 01:00 weekly — broad science roundup across physics, mathematics,
    biology, chemistry, and earth/materials. Pulls from arXiv categories
    plus ChemRxiv (chemistry) and EarthArxiv (earth).

    Output is a single string with five sections delimited by sentinels of the
    form `===SECTION:NAME===`. The scheduler splits on these and writes each
    section to its corresponding walnut. Each section internally uses
    `## ICON N. Title` level-2 headings so Darwin can chunk per-finding.

    walnut_contexts: optional dict mapping subject name to prior walnut text,
    used for "avoid repeating" guidance. Keys: physics, mathematics, biology,
    chemistry, earth-materials.
    """
    walnut_contexts = walnut_contexts or {}

    physics_papers = fetch_arxiv_by_category(
        ["astro-ph.*", "gr-qc", "hep-th", "hep-ph", "quant-ph",
         "cond-mat.str-el", "cond-mat.supr-con"],
        max_results=50,
    )
    math_papers = fetch_arxiv_by_category(["math.*"], max_results=50)
    biology_papers = fetch_arxiv_by_category(["q-bio.*"], max_results=50)
    chem_arxiv = fetch_arxiv_by_category(["physics.chem-ph"], max_results=30)
    chem_chemrxiv = fetch_chemrxiv(max_results=50)
    earth_arxiv = fetch_arxiv_by_category(
        ["cond-mat.mtrl-sci", "cond-mat.soft", "physics.geo-ph", "physics.flu-dyn"],
        max_results=50,
    )
    earth_eartharxiv = fetch_eartharxiv(max_results=50)

    def _ctx_snippet(key: str) -> str:
        prior = walnut_contexts.get(key, "")
        return prior[-1500:] if prior else "(none)"

    prompt = (
        "Weekly science roundup. Survey recent research across five subjects "
        "and surface the 8-10 most interesting findings PER SUBJECT.\n\n"
        f"Today is {datetime.now().strftime('%B %d, %Y')}.\n\n"
        "OUTPUT FORMAT — STRICT:\n"
        "Produce five sections in this exact order, each preceded by its sentinel:\n"
        "  ===SECTION:PHYSICS===\n"
        "  ===SECTION:MATHEMATICS===\n"
        "  ===SECTION:BIOLOGY===\n"
        "  ===SECTION:CHEMISTRY===\n"
        "  ===SECTION:EARTH-MATERIALS===\n\n"
        "Within each section:\n"
        "- Start with: '📎 Clippy | <Subject> Roundup | <date>'\n"
        "- 8-10 findings, each formatted as a `## ICON N. Title` level-2 heading "
        "(this matters — downstream tooling chunks on `## `).\n"
        "- Under each heading: 60-100 word summary, then on a new line:\n"
        "  'Why it matters:' one sentence on what this challenges or unlocks.\n"
        "  'Cross-domain signal:' one sentence linking to another field.\n"
        "- End each section with: '→ Open question:' one line on the most "
        "intellectually unresolved thread.\n"
        "- Do NOT include any prose between sentinels and the section header.\n\n"
        "PHYSICS — sources to draw from:\n"
        "## arXiv: Physics (astro-ph, gr-qc, hep-*, quant-ph, cond-mat correlated)\n"
        f"{physics_papers}\n\n"
        f"Prior physics walnut (avoid repeating): {_ctx_snippet('physics')}\n\n"
        "MATHEMATICS — sources to draw from:\n"
        "## arXiv: Mathematics (math.*)\n"
        f"{math_papers}\n\n"
        f"Prior mathematics walnut (avoid repeating): {_ctx_snippet('mathematics')}\n\n"
        "BIOLOGY — sources to draw from:\n"
        "## arXiv: Quantitative Biology (q-bio.*)\n"
        f"{biology_papers}\n\n"
        f"Prior biology walnut (avoid repeating): {_ctx_snippet('biology')}\n\n"
        "CHEMISTRY — sources to draw from:\n"
        "## arXiv: Chemical Physics (physics.chem-ph)\n"
        f"{chem_arxiv}\n\n"
        "## ChemRxiv recent preprints\n"
        f"{chem_chemrxiv}\n\n"
        f"Prior chemistry walnut (avoid repeating): {_ctx_snippet('chemistry')}\n\n"
        "EARTH & MATERIALS — sources to draw from:\n"
        "## arXiv: Materials & Earth-adjacent (cond-mat.mtrl-sci, cond-mat.soft, "
        "physics.geo-ph, physics.flu-dyn)\n"
        f"{earth_arxiv}\n\n"
        "## EarthArxiv recent preprints\n"
        f"{earth_eartharxiv}\n\n"
        f"Prior earth-materials walnut (avoid repeating): {_ctx_snippet('earth-materials')}\n\n"
        "Pick what is most interesting, not most recent. Cast wide. "
        "Prefer findings that challenge assumptions or connect across subfields. "
        "Use ONLY the pre-fetched data above — do NOT use training data for any "
        "specific figures or claims; that data is outdated.\n"
    )
    return research("Science Roundup", prompt)