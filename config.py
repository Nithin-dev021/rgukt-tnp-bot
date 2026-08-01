"""
Configuration for the RGUKT T&P Telegram Bot.

All settings are read from environment variables or a local .env file.
"""

import os
from pathlib import Path

# Automatically load local .env file if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ──────────────────────────────────────────────
# Telegram settings
# ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

# ──────────────────────────────────────────────
# Polling settings
# ──────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))  # 5 min

# ──────────────────────────────────────────────
# WhatsApp settings (Green-API)
# ──────────────────────────────────────────────
ENABLE_WHATSAPP = os.environ.get(
    "ENABLE_WHATSAPP", "false"
).lower() in ("true", "1", "yes")

GREENAPI_INSTANCE_ID = os.environ.get("GREENAPI_INSTANCE_ID", "YOUR_GREENAPI_INSTANCE_ID_HERE")
GREENAPI_API_TOKEN = os.environ.get(
    "GREENAPI_API_TOKEN", "YOUR_GREENAPI_API_TOKEN_HERE"
)
GREENAPI_HOST = os.environ.get("GREENAPI_HOST", "https://7107.api.greenapi.com")
WHATSAPP_CHAT_ID = os.environ.get("WHATSAPP_CHAT_ID", "YOUR_WHATSAPP_CHAT_ID_HERE")

# ──────────────────────────────────────────────
# First-run behavior
# ──────────────────────────────────────────────
SEND_ALL_ON_FIRST_RUN = os.environ.get(
    "SEND_ALL_ON_FIRST_RUN", "false"
).lower() in ("true", "1", "yes")

# ──────────────────────────────────────────────
# Source URL
# ──────────────────────────────────────────────
TNP_BASE_URL = "https://hub.rgukt.ac.in"
TNP_INDEX_URL = f"{TNP_BASE_URL}/hub/tnp/index"

# ──────────────────────────────────────────────
# State file path (JSON, for dedup)
# ──────────────────────────────────────────────
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "sent_notices.json"
))

# ──────────────────────────────────────────────
# HTTP request settings
# ──────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30  # seconds
