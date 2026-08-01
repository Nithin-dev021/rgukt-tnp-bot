"""
State management for the T&P Telegram Bot.

Tracks sent notice IDs in a local JSON file for deduplication.
"""

import json
import logging
import os
from typing import List, Set

from config import STATE_FILE

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
    """Persist the set of sent notice IDs to the state file."""
    try:
        data = {"sent_ids": sorted(sent_ids)}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug("Saved %d sent notice ID(s) to state file", len(sent_ids))
    except OSError as e:
        logger.error("Failed to write state file: %s", e)


def is_first_run() -> bool:
    """Check whether this is the first run (no state file exists)."""
    return not os.path.exists(STATE_FILE)


def filter_new_notices(notices: list, sent_ids: Set[str]) -> list:
    """
    Return only notices whose IDs are not in sent_ids.
    Preserves original order (newest first as on the page).
    """
    new_notices = [n for n in notices if n.id not in sent_ids]
    logger.info(
        "Filtered: %d total, %d already sent, %d new",
        len(notices), len(notices) - len(new_notices), len(new_notices),
    )
    return new_notices
