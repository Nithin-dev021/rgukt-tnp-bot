"""
Telegram sender for the T&P Bot.

All notices are sent as plain text messages (sendMessage) with HTML formatting.
If a notice has an attachment, its download URL goes at the end — Telegram's
link preview automatically shows a downloadable file card for it.
"""

import logging
import re
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

MAX_MESSAGE_LENGTH = 4096
SEND_DELAY = 2.0


def _clean_body(text: str) -> str:
    """Remove markdown artifacts and excessive whitespace from body text."""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"^\*\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"Download:\s*Notice Attachment\s*", "", text)
    return text.strip()


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _format_message(notice) -> str:
    """
    Format a notice as:
        <b>date: title</b>

        body text (trimmed if needed)

        URL:
        https://...  (attachment URL if available, otherwise source URL)
    """
    title_line = _escape_html(f"{notice.date}: {notice.title}")
    header = f"<b>{title_line}</b>"

    # Footer construction
    footer_lines = [f"\nURL:\n{notice.source_url}"]
    if notice.attachment_url:
        footer_lines.append(f"\n\nAttachment:\n{notice.attachment_url}")
    footer = "".join(footer_lines)

    # Calculate space available for body
    overhead = len(header) + len(footer) + 4  # 4 for blank line separators
    max_body = MAX_MESSAGE_LENGTH - overhead

    body = _clean_body(notice.body) if notice.body else ""
    if body:
        trim_note = "\n\n<i>[...Text limit exceeded. Click the URL link below to view the full notice.]</i>"
        trim_note_len = len(trim_note)
        if len(_escape_html(body)) > max_body:
            while len(_escape_html(body)) > max_body - trim_note_len:
                body = body[:len(body) - 50].rsplit("\n", 1)[0]
            body = _escape_html(body) + trim_note
        else:
            body = _escape_html(body)

    parts = [header]
    if body:
        parts.append("")
        parts.append(body)
    parts.append(footer)

    return "\n".join(parts)


def send_notice(notice) -> bool:
    """Send a single notice as a text message. Returns True on success."""
    text = _format_message(notice)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        # Link preview is ON so Telegram shows the file card for attachment URLs
    }
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            data=payload,
            timeout=REQUEST_TIMEOUT,
        )
        result = resp.json()
        if result.get("ok"):
            logger.info("sendMessage success (ID: %s)", notice.id)
            return True
        else:
            logger.error("sendMessage API error: %s", result.get("description", result))
            return False
    except requests.RequestException as e:
        logger.error("sendMessage request failed: %s", e)
        return False


def send_notices(notices: list) -> list:
    """
    Send multiple notices, oldest first (reversed from page order).
    Returns the list of notice IDs that were successfully sent.
    """
    ordered = list(reversed(notices))
    sent_ids = []

    for i, notice in enumerate(ordered):
        logger.info(
            "Sending notice %d/%d — ID: %s — %s",
            i + 1, len(ordered), notice.id, notice.title,
        )
        success = send_notice(notice)
        if success:
            sent_ids.append(notice.id)
        else:
            logger.error(
                "Failed to send notice %s — will retry on next poll", notice.id
            )

        if i < len(ordered) - 1:
            time.sleep(SEND_DELAY)

    return sent_ids
