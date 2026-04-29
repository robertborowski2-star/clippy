"""Scheduler — 5 research jobs on cron using APScheduler."""

import logging
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

        telegram_bot.send_message(result)
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


def run_weekly_summary():
    """Monday 08:00 — Weekly intel summary across all topics and projects."""
    log.info("Starting Weekly Summary job")
    try:
        ai_context = memory.read_walnut("ai-tech")
        finance_context = memory.read_walnut("finance-geo")
        cre_context = memory.read_walnut("cre-market")
        project_contexts = {
            "agent-network": memory.read_project_context("agent-network"),
            "klaus": memory.read_project_context("klaus"),
            "cre-llm": memory.read_project_context("cre-llm"),
        }

        result = agent.weekly_summary(
            ai_context=ai_context,
            finance_context=finance_context,
            cre_context=cre_context,
            project_contexts=project_contexts,
        )

        memory.log_research("Weekly Summary", result, "ai-tech")
        telegram_bot.send_message(result)
        darwin_hook.post_findings("weekly-summary", result)
        log.info("Weekly Summary job complete")
    except Exception as e:
        log.error(f"Weekly Summary failed: {e}")
        telegram_bot.send_message(f"📎 Clippy | ERROR | Weekly Summary failed: {e}")


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

    # Weekly Summary — Monday 08:00
    sched.add_job(
        run_weekly_summary,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_summary",
        name="Weekly Intel Summary",
        misfire_grace_time=3600,
    )

    sched.start()
    log.info("Scheduler started with 5 jobs")
    return sched
