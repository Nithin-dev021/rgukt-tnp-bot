"""
State management for the T&P Telegram Bot.

Tracks sent notice IDs in a local JSON file for deduplication.
"""

import json
import logging
import os
from typing import List, Set

from config import STATE_FILE, MAX_NOTICE_AGE_DAYS

logger = logging.getLogger(__name__)


def load_sent_ids() -> Set[str]:
    """Load the set of already-sent notice IDs from the state file."""
    if not os.path.exists(STATE_FILE):
        logger.info("State file does not exist yet — first run detected")
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        sent = set(data.get("sent_ids", []))
        logger.info("Loaded %d sent notice ID(s) from state file", len(sent))
        return sent
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read state file: %s — starting fresh", e)
        return set()


def save_sent_ids(sent_ids: Set[str]) -> None:
    """Persist the set of sent notice IDs to the state file using atomic writing to prevent corruption."""
    try:
        # Sort numerically so order is clean and predictable
        sorted_ids = sorted(sent_ids, key=lambda x: int(x) if x.isdigit() else x)
        if len(sorted_ids) > 1000:
            sorted_ids = sorted_ids[-1000:]

        data = {"sent_ids": sorted_ids}
        temp_file = f"{STATE_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, STATE_FILE)
        logger.debug("Saved %d sent notice ID(s) to state file", len(sorted_ids))
    except OSError as e:
        logger.error("Failed to write state file: %s", e)


def is_first_run() -> bool:
    """Check whether this is the first run (no state file exists)."""
    return not os.path.exists(STATE_FILE)


def filter_new_notices(
    notices: list, sent_ids: Set[str], max_age_days: int = MAX_NOTICE_AGE_DAYS
) -> list:
    """
    Return only notices whose IDs are not in sent_ids and are within max_age_days.
    Older unrecorded notices are automatically marked as seen to prevent historical spam.
    Preserves original order (newest first as on the page).
    """
    new_notices = []
    stale_marked = 0

    for n in notices:
        if n.id in sent_ids:
            continue

        # Check notice age (safeguard against historical notice bursts on server restarts)
        if hasattr(n, "is_recent") and not n.is_recent(max_age_days):
            logger.info(
                "Notice %s ('%s', %s) is older than %d day(s) — auto-marking as seen",
                n.id, n.title[:35], n.date, max_age_days,
            )
            sent_ids.add(n.id)
            stale_marked += 1
            continue

        new_notices.append(n)

    if stale_marked > 0:
        save_sent_ids(sent_ids)

    logger.info(
        "Filtered: %d total, %d already sent, %d stale auto-marked, %d genuinely new",
        len(notices), len(notices) - len(new_notices) - stale_marked, stale_marked, len(new_notices),
    )
    return new_notices
