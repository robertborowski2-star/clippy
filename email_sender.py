"""Email delivery for the Weekly CRE Brief.

Sends a multipart (HTML + plain text) email via Gmail SMTP. Recipients are
read from the CRE_EMAIL_RECIPIENTS env var (comma-separated). All recipients
are BCC'd; the visible To: is the sender themselves, so colleagues don't see
each other's addresses.

Requires SMTP_USER (the Gmail address) and SMTP_PASS (a Google App Password,
NOT the account password). Generate at https://myaccount.google.com/apppasswords
— requires 2FA on the Google account.

If SMTP_USER, SMTP_PASS, or CRE_EMAIL_RECIPIENTS is unset/empty, send_cre_brief
logs a warning and returns False without raising. The caller (scheduler) then
continues with Telegram/walnut/Darwin as normal — email is opportunistic in the
same way the Darwin hook is.
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown

log = logging.getLogger("clippy.email_sender")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SEC = 30

DISPLAY_NAME = "Robert Borowski"

UNSUBSCRIBE_TEXT = (
    "\n\n---\n\n"
    "Reply with UNSUBSCRIBE to stop receiving these briefs."
)
UNSUBSCRIBE_HTML = (
    '<hr style="margin-top:32px;border:0;border-top:1px solid #ddd;">'
    '<p style="color:#888;font-size:12px;font-style:italic;margin-top:12px;">'
    'Reply with UNSUBSCRIBE to stop receiving these briefs.'
    '</p>'
)

# Inline CSS for the HTML email — kept simple because Outlook's renderer
# is hostile to anything fancy. Targets headings and links only.
HTML_WRAPPER = (
    '<!DOCTYPE html>'
    '<html><head><meta charset="utf-8"></head>'
    '<body style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Helvetica, Arial, sans-serif;'
    ' font-size: 14px; line-height: 1.5; color: #222; max-width: 720px; margin: 0 auto; padding: 16px;">'
    '{body}'
    '{footer}'
    '</body></html>'
)


def get_recipients() -> list:
    """Parse CRE_EMAIL_RECIPIENTS into a deduped list of addresses."""
    raw = os.getenv("CRE_EMAIL_RECIPIENTS", "")
    seen = set()
    out = []
    for addr in raw.split(","):
        a = addr.strip()
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _build_subject() -> str:
    today = datetime.now()
    # Cross-platform day-of-month without leading zero (works on macOS + Linux).
    day = str(today.day)
    return f"Weekly Canadian CRE Brief — {today.strftime('%B')} {day}, {today.year}"


def _build_message(markdown_body: str, sender_addr: str, recipients: list) -> MIMEMultipart:
    text_body = markdown_body + UNSUBSCRIBE_TEXT
    html_inner = markdown.markdown(markdown_body, extensions=["extra", "sane_lists"])
    html_body = HTML_WRAPPER.format(body=html_inner, footer=UNSUBSCRIBE_HTML)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = _build_subject()
    msg["From"] = f"{DISPLAY_NAME} <{sender_addr}>"
    msg["To"] = sender_addr  # visible To: is the sender themselves
    msg["Bcc"] = ", ".join(recipients)
    msg["Reply-To"] = sender_addr

    msg.attach(MIMEText(text_body, "plain", _charset="utf-8"))
    msg.attach(MIMEText(html_body, "html", _charset="utf-8"))
    return msg


def send_cre_brief(markdown_body: str) -> bool:
    """Send the CRE brief to all configured recipients.

    Returns True on successful send, False on skip (missing config) or error.
    Never raises — caller's other delivery paths must continue regardless.
    """
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    if not smtp_user or not smtp_pass:
        log.warning("email_sender: SMTP_USER or SMTP_PASS not set; skipping email send")
        return False

    recipients = get_recipients()
    if not recipients:
        log.warning("email_sender: CRE_EMAIL_RECIPIENTS is empty; skipping email send")
        return False

    if not markdown_body or not markdown_body.strip():
        log.warning("email_sender: empty body; skipping email send")
        return False

    try:
        msg = _build_message(markdown_body, smtp_user, recipients)
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SEC) as server:
            server.login(smtp_user, smtp_pass)
            # send_message strips the Bcc header before transmitting and
            # uses To+Cc+Bcc for the SMTP envelope automatically.
            server.send_message(msg)
        log.info(
            "email_sender: sent CRE brief to %d recipients (BCC)",
            len(recipients),
        )
        return True
    except Exception as e:
        log.error("email_sender: failed to send CRE brief: %s", e)
        return False
