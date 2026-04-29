"""Memory system — SQLite for metadata + walnut markdown files for accumulated findings."""

import sqlite3
from datetime import datetime
from pathlib import Path


CLIPPY_DIR = Path.home() / "clippy"
WALNUTS_DIR = CLIPPY_DIR / "walnuts"
DB_PATH = CLIPPY_DIR / "clippy.db"

# Clippy's own research walnuts (accumulated findings)
WALNUT_FILES = {
    "ai-tech":         WALNUTS_DIR / "ai-tech.md",
    "cre-market":      WALNUTS_DIR / "cre-market.md",
    "finance-geo":     WALNUTS_DIR / "finance-geo.md",
    "deep-dives":      WALNUTS_DIR / "deep-dives.md",
    "physics":         WALNUTS_DIR / "physics.md",
    "mathematics":     WALNUTS_DIR / "mathematics.md",
    "biology":         WALNUTS_DIR / "biology.md",
    "chemistry":       WALNUTS_DIR / "chemistry.md",
    "earth-materials": WALNUTS_DIR / "earth-materials.md",
}

# Project walnuts — Robert's active projects (read + append only)
PROJECT_WALNUTS_DIR = Path.home() / "walnuts"
PROJECT_WALNUT_FILES = {
    "agent-network": PROJECT_WALNUTS_DIR / "agent-network",
    "klaus":         PROJECT_WALNUTS_DIR / "klaus",
    "cre-llm":       PROJECT_WALNUTS_DIR / "cre-llm",
}


def init():
    """Initialize directories, walnut files, and SQLite database."""
    CLIPPY_DIR.mkdir(parents=True, exist_ok=True)
    WALNUTS_DIR.mkdir(parents=True, exist_ok=True)

    walnut_headers = {
        "finance-geo": "# Finance & Geopolitics — Clippy Walnut\n\n",
    }
    for name, path in WALNUT_FILES.items():
        if not path.exists():
            header = walnut_headers.get(name, f"# {name.replace('-', ' ').title()} — Clippy Walnut\n\n")
            path.write_text(header)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            job_name TEXT NOT NULL,
            summary TEXT,
            walnut TEXT,
            tokens_used INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def read_walnut(name: str) -> str:
    """Read a Clippy research walnut file's contents."""
    path = WALNUT_FILES.get(name)
    if path and path.exists():
        return path.read_text()
    return ""


def get_latest_walnut_entry(name: str) -> str:
    """Extract just the most recent timestamped entry from a walnut.

    Walnuts grow by prepending: each `write_walnut(name, content)` wraps
    its content as `\\n---\\n[timestamp]\\ncontent\\n---\\n` and inserts it
    right after the `# Title` header line. So the latest entry sits between
    the first and second `---` delimiters from the top of the file.

    Returns the timestamped entry body (timestamp line + content), stripped
    of `---` delimiters and surrounding whitespace. Returns "" if the walnut
    is empty or has no entries (e.g., freshly created file with header only).
    """
    text = read_walnut(name)
    if not text:
        return ""
    parts = text.split("\n---\n")
    # parts[0] is the header ("# Title — Clippy Walnut\n\n").
    # parts[1] is the latest entry body ("[timestamp]\ncontent...").
    # parts[2] is empty (between the closing --- of latest and opening --- of next).
    # parts[3+] are older entries.
    for part in parts[1:]:
        body = part.strip()
        if body and body.startswith("["):
            return body
    return ""


def read_project_walnut(project: str, file: str = "now") -> str:
    """
    Read a specific file from a project walnut.
    project: 'agent-network', 'klaus', or 'cre-llm'
    file: 'key', 'now', 'tasks', 'insights', or 'log'
    """
    project_dir = PROJECT_WALNUT_FILES.get(project)
    if not project_dir:
        return ""
    path = project_dir / f"{file}.md"
    if path.exists():
        return path.read_text()
    return ""


def read_project_context(project: str) -> str:
    """
    Read the most relevant context files for a project walnut:
    now.md + tasks.md + last 500 chars of log.md
    Returns a formatted string ready to inject into a prompt.
    """
    project_dir = PROJECT_WALNUT_FILES.get(project)
    if not project_dir:
        return ""

    parts = []
    for fname in ["now", "tasks"]:
        path = project_dir / f"{fname}.md"
        if path.exists():
            parts.append(path.read_text().strip())

    # Only last 500 chars of log to keep context tight
    log_path = project_dir / "log.md"
    if log_path.exists():
        log_content = log_path.read_text().strip()
        parts.append("## Recent Log (last entries)\n" + log_content[-500:])

    return "\n\n".join(parts)


def append_project_log(project: str, entry: str):
    """
    Prepend a new timestamped entry to a project walnut's log.md.
    Used by Clippy to write findings back to project walnuts.
    """
    project_dir = PROJECT_WALNUT_FILES.get(project)
    if not project_dir:
        return

    log_path = project_dir / "log.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_entry = f"\n---\n[{timestamp}] Clippy Research\n{entry}\n---\n"

    if log_path.exists():
        existing = log_path.read_text()
        # Prepend after header line
        lines = existing.split("\n")
        header_end = next((i + 1 for i, l in enumerate(lines) if l.startswith("# ")), 1)
        before = "\n".join(lines[:header_end])
        after = "\n".join(lines[header_end:])
        log_path.write_text(before + new_entry + after)
    else:
        log_path.write_text(f"# {project} — log.md\n" + new_entry)


def write_walnut(name: str, entry: str):
    """Prepend an entry to a Clippy research walnut file with timestamp."""
    path = WALNUT_FILES.get(name)
    if not path:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    formatted = f"\n---\n[{timestamp}]\n{entry}\n---\n"

    existing = path.read_text() if path.exists() else ""
    lines = existing.split("\n")
    header_end = next((i + 1 for i, l in enumerate(lines) if l.startswith("# ")), 1)
    before = "\n".join(lines[:header_end])
    after = "\n".join(lines[header_end:])
    path.write_text(before + formatted + after)


def log_research(job_name: str, summary: str, walnut: str, tokens_used: int = 0):
    """Log a research job to SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO research_log (timestamp, job_name, summary, walnut, tokens_used) "
        "VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), job_name, summary[:500], walnut, tokens_used),
    )
    conn.commit()
    conn.close()


def get_recent_logs(days: int = 7) -> list:
    """Get research logs from the last N days."""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute(
        "SELECT timestamp, job_name, summary FROM research_log "
        "WHERE timestamp >= datetime('now', ?) ORDER BY timestamp DESC",
        (f"-{days} days",),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows