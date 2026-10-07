"""Stanislaus County public HTML tentative-ruling discovery."""

from __future__ import annotations

from urllib.parse import urlparse

from counties.common import PageRef, absolute_url, clean_text, extract_links
from counties.new_county_parsers import parse_stanislaus_page as parse_page_capture

BASE = "https://www.stanislaus.courts.ca.gov"
ROOT = f"{BASE}/online-services/tentative-rulings"
LANDING_PAGES = [
    ROOT,
    f"{ROOT}/civil-tentative-rulings",
    f"{ROOT}/family-law-tentative-rulings",
    "https://www.stanislaus.courts.ca.gov/divisions/probate/probate-notes",
]
PAGE_CAPTURE_URLS = [
    PageRef(url=url, title=f"Stanislaus {url.rsplit('/', 1)[-1]}", page_kind="tentative_rulings_page")
    for url in LANDING_PAGES
]


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def discover_live_pages(html: str, page_url: str | None = None):
    source_page = page_url or ROOT
    refs: list[PageRef] = []
    for link in extract_links(html):
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.stanislaus.courts.ca.gov", "stanislaus.courts.ca.gov"}:
            continue
        path = parsed.path.lower()
        if "/online-services/tentative-rulings/" not in path and "/divisions/probate/probate-notes" not in path:
            continue
        refs.append(
            PageRef(
                url=url,
                title=clean_text(link.text) or "Stanislaus tentative rulings",
                page_kind="tentative_rulings_page",
            )
        )
    return refs
