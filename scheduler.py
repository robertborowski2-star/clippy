"""Scheduler — 5 research jobs on cron using APScheduler."""

import logging
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import agent
import darwin_hook
import memory
import telegram_bot

log = logging.getLogger("clippy.scheduler")


def run_ai_fringe():
    """07:45 daily — AI & Fringe Science research, informed by agent-network walnut."""
    log.info("Starting AI & Fringe Science research job")
    try:
        research_context = memory.read_walnut("ai-tech")
        project_context = memory.read_project_context("agent-network")

        result = agent.ai_fringe_research(
            walnut_context=research_context,
            project_context=project_context,
        )

        memory.write_walnut("ai-tech", result)
        memory.log_research("AI & Fringe Science", result, "ai-tech")
        memory.append_project_log("agent-network", result)

        darwin_hook.post_findings("ai-tech", result)
        log.info("AI & Fringe Science research job complete")
    except Exception as e:
        log.error(f"AI & Fringe Science research failed: {e}")
        telegram_bot.send_message(f"📎 Clippy | ERROR | AI & Fringe Science research failed: {e}")


def run_finance_geo():
    """16:00 daily — Finance & Geopolitics research, pure research (no project context)."""
    log.info("Starting Finance & Geopolitics research job")
    try:
        research_context = memory.read_walnut("finance-geo")

        result = agent.finance_geo_research(
            walnut_context=research_context,
        )

        memory.write_walnut("finance-geo", result)
        memory.log_research("Finance & Geopolitics", result, "finance-geo")

        telegram_bot.send_message(result)
        darwin_hook.post_findings("finance-geo", result)
        log.info("Finance & Geopolitics research job complete")
    except Exception as e:
        log.error(f"Finance & Geopolitics research failed: {e}")
        telegram_bot.send_message(f"📎 Clippy | ERROR | Finance & Geopolitics research failed: {e}")


def run_cre_weekly():
    """Monday 10:00 — CRE Weekly research, informed by Klaus + CRE-LLM walnuts."""
    log.info("Starting CRE Weekly research job")
    try:
        research_context = memory.read_walnut("cre-market")
        klaus_context = memory.read_project_context("klaus")
        cre_llm_context = memory.read_project_context("cre-llm")
        project_context = (
            "=== KLAUS PROJECT ===\n" + klaus_context +
            "\n\n=== CRE-LLM PROJECT ===\n" + cre_llm_context
        )

        result = agent.cre_market_research(
            walnut_context=research_context,
            project_context=project_context,
        )

        memory.write_walnut("cre-market", result)
        memory.log_research("CRE Weekly", result, "cre-market")
        memory.append_project_log("klaus", result)
        memory.append_project_log("cre-llm", result)

        telegram_bot.send_message(result)
        darwin_hook.post_findings("cre-market", result)
        log.info("CRE Weekly research job complete")
    except Exception as e:
        log.error(f"CRE Weekly research failed: {e}")
        telegram_bot.send_message(f"📎 Clippy | ERROR | CRE Weekly research failed: {e}")


def run_deep_dive():
    """21:00 daily — Deep dive on best finding across all topics and projects."""
    log.info("Starting Deep Dive job")
    try:
        ai_context = memory.read_walnut("ai-tech")
        finance_context = memory.read_walnut("finance-geo")
        cre_context = memory.read_walnut("cre-market")
        project_contexts = {
            "agent-network": memory.read_project_context("agent-network"),
            "klaus": memory.read_project_context("klaus"),
            "cre-llm": memory.read_project_context("cre-llm"),
        }

        result = agent.deep_dive(
            ai_context=ai_context,
            finance_context=finance_context,
            cre_context=cre_context,
            project_contexts=project_contexts,
        )

        memory.write_walnut("deep-dives", result)
        memory.log_research("Deep Dive", result, "deep-dives")
        telegram_bot.send_message(result)
        darwin_hook.post_findings("deep-dives", result)
        log.info("Deep Dive job complete")
    except Exception as e:
        log.error(f"Deep Dive failed: {e}")
        telegram_bot.send_message(f"📎 Clippy | ERROR | Deep Dive failed: {e}")


SCIENCE_SUBJECTS = ["physics", "mathematics", "biology", "chemistry", "earth-materials"]
_SECTION_PATTERN = re.compile(r"===SECTION:([A-Za-z\-]+)===\s*", re.MULTILINE)


def _split_science_sections(result: str) -> dict:
    """Split science_roundup output on `===SECTION:NAME===` sentinels.

    Returns {walnut_name: section_text}. Unknown sentinels are dropped.
    Preamble before the first sentinel is ignored.
    """
    parts = _SECTION_PATTERN.split(result)
    sections: dict = {}
    # parts = [preamble, NAME1, body1, NAME2, body2, ...]
    for i in range(1, len(parts), 2):
        name = parts[i].strip().lower()
        if name in SCIENCE_SUBJECTS and i + 1 < len(parts):
            sections[name] = parts[i + 1].strip()
    return sections


def run_science_roundup():
    """Saturday 01:00 — weekly science roundup across 5 subjects.

    Single LLM call produces sentinel-delimited sections. Each section is
    written to its own walnut and posted to Darwin separately. No Telegram.
    """
    log.info("Starting Science Roundup job")
    try:
        walnut_contexts = {
            subject: memory.read_walnut(subject) for subject in SCIENCE_SUBJECTS
        }

        result = agent.science_roundup_research(walnut_contexts=walnut_contexts)
        sections = _split_science_sections(result)

        if not sections:
            raise RuntimeError("Science Roundup produced no recognizable sections")

        for subject, body in sections.items():
            memory.write_walnut(subject, body)
            memory.log_research(f"Science Roundup ({subject})", body, subject)
            darwin_hook.post_findings(subject, body)

        missing = [s for s in SCIENCE_SUBJECTS if s not in sections]
        if missing:
            log.warning("Science Roundup missing sections: %s", missing)

        log.info("Science Roundup complete: wrote %d/%d subjects",
                 len(sections), len(SCIENCE_SUBJECTS))
    except Exception as e:
        log.error(f"Science Roundup failed: {e}")
        telegram_bot.send_message(f"📎 Clippy | ERROR | Science Roundup failed: {e}")


def start() -> BackgroundScheduler:
    """Start the scheduler with all 5 research jobs."""
    sched = BackgroundScheduler()

    # Daily AI & Fringe Science — 07:45
    sched.add_job(
        run_ai_fringe,
        CronTrigger(hour=7, minute=45),
        id="ai_fringe",
        name="AI & Fringe Science",
        misfire_grace_time=3600,
    )

    # Daily Finance & Geopolitics — 16:00
    sched.add_job(
        run_finance_geo,
        CronTrigger(hour=16, minute=0),
        id="finance_geo",
        name="Finance & Geopolitics",
        misfire_grace_time=3600,
    )

    # Weekly CRE — Monday 10:00
    sched.add_job(
        run_cre_weekly,
        CronTrigger(day_of_week="mon", hour=10, minute=0),
        id="cre_weekly",
        name="CRE Weekly",
        misfire_grace_time=3600,
    )

    # Daily Deep Dive — 21:00
    sched.add_job(
        run_deep_dive,
        CronTrigger(hour=21, minute=0),
        id="deep_dive",
        name="Deep Dive",
        misfire_grace_time=3600,
    )

    # Weekly Science Roundup — Saturday 01:00
    sched.add_job(
        run_science_roundup,
        CronTrigger(day_of_week="sat", hour=1, minute=0),
        id="science_roundup",
        name="Science Roundup",
        misfire_grace_time=3600,
    )

    sched.start()
    log.info("Scheduler started with 5 jobs")
    return sched
