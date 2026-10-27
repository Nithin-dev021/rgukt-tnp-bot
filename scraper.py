"""
Scraper for the RGUKT Basar T&P Cell notice board.

Fetches the page HTML and parses each notice into a structured record:
    id, date, title, body, attachment_url, url_link, published_by, source_url
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import TNP_BASE_URL, TNP_INDEX_URL, USER_AGENT, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


VALID_PLACEMENT_PUBLISHERS = [
    "TNPBPO",
    "TP CELL BASAR",
    "TP CELL",
    "T&P CELL",
    "TNP CELL",
    "PLACEMENT",
    "TRAINING & PLACEMENT",
]


def is_placement_notice(publisher: str = "", category: str = "", title: str = "") -> bool:
    """Determine if a notice belongs to Training & Placement."""
    pub = (publisher or "").upper().strip()
    cat = (category or "").upper().strip()
    tit = (title or "").upper().strip()

    # Match publisher variations (TNPBPO, TP CELL BASAR, TP CELL, etc.)
    if any(p in pub for p in VALID_PLACEMENT_PUBLISHERS):
        return True

    # Match Category: Placements
    if "PLACEMENT" in cat:
        return True

    # Match placement title keywords as safety net
    placement_keywords = [
        "T&P:",
        "RECRUITMENT",
        "CAMPUS DRIVE",
        "PLACEMENT",
        "INTERNSHIP",
    ]
    if any(k in tit for k in placement_keywords):
        return True

    return False


def parse_notice_date(date_str: str) -> Optional[datetime]:
    """Parse notice date string like '27 Oct 2026' or '16, Sep 2026' into a datetime object."""
    if not date_str:
        return None
    cleaned = date_str.strip().rstrip(":")
    for fmt in (
        "%d %b %Y",
        "%d, %b %Y",
        "%d %B %Y",
        "%d, %B %Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            pass
    return None


@dataclass
class Notice:
    """A single T&P notice."""
    id: str                           # e.g. "14851"
    date: str                         # e.g. "24, Jul 2026"
    title: str                        # e.g. "005: Walk-in Recruitment Drive – Aakriti Housing"
    body: str                         # full body text
    attachment_url: Optional[str]     # absolute URL to downloadable file, if any
    url_link: Optional[str]           # external registration/info URL, if any
    published_by: Optional[str]       # "Published by: ..." line, if any
    source_url: str                   # page URL where this notice was found

    def is_recent(self, max_days: int = 3) -> bool:
        """Check if the notice was published within max_days (with 1-day buffer for timezone)."""
        dt = parse_notice_date(self.date)
        if not dt:
            # If date cannot be parsed, treat as recent to be safe
            return True
        age_seconds = (datetime.now() - dt).total_seconds()
        # Generous buffer (+ 86400s) to absorb Render UTC vs Indian Standard Time
        return age_seconds <= (max_days * 86400 + 86400)


def fetch_page(url: str = TNP_INDEX_URL) -> str:
    """
    Fetch the raw HTML of the T&P notice page.
    Raises requests.RequestException on failure.
    """
    headers = {"User-Agent": USER_AGENT}
    logger.info("Fetching %s", url)
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def parse_notices(html: str, source_url: str = TNP_INDEX_URL) -> List[Notice]:
    """
    Parse notice blocks from the page HTML.
    Supports both the new E-Notice accordion portal (/hub/notice/index)
    and the legacy Bootstrap card portal (/hub/tnp/index).
    """
    soup = BeautifulSoup(html, "html.parser")
    notices: List[Notice] = []

    # ── 1. Check for new E-Notice system (accordion-item) ───────────────
    accordion_items = soup.find_all("div", class_="accordion-item")
    if accordion_items:
        logger.info("Detected new E-Notice accordion layout (%d items)", len(accordion_items))
        for item in accordion_items:
            try:
                notice = _parse_single_accordion_item(item, source_url)
                if notice:
                    notices.append(notice)
            except Exception:
                logger.exception("Failed to parse an accordion notice item, skipping")
        logger.info("Parsed %d placement notice(s) from E-Notice portal", len(notices))
        return notices

    # ── 2. Fallback: Legacy Bootstrap 4 cards (/hub/tnp/index) ─────────
    content_area = soup.find("div", class_="card-body text-success")
    if not content_area:
        content_area = soup.find(id="accordion") or soup.find("div", class_="card-body")

    if not content_area:
        logger.warning("Could not find the main notice container")
        return notices

    notice_cards = content_area.find_all("div", class_="card", recursive=False)
    if not notice_cards:
        notice_cards = content_area.find_all("div", class_="card")

    logger.info("Found %d legacy notice card(s) on the page", len(notice_cards))

    for card in notice_cards:
        try:
            notice = _parse_single_card(card, source_url)
            if notice:
                notices.append(notice)
        except Exception:
            logger.exception("Failed to parse a legacy notice card, skipping it")

    return notices


def _parse_single_accordion_item(item, source_url: str) -> Optional[Notice]:
    """Parse a Bootstrap 5 accordion notice from /hub/notice/index."""
    cat = item.get("data-category", "")

    # ID from accordion-collapse
    collapse_div = item.find("div", class_="accordion-collapse")
    if not collapse_div or not collapse_div.get("id"):
        return None
    raw_id = collapse_div["id"]
    notice_id = raw_id.replace("nc-", "").strip()
    if not notice_id:
        return None

    # Date
    date_tag = item.find("span", class_="notice-date")
    date_str = ""
    if date_tag:
        # e.g. "27 Oct 2026"
        date_str = date_tag.get_text(strip=True)

    # Subject / Title
    subject_tag = item.find("span", class_="notice-subject")
    title = subject_tag.get_text(" ", strip=True) if subject_tag else ""
    title = re.sub(r"\s+", " ", title).strip()

    # Publisher ("Published by: TNPBPO", "TP CELL BASAR", etc.)
    publisher = ""
    for tag in item.find_all(["p", "span", "div"]):
        text = tag.get_text(strip=True)
        if "Published by:" in text:
            publisher = text.split("Published by:", 1)[1].strip()
            break

    # Filter: must be a placement notice (matches TNPBPO, TP CELL BASAR, TP CELL, or Placements category)
    if not is_placement_notice(publisher=publisher, category=cat, title=title):
        return None

    # Body text
    body_div = item.find("div", class_="notice-body") or item.find("div", class_="accordion-body")
    body_text = body_div.get_text("\n", strip=True) if body_div else ""

    # Attachment URL (look for /download/ link, PDF/doc extensions, or download text)
    attachment_url = None
    for a in item.find_all("a", href=True):
        href = a["href"]
        text_lower = a.get_text().lower()
        if (
            "/download/" in href.lower()
            or href.lower().endswith((".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip"))
            or "download" in text_lower
            or "attachment" in text_lower
        ):
            attachment_url = urljoin(TNP_BASE_URL, href)
            break

    # External link (forms, JD links, or view link)
    url_link = None
    for a in item.find_all("a", href=True):
        href = a["href"]
        if (href.startswith("http") and "rgukt.ac.in" not in href) or "view link" in a.get_text().lower():
            url_link = href
            break

    return Notice(
        id=notice_id,
        date=date_str,
        title=title,
        body=body_text,
        attachment_url=attachment_url,
        url_link=url_link,
        published_by=publisher,
        source_url=f"{source_url}#nc-{notice_id}",
    )


def _parse_single_card(card, source_url: str) -> Optional[Notice]:
    """Parse a single Bootstrap card element into a Notice."""

    # ── Header: extract ID, date, title ─────────────────────────
    header_link = card.select_one("div.card-header a.card-link")
    if not header_link:
        logger.debug("Skipping card with no header link")
        return None

    # ID from the href fragment: href="#14851" → "14851"
    href = header_link.get("href", "")
    notice_id = href.lstrip("#").strip()
    if not notice_id:
        logger.debug("Skipping card with no anchor ID")
        return None

    # Date from the <font> tag
    font_tag = header_link.find("font")
    date_str = ""
    if font_tag:
        date_str = font_tag.get_text(strip=True).rstrip(":")

    # Title: full header text minus the date portion and any whitespace junk
    # Get the full text, remove the date part, strip leading/trailing junk
    full_header_text = header_link.get_text(" ", strip=True)
    if date_str:
        # Remove "24, Jul 2026:" prefix from the combined text
        title = full_header_text.replace(date_str + ":", "", 1).strip()
    else:
        title = full_header_text

    # Clean up stray whitespace
    title = re.sub(r"\s+", " ", title).strip()

    # ── Body: extract text, attachment, external links ──────────
    collapse_div = card.find("div", id=notice_id) or card.find("div", class_="collapse")
    body_text = ""
    attachment_url = None
    url_link = None
    published_by = None

    if collapse_div:
        body_div = collapse_div.find("div", class_="card-body") or collapse_div
    else:
        body_div = card.find("div", class_="card-body")

    if body_div:
        # Look for attachment download link (checks download URL, extension, and anchor text)
        for a_tag in body_div.find_all("a", href=True):
            href_val = a_tag["href"]
            tag_text = a_tag.get_text().lower()
            if (
                "download" in href_val.lower()
                or href_val.lower().endswith((".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip"))
                or "attachment" in tag_text
                or "download" in tag_text
            ):
                attachment_url = urljoin(TNP_BASE_URL, href_val)
                break

        # Look for external URL links (registration forms, etc.)
        for a_tag in body_div.find_all("a", href=True):
            href_val = a_tag["href"]
            if href_val.startswith("http") and "rgukt.ac.in" not in href_val:
                url_link = href_val
                break

        # Extract body text
        body_text = body_div.get_text("\n", strip=True)

        # Look for "Published by:" pattern
        pub_match = re.search(r"Published\s+by\s*:\s*(.+)", body_text, re.IGNORECASE)
        if pub_match:
            published_by = pub_match.group(1).strip()

    return Notice(
        id=notice_id,
        date=date_str,
        title=title,
        body=body_text,
        attachment_url=attachment_url,
        url_link=url_link,
        published_by=published_by,
        source_url=f"{source_url}#{notice_id}",
    )


def dump_html(html: str, filepath: str = "debug_dump.html") -> None:
    """Write the raw HTML to a file for debugging."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Raw HTML dumped to %s", filepath)
