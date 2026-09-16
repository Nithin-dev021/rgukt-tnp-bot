"""
RGUKT T&P Notice → Telegram Bot

Main orchestrator: fetch → parse → filter new → send → update state.

Usage:
    python main.py              # single run (good for cron)
    python main.py --loop       # continuous polling
    python main.py --debug      # single run + dump raw HTML for inspection
"""

import argparse
import logging
import sys
import time

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import (
    POLL_INTERVAL_SECONDS,
    SEND_ALL_ON_FIRST_RUN,
    TNP_INDEX_URL,
    ENABLE_WHATSAPP,
    MAX_BURST_ON_STARTUP,
    ALERT_ON_WHATSAPP_DISCONNECT,
)
from scraper import fetch_page, parse_notices, dump_html
from state import load_sent_ids, save_sent_ids, is_first_run, filter_new_notices
from telegram_sender import send_notices

# Global resilience flags
_IS_STARTUP_CYCLE = True
_CONSECUTIVE_PARSE_FAILURES = 0
_WHATSAPP_ALERT_SENT = False


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler to satisfy cloud hosting health checks (Render, Railway, etc.)."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - RGUKT T&P Bot is running!")

    def log_message(self, format, *args):
        pass  # suppress access logs to keep console clean


def start_health_check_server() -> None:
    """Start a lightweight HTTP server on the PORT env variable in a background daemon thread."""
    port_str = os.environ.get("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logging.getLogger("tnp_bot").info(
            "Health check HTTP server listening on port %d", port
        )
        server.serve_forever()
    except Exception as e:
        logging.getLogger("tnp_bot").warning(
            "Could not start health check server: %s", e
        )


def start_self_pinger() -> None:
    """Periodically ping the public service URL to prevent Render Free tier from sleeping (resets 15-min idle timer)."""
    def pinger():
        time.sleep(30)  # Wait for initial startup
        # Target the public URL so requests route through Render's external ingress/load balancer
        target_url = os.environ.get("RENDER_EXTERNAL_URL") or "https://rgukt-tnp-bot.onrender.com"

        log = logging.getLogger("tnp_bot")
        log.info("Self-pinger initialized — keeping Render awake at %s", target_url)

        import requests
        while True:
            try:
                time.sleep(240)  # Ping every 4 minutes (well within Render's 15-minute idle window)
                resp = requests.get(target_url, timeout=15)
                log.info("Self-ping success to %s (status: %d)", target_url, resp.status_code)
            except Exception as e:
                log.warning("Self-ping warning to %s: %s (will retry in 4 min)", target_url, e)

    threading.Thread(target=pinger, daemon=True).start()

# ──────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tnp_bot")


def run_once(debug: bool = False) -> None:
    """Execute one poll cycle: fetch → parse → filter → send → save with multi-layer safeguards."""
    global _IS_STARTUP_CYCLE, _CONSECUTIVE_PARSE_FAILURES, _WHATSAPP_ALERT_SENT

    # WhatsApp connection health check on startup — logs to console only
    if ENABLE_WHATSAPP and _IS_STARTUP_CYCLE:
        try:
            from whatsapp_sender import check_whatsapp_status
            status = check_whatsapp_status()
            state = status.get("stateInstance")
            if state and state != "authorized":
                logger.warning(
                    "WhatsApp Green-API instance is not authorized (state: '%s'). "
                    "WhatsApp notices will fail until re-linked in console.green-api.com. "
                    "Telegram notices are unaffected.",
                    state,
                )
            else:
                logger.info("WhatsApp Green-API connection verified (state: '%s')", state)
        except Exception as e:
            logger.warning("Could not verify WhatsApp instance status: %s", e)

    # 1. Fetch the page
    try:
        html = fetch_page(TNP_INDEX_URL)
    except Exception:
        logger.exception("Failed to fetch the T&P page — aborting this cycle")
        return

    # Debug: dump raw HTML to file
    if debug:
        dump_html(html)

    # 2. Parse notices
    notices = parse_notices(html)
    if not notices:
        _CONSECUTIVE_PARSE_FAILURES += 1
        logger.warning(
            "0 notices parsed (consecutive failure count: %d). "
            "The RGUKT T&P website layout or URL may have changed.",
            _CONSECUTIVE_PARSE_FAILURES,
        )
        return
    else:
        _CONSECUTIVE_PARSE_FAILURES = 0

    logger.info("Parsed %d notice(s) from the page", len(notices))

    # 3. Load state
    first_run = is_first_run()
    sent_ids = load_sent_ids()

    # 4. Filter new notices (automatically marks notices older than MAX_NOTICE_AGE_DAYS as seen)
    new_notices = filter_new_notices(notices, sent_ids)

    if not new_notices:
        logger.info("No new notices to send")
        _IS_STARTUP_CYCLE = False
        return

    # 5. Cold Startup Safeguard:
    # If this is the container's very first cycle since booting up and multiple unrecorded notices appear
    # (e.g. after a Render container restart where ephemeral disk reverted to git),
    # auto-synchronize without sending to prevent spamming old notices!
    if _IS_STARTUP_CYCLE:
        _IS_STARTUP_CYCLE = False
        if (first_run and not SEND_ALL_ON_FIRST_RUN) or len(new_notices) > MAX_BURST_ON_STARTUP:
            logger.warning(
                "Cold startup detected with %d unrecorded notice(s) (threshold: %d). "
                "Auto-synchronizing state and marking them as seen to prevent channel spam after reboot.",
                len(new_notices), MAX_BURST_ON_STARTUP,
            )
            all_ids = sent_ids | {n.id for n in new_notices}
            save_sent_ids(all_ids)
            return

    _IS_STARTUP_CYCLE = False

    # 6. Send new notices to Telegram
    logger.info("Sending %d new notice(s) to Telegram...", len(new_notices))
    telegram_sent = set(send_notices(new_notices))

    # 7. Send new notices to WhatsApp (completely isolated, optional)
    whatsapp_sent = set()
    if ENABLE_WHATSAPP:
        logger.info("Sending %d new notice(s) to WhatsApp...", len(new_notices))
        try:
            from whatsapp_sender import send_notices as send_whatsapp_notices
            whatsapp_sent = set(send_whatsapp_notices(new_notices))
        except Exception:
            logger.exception("Error sending WhatsApp notices — Telegram is unaffected")

    # 8. Update state — mark notice as sent if delivered by at least one channel
    delivered_ids = telegram_sent | whatsapp_sent
    if delivered_ids:
        sent_ids.update(delivered_ids)
        save_sent_ids(sent_ids)
        logger.info(
            "Successfully delivered %d notice(s) across active channels: %s",
            len(delivered_ids), list(delivered_ids),
        )
    else:
        logger.warning("No notices were delivered successfully — will retry next cycle")


def main():
    # Start HTTP health check server and self-pinger (for cloud hosts like Render)
    threading.Thread(target=start_health_check_server, daemon=True).start()
    start_self_pinger()

    parser = argparse.ArgumentParser(
        description="RGUKT T&P Notice → Telegram Bot",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously, polling at the configured interval",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Dump the raw fetched HTML to debug_dump.html for inspection",
    )
    args = parser.parse_args()

    if args.loop:
        logger.info(
            "Starting in loop mode — polling every %d seconds (%d minutes)",
            POLL_INTERVAL_SECONDS, POLL_INTERVAL_SECONDS // 60,
        )
        while True:
            try:
                run_once(debug=args.debug)
            except KeyboardInterrupt:
                logger.info("Interrupted by user — shutting down")
                sys.exit(0)
            except Exception:
                logger.exception("Unexpected error in poll cycle — will retry")

            logger.info("Sleeping for %d seconds...", POLL_INTERVAL_SECONDS)
            try:
                time.sleep(POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logger.info("Interrupted by user — shutting down")
                sys.exit(0)
    else:
        run_once(debug=args.debug)


if __name__ == "__main__":
    main()
