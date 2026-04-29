"""Telegram bot — sends briefings and handles interactive questions."""

import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import agent
import memory

log = logging.getLogger("clippy.telegram")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Max Telegram message length
MAX_MSG_LEN = 4096


def send_message(text: str):
    """Send a message to the configured Telegram chat (sync, for scheduler use)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured, printing to console instead")
        print(text)
        return

    import asyncio
    from telegram import Bot

    async def _send():
        bot = Bot(token=TELEGRAM_TOKEN)
        # Split long messages
        for i in range(0, len(text), MAX_MSG_LEN):
            chunk = text[i : i + MAX_MSG_LEN]
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=chunk)

    # Handle case where event loop is already running
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        asyncio.run(_send())


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "📎 Clippy online. I run scheduled research jobs and send briefings.\n\n"
        "Commands:\n"
        "/ask <question> — Ask me anything\n"
        "/status — Show scheduled jobs\n"
        "/run <job> — Manually trigger a job (ai, cre, deep, weekly)\n"
        "/walnut <name> — Read a walnut file (ai-tech, cre-market, deep-dives)"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent research log entries."""
    logs = memory.get_recent_logs(days=3)
    if not logs:
        await update.message.reply_text("📎 No research logged in the last 3 days.")
        return

    lines = ["📎 Clippy | Recent Activity\n"]
    for ts, job, summary in logs[:10]:
        short = summary[:100] + "..." if len(summary) > 100 else summary
        lines.append(f"• {ts[:16]} | {job}\n  {short}")

    await update.message.reply_text("\n".join(lines))


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a research job."""
    if not context.args:
        await update.message.reply_text("Usage: /run <ai|cre|deep|weekly>")
        return

    job = context.args[0].lower()
    await update.message.reply_text(f"📎 Running {job} job...")

    import scheduler
    job_map = {
        "ai": scheduler.run_ai_tech,
        "cre": scheduler.run_cre_market,
        "deep": scheduler.run_deep_dive,
        "weekly": scheduler.run_weekly_summary,
    }

    func = job_map.get(job)
    if func:
        func()
    else:
        await update.message.reply_text(f"Unknown job: {job}. Use: ai, cre, deep, weekly")


async def cmd_walnut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read a walnut file."""
    if not context.args:
        await update.message.reply_text("Usage: /walnut <ai-tech|cre-market|deep-dives>")
        return

    name = context.args[0].lower()
    content = memory.read_walnut(name)
    if not content:
        await update.message.reply_text(f"📎 Walnut '{name}' not found or empty.")
        return

    # Send last 3000 chars to stay within Telegram limits
    snippet = content[-3000:] if len(content) > 3000 else content
    await update.message.reply_text(f"📎 Walnut: {name}\n\n{snippet}")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask Clippy a question using Claude."""
    if not context.args:
        await update.message.reply_text("Usage: /ask <your question>")
        return

    question = " ".join(context.args)
    await update.message.reply_text("📎 Researching...")

    result = agent.research("Ad-hoc Question", question)
    for i in range(0, len(result), MAX_MSG_LEN):
        await update.message.reply_text(result[i : i + MAX_MSG_LEN])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages as questions."""
    question = update.message.text
    await update.message.reply_text("📎 Researching...")

    result = agent.research("Ad-hoc Question", question)
    for i in range(0, len(result), MAX_MSG_LEN):
        await update.message.reply_text(result[i : i + MAX_MSG_LEN])


def start_bot():
    """Start the Telegram bot (blocking)."""
    if not TELEGRAM_TOKEN:
        log.warning("TELEGRAM_TOKEN not set, bot not started")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("walnut", cmd_walnut))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Telegram bot starting")
    app.run_polling()
