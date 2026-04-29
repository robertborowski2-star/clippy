"""Darwin ingestion hook.

Posts Clippy's research findings to Darwin's `/ingest` endpoint, fire-and-
forget, chunked on `## ` level-2 headings so each finding becomes one
ingestion in Darwin's graph rather than a 5-10 KB blob that would be
truncated to the first 4 KB by encode.py's subject extraction.

Reads `DARWIN_INGEST_URL` and `DARWIN_API_KEY` from the process environment.
If either is empty the hook is a no-op — Clippy can run with the integration
disabled (e.g. during a Darwin outage or in dev). Exceptions are caught and
logged at WARNING level; they never propagate, so a Darwin problem cannot
break Clippy's Telegram delivery or walnut writes.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime

import httpx

log = logging.getLogger("clippy.darwin_hook")

DARWIN_INGEST_URL = os.getenv("DARWIN_INGEST_URL", "")
DARWIN_API_KEY = os.getenv("DARWIN_API_KEY", "")
SOURCE = "agent"
# Short — we never want a hung Darwin to delay Clippy. The hook is opportunistic.
HTTP_TIMEOUT_SEC = 5.0

_SPLIT_PATTERN = re.compile(r"^(?=## )", re.MULTILINE)
_TRAILING_SEPARATOR = re.compile(r"\n+---\s*$")


def _chunk(content: str) -> list[dict]:
    """Split content on `## ` level-2 headings; drop the preamble; dedup by hash."""
    sections = _SPLIT_PATTERN.split(content)
    chunks: list[dict] = []
    seen: set[str] = set()
    for section in sections[1:]:  # drop preamble before first `## `
        body = _TRAILING_SEPARATOR.sub("", section.rstrip()).rstrip()
        if not body:
            continue
        h = hashlib.md5(body.encode("utf-8")).hexdigest()
        first_line = body.split("\n", 1)[0].lstrip("# ").strip()
        chunks.append({
            "content": body,
            "first_line": first_line,
            "hash": h,
            "is_duplicate": h in seen,
        })
        seen.add(h)
    return chunks


def post_findings(walnut_name: str, result: str) -> None:
    """Post a Clippy job's result to Darwin, chunked on `## ` headings.

    walnut_name: the walnut this result belongs to ('ai-tech', 'finance-geo',
        'cre-market', 'deep-dives', 'weekly-summary'). Used in source_ref and
        metadata.
    result: the raw text returned from agent.X_research(...) — what would
        also be prepended to the walnut and sent to Telegram.

    Fire-and-forget. Returns nothing. Exceptions are caught and logged.
    """
    if not DARWIN_INGEST_URL or not DARWIN_API_KEY:
        log.info("darwin_hook disabled (DARWIN_INGEST_URL or DARWIN_API_KEY unset)")
        return
    if not result or not result.strip():
        return

    chunks = _chunk(result)

    # Defensive fallback — if no `## ` headings exist (e.g. weekly_summary
    # may be a single prose block), post the whole result as one ingestion.
    # encode.py will truncate to 4 KB but we don't drop the content entirely.
    if not chunks:
        log.info("darwin_hook: no `## ` headings in %s; posting as single chunk", walnut_name)
        body = result.strip()
        chunks = [{
            "content": body,
            "first_line": body.split("\n", 1)[0][:200],
            "hash": hashlib.md5(body.encode("utf-8")).hexdigest(),
            "is_duplicate": False,
        }]

    unique = [c for c in chunks if not c["is_duplicate"]]
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    posted = errored = 0

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SEC) as client:
            for i, c in enumerate(unique, 1):
                source_ref = f"clippy:{walnut_name}:{timestamp}#{i}"
                try:
                    r = client.post(
                        DARWIN_INGEST_URL,
                        json={
                            "source": SOURCE,
                            "source_ref": source_ref,
                            "content": c["content"],
                            "metadata": {
                                "walnut": walnut_name,
                                "finding_index": i,
                                "finding_title": c["first_line"][:200],
                                "clippy_timestamp": timestamp,
                            },
                        },
                        headers={"X-API-Key": DARWIN_API_KEY},
                    )
                    if r.status_code == 200:
                        posted += 1
                    else:
                        errored += 1
                        log.warning(
                            "darwin_hook: POST %s -> %s: %s",
                            source_ref, r.status_code, r.text[:200],
                        )
                except Exception as exc:
                    errored += 1
                    log.warning("darwin_hook: POST %s error: %s", source_ref, exc)
    except Exception as exc:
        log.warning("darwin_hook: client error in %s post: %s", walnut_name, exc)
        return

    log.info(
        "darwin_hook: %s chunks=%d posted=%d errored=%d",
        walnut_name, len(unique), posted, errored,
    )
