"""
WhatsApp sender for the T&P Bot using Green-API gateway.

Sends notices to a configured WhatsApp Group or Chat via Green-API:
    - Bold title (*date: title*)
    - Clean body text
    - URL & Attachment links
"""

import logging
import re
import time

import requests

from config import (
    GREENAPI_INSTANCE_ID,
    GREENAPI_API_TOKEN,
    GREENAPI_HOST,
    WHATSAPP_CHAT_ID,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Max message length for WhatsApp text message
MAX_MESSAGE_LENGTH = 4000
SEND_DELAY = 2.5


def _clean_body(text: str) -> str:
    """Remove markdown artifacts and excessive whitespace from body text."""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"^\*\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"Download:\s*Notice Attachment\s*", "", text)
    return text.strip()


def _format_message(notice) -> str:
    """
    Format a notice into WhatsApp style:
        *date: title*

        body text

        URL:
        https://...

        Attachment:
        https://...
    """
    title_line = f"*{notice.date}: {notice.title}*"

    # Footer construction
    footer_lines = [f"\nURL:\n{notice.source_url}"]
    if notice.attachment_url:
        footer_lines.append(f"\n\nAttachment:\n{notice.attachment_url}")
    footer = "".join(footer_lines)

    overhead = len(title_line) + len(footer) + 4
    max_body = MAX_MESSAGE_LENGTH - overhead

    body = _clean_body(notice.body) if notice.body else ""
    if body:
        trim_note = "\n\n_[...Text limit exceeded. Click the URL link below to view the full notice.]_"
        trim_note_len = len(trim_note)
        if len(body) > max_body:
            while len(body) > max_body - trim_note_len:
                body = body[:len(body) - 50].rsplit("\n", 1)[0]
            body += trim_note

    parts = [title_line]
    if body:
        parts.append("")
        parts.append(body)
    parts.append(footer)

    return "\n".join(parts)


def send_notice(notice) -> bool:
    """
    Send a single notice to the configured WhatsApp chat/group via Green-API.
    Returns True if sent successfully, False otherwise.
    """
    if not GREENAPI_INSTANCE_ID or not GREENAPI_API_TOKEN or not WHATSAPP_CHAT_ID:
        logger.warning("WhatsApp credentials or WHATSAPP_CHAT_ID not configured — skipping")
        return False

    message_text = _format_message(notice)
    url = f"{GREENAPI_HOST.rstrip('/')}/waInstance{GREENAPI_INSTANCE_ID}/sendMessage/{GREENAPI_API_TOKEN}"

    payload = {
        "chatId": WHATSAPP_CHAT_ID,
        "message": message_text,
    }

    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        result = resp.json()
        if resp.status_code == 200 and result.get("idMessage"):
            logger.info("WhatsApp sendMessage success (ID: %s | msg_id: %s)", notice.id, result.get("idMessage"))
            return True
        else:
            logger.error("WhatsApp API error: %s", result)
            return False
    except requests.RequestException as e:
        logger.error("WhatsApp request failed: %s", e)
        return False


def send_notices(notices: list) -> list:
    """
    Send multiple notices to WhatsApp, oldest first (reversed from page order).
    Returns the list of notice IDs that were successfully sent.
    """
    ordered = list(reversed(notices))
    sent_ids = []

    for i, notice in enumerate(ordered):
        logger.info(
            "Sending WhatsApp notice %d/%d — ID: %s — %s",
            i + 1, len(ordered), notice.id, notice.title,
        )
        success = send_notice(notice)
        if success:
            sent_ids.append(notice.id)
        else:
            logger.error(
                "Failed to send WhatsApp notice %s — skipping", notice.id
            )

        if i < len(ordered) - 1:
            time.sleep(SEND_DELAY)

    return sent_ids
