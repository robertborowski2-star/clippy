"""Clippy's brain — calls Claude with web_search tool for research jobs."""

import anthropic
import urllib.request
import urllib.parse
import json
import os
import re
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


# ── CRE source RSS fetchers ────────────────────────────────────────────────

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _fetch_rss(url: str, max_items: int = 15, keyword_filter: list = None,
               over_fetch_factor: int = 4) -> list:
    """Generic RSS 2.0 fetcher.

    Returns a list of dicts: {title, link, description, categories}.
    If keyword_filter is provided, items matching any keyword (in title,
    description, or category) are kept; others dropped. We over-fetch to
    compensate for filter rejections.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": "Clippy-Research-Agent/1.0 (+https://github.com/robertborowski2-star/clippy)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        xml_data = r.read()

    root = ET.fromstring(xml_data)
    channel = root.find("channel")
    if channel is None:
        return []

    raw_items = channel.findall("item")
    fetch_cap = max_items * over_fetch_factor if keyword_filter else max_items

    results = []
    for item in raw_items[:fetch_cap]:
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        cats = [c.text for c in item.findall("category") if c.text]

        title = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
        link = (link_el.text or "").strip() if link_el is not None and link_el.text else ""
        desc_raw = (desc_el.text or "").strip() if desc_el is not None and desc_el.text else ""
        desc = _HTML_TAG_RE.sub("", desc_raw).strip()[:300]

        if keyword_filter:
            haystack = (title + " " + desc + " " + " ".join(cats)).lower()
            if not any(kw.lower() in haystack for kw in keyword_filter):
                continue

        results.append({
            "title": title, "link": link, "description": desc, "categories": cats,
        })
        if len(results) >= max_items:
            break

    return results


def _format_rss_section(heading: str, items: list) -> str:
    """Render a list of RSS dicts as a markdown section."""
    if not items:
        return f"## {heading}\n_(no recent items)_"
    lines = [f"## {heading}"]
    for it in items:
        line = f"- **{it['title']}** ({it['link']})"
        if it["description"]:
            line += f"\n  {it['description']}"
        lines.append(line)
    return "\n".join(lines)


def _slug_to_title(slug: str) -> str:
    """Convert a URL slug like 'hudson-s-bay-ccaa-ruling' to 'Hudson S Bay Ccaa Ruling'."""
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split() if w)


def _fetch_sitemap_recent(url: str, prefix: str = "", max_items: int = 15) -> list:
    """Fetch a sitemap.xml, return the most recent entries by lastmod desc.

    prefix: only include URLs starting with this string. Used to filter to
    article paths (e.g., '/p/' on Insolvency Insider) and skip taxonomy
    pages, author bios, and the homepage.

    Returns list of dicts: {url, lastmod, slug, title}.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": "Clippy-Research-Agent/1.0",
        "Accept": "application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()

    root = ET.fromstring(raw)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    url_elements = root.findall("sm:url", ns)

    entries = []
    for u in url_elements:
        loc_el = u.find("sm:loc", ns)
        mod_el = u.find("sm:lastmod", ns)
        if loc_el is None or not loc_el.text:
            continue
        loc = loc_el.text.strip()
        if prefix and not loc.startswith(prefix):
            continue
        if not prefix and loc.endswith("/"):
            continue
        mod = mod_el.text.strip() if mod_el is not None and mod_el.text else "1970-01-01"
        slug = loc.rstrip("/").rsplit("/", 1)[-1]
        entries.append({
            "url": loc,
            "lastmod": mod,
            "slug": slug,
            "title": _slug_to_title(slug),
        })

    # ISO-8601 timestamps sort lexically the same as chronologically.
    entries.sort(key=lambda e: e["lastmod"], reverse=True)
    return entries[:max_items]


def _format_sitemap_section(heading: str, entries: list) -> str:
    """Render a list of sitemap entry dicts as a markdown section."""
    if not entries:
        return f"## {heading}\n_(no recent items)_"
    lines = [f"## {heading}"]
    for e in entries:
        lines.append(f"- **{e['title']}** ({e['url']}) — {e['lastmod'][:10]}")
    return "\n".join(lines)


def fetch_renx(max_items: int = 20) -> str:
    """Fetch recent RENx.ca articles via their posts sitemap.

    RENx doesn't expose an RSS feed, so we use their posts sitemap and derive
    titles from URL slugs. Slug-derived titles are imperfect (e.g., 'Nyc'
    instead of 'NYC') but readable enough for the LLM to identify interesting
    stories. All RENx content is CRE-focused so no keyword filter needed.
    """
    try:
        entries = _fetch_sitemap_recent(
            "https://renx.ca/sitemaps/posts-1.xml",
            prefix="https://renx.ca/",
            max_items=max_items,
        )
        return _format_sitemap_section("RENx — Recent Articles (sitemap)", entries)
    except Exception as e:
        return f"[RENx fetch failed: {e}]"


def fetch_storeys(max_items: int = 15) -> str:
    """Fetch recent Storeys articles via RSS."""
    try:
        items = _fetch_rss("https://storeys.com/feed/", max_items=max_items)
        return _format_rss_section("Storeys — Recent Articles", items)
    except Exception as e:
        return f"[Storeys fetch failed: {e}]"


def fetch_insolvency_insider(max_items: int = 15) -> str:
    """Fetch recent Insolvency Insider filings via their sitemap.

    Insolvency Insider is a SPA with no RSS, so we use their sitemap. Filtered
    to article paths (`/p/...`) only. Items are NOT keyword-filtered to real
    estate at fetch time — slug-only matching would miss CRE-relevant entries
    like 'Hudson's Bay CCAA' (no 'real estate' keyword in slug). The CRE prompt
    instructs the LLM to do the relevance filtering instead, which works well
    because slugs carry the company name and case type.
    """
    try:
        entries = _fetch_sitemap_recent(
            "https://insolvencyinsider.ca/sitemap.xml",
            prefix="https://insolvencyinsider.ca/p/",
            max_items=max_items,
        )
        return _format_sitemap_section(
            "Insolvency Insider — Recent Canadian Filings (unfiltered; LLM curates to CRE)",
            entries,
        )
    except Exception as e:
        return f"[Insolvency Insider fetch failed: {e}]"

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
        "Summarize top 10-12 findings total. For each finding:\n"
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
    """Monday 10:00 — CRE Weekly research, guided by Klaus + CRE-LLM project context.

    Output is structured for both walnut accumulation AND email delivery to
    a colleague distribution list. Slightly more polished than other jobs:
    executive summary intro, named themes as `## ` level-2 headings, and
    sourced findings under each theme. The `## ` headings remain intact so
    Darwin's chunker still works.
    """

    # Direct trade-press feeds. Storeys = real RSS; RENx and Insolvency
    # Insider = sitemap-derived (no RSS available). Sitemap entries carry
    # only URL + lastmod; titles are slug-derived (imperfect capitalization
    # but readable). Insolvency Insider is unfiltered — the LLM filters
    # to CRE-relevance below.
    rss_renx = fetch_renx(max_items=20)
    rss_storeys = fetch_storeys(max_items=15)
    rss_insolvency = fetch_insolvency_insider(max_items=15)

    # Brave Search — broader market context the trade press may not catch.
    brave_cmhc = fetch_brave_search("CMHC housing market Canada")
    brave_caprate = fetch_brave_search("cap rate Canada 2026")
    brave_invest = fetch_brave_search("Canadian CRE investment 2026")

    prompt = (
        "Research Canadian commercial real estate (CRE) news for this week. "
        "This brief is sent by email to senior CRE executives, so format and "
        "tone should be polished and professional — but still tight, no fluff.\n\n"
        "I've pre-fetched these data sources — use them as primary input:\n\n"
        f"{rss_renx}\n\n"
        f"{rss_storeys}\n\n"
        f"{rss_insolvency}\n\n"
        f"{brave_cmhc}\n\n"
        f"{brave_caprate}\n\n"
        f"{brave_invest}\n\n"
        f"Today is {datetime.now().strftime('%B %d, %Y')}. "
        "Use ONLY the pre-fetched data above for all specific prices, figures, "
        "and market levels — do NOT use your training data for any market "
        "figures as it is outdated. The data above is live and current. "
        "If a finding's source isn't in the pre-fetched data, use web_search "
        "to verify before including it.\n\n"
        "OUTPUT STRUCTURE — STRICT (downstream tooling depends on it):\n\n"
        "Open with: '📎 Clippy | Weekly Canadian CRE Brief | <date>'\n\n"
        "Then a **2-3 sentence executive summary** in plain prose — what's "
        "the headline of the week? (No bullet list here. Read like a Bloomberg "
        "Daybook lede.)\n\n"
        "Then 3-5 named themes, each as a `## ICON N. Theme Name` level-2 "
        "heading. Theme names should be specific (e.g., 'Cap Rate Compression "
        "in Industrial', 'Hotel Distress / Receiverships', 'Office-to-Resi "
        "Conversions', 'Multi-Family Transactions', 'Policy & Regulation'). "
        "Use the headings to group findings, not to label individual articles.\n\n"
        "Under each theme:\n"
        "- 2-4 findings as bullet points\n"
        "- Each finding: bolded headline + 50-80 word summary + source link "
        "in parentheses\n"
        "- Where relevant, include cap rates, $/sqft, transaction sizes, "
        "and named parties (buyer/seller/broker)\n\n"
        "Insolvency Insider items are valuable — distressed assets matter "
        "for acquisition pipelines. The list above is UNFILTERED Canadian "
        "filings; you must curate to CRE-relevant items only. Include: "
        "real estate, REITs, retail (tenant collapses → vacancy), "
        "hospitality (hotel chains, restaurants), construction, "
        "developers, landlords, REITs, building owners. Skip: pure "
        "fintech failures, unrelated industrial bankruptcies with no real "
        "estate footprint, individual personal bankruptcies. When you "
        "include one, give it its own theme if notable (e.g., a major "
        "retailer's CCAA filing reshapes the retail CRE landscape).\n\n"
        "Note on titles in RENx and Insolvency Insider sources: those are "
        "derived from URL slugs (e.g., 'Hudson S Bay Ccaa Proceedings' "
        "really means 'Hudson's Bay CCAA Proceedings'). Render them with "
        "proper capitalization and apostrophes when you include them in "
        "the brief. Use web_search to verify details if a slug-titled item "
        "looks important.\n\n"
        "End with two lines:\n"
        "  '→ Watch this week:' one specific thing to monitor\n"
        "  '→ Action:' one specific thing Robert (or readers) should consider doing\n\n"
        "Flag anything directly relevant to Klaus or CRE-LLM in the relevant "
        "theme inline (don't add a separate project section)."
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