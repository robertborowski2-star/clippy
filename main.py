"""Clippy — AI research agent. Entry point."""

import argparse
import logging
import signal
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import memory
import scheduler
import telegram_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(memory.CLIPPY_DIR / "clippy.log"),
    ],
)
log = logging.getLogger("clippy")


def main():
    parser = argparse.ArgumentParser(description="Clippy — AI Research Agent")
    parser.add_argument("--no-bot", action="store_true", help="Run scheduler only, no Telegram bot")
    parser.add_argument("--run", choices=["ai", "finance", "cre", "deep", "weekly"], help="Run a single job and exit")
    args = parser.parse_args()

    # Initialize memory system
    memory.init()
    log.info("Clippy initialized")

    # Single job mode
    if args.run:
        log.info(f"Running single job: {args.run}")
        job_map = {
            "ai": scheduler.run_ai_fringe,
            "cre": scheduler.run_cre_weekly,
            "finance": scheduler.run_finance_geo,
            "deep": scheduler.run_deep_dive,
            "weekly": scheduler.run_weekly_summary,
        }
        job_map[args.run]()
        return

    # Start scheduler
    sched = scheduler.start()

    # Graceful shutdown
    def shutdown(signum, frame):
        log.info("Shutting down...")
        sched.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if args.no_bot:
        log.info("Running in scheduler-only mode")
        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            sched.shutdown()
    else:
        log.info("Starting Telegram bot")
        telegram_bot.start_bot()


if __name__ == "__main__":
    main()
