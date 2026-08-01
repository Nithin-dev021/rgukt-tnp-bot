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
)
from scraper import fetch_page, parse_notices, dump_html
from state import load_sent_ids, save_sent_ids, is_first_run, filter_new_notices
from telegram_sender import send_notices


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
    """Periodically ping the service URL to prevent Render Free tier from sleeping (resets 15-min idle timer)."""
    def pinger():
        time.sleep(30)  # Wait for initial startup
        target_url = os.environ.get("RENDER_EXTERNAL_URL")
        port_str = os.environ.get("PORT")

        if not target_url and port_str:
            target_url = f"http://127.0.0.1:{port_str}"

        if not target_url:
            return

        log = logging.getLogger("tnp_bot")
        log.info("Self-pinger initialized — keeping Render awake at %s", target_url)

        import requests
        while True:
            try:
                time.sleep(600)  # Ping every 10 minutes
                resp = requests.get(target_url, timeout=15)
                log.debug("Self-ping status: %d", resp.status_code)
            except Exception as e:
                log.debug("Self-ping warning: %s", e)

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
    """Execute one poll cycle: fetch → parse → filter → send → save."""

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
        logger.warning(
            "0 notices parsed — the site structure may have changed. "
            "Run with --debug and inspect debug_dump.html to fix selectors."
        )
        return

    logger.info("Parsed %d notice(s) from the page", len(notices))

    # 3. Load state and check for first run
    first_run = is_first_run()
    sent_ids = load_sent_ids()

    # 4. Filter new notices
    new_notices = filter_new_notices(notices, sent_ids)

    if not new_notices:
        logger.info("No new notices to send")
        return

    # 5. Handle first-run behavior
    if first_run and not SEND_ALL_ON_FIRST_RUN:
        logger.info(
            "First run detected — recording %d notice(s) as 'seen' without sending. "
            "Set SEND_ALL_ON_FIRST_RUN=true to change this behavior.",
            len(new_notices),
        )
        all_ids = sent_ids | {n.id for n in new_notices}
        save_sent_ids(all_ids)
        return

    # 6. Send new notices to Telegram
    logger.info("Sending %d new notice(s) to Telegram...", len(new_notices))
    successfully_sent = send_notices(new_notices)

    # 7. Send new notices to WhatsApp (completely isolated, optional)
    if ENABLE_WHATSAPP:
        logger.info("Sending %d new notice(s) to WhatsApp...", len(new_notices))
        try:
            from whatsapp_sender import send_notices as send_whatsapp_notices
            send_whatsapp_notices(new_notices)
        except Exception:
            logger.exception("Error sending WhatsApp notices — Telegram is unaffected")

    # 8. Update state — only mark successfully sent notices
    if successfully_sent:
        sent_ids.update(successfully_sent)
        save_sent_ids(sent_ids)
        logger.info(
            "Successfully sent %d/%d notice(s)",
            len(successfully_sent), len(new_notices),
        )
    else:
        logger.warning("No notices were sent successfully — will retry next cycle")


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
