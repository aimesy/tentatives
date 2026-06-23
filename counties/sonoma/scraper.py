"""Sonoma County public HTML tentative-ruling discovery."""

from __future__ import annotations

from urllib.parse import urlparse

from counties.common import PageRef, absolute_url, clean_text, extract_links
from counties.static_pdf import discover_static_pdfs

BASE = "https://sonoma.courts.ca.gov"
ROOT = f"{BASE}/online-services/tentative-rulings"
LANDING_PAGES = [
    ROOT,
    f"{ROOT}/civil-tentative-rulings",
    f"{ROOT}/family-law-tentative-rulings",
    f"{ROOT}/probate-tentative-rulings",
]
WAYBACK_PDF_PATTERNS = [
    "https://sonoma.courts.ca.gov/system/files/tentative-rulings/*.pdf",
]
PAGE_CAPTURE_URLS = [
    PageRef(url=url, title=f"Sonoma {url.rsplit('/', 1)[-1]}", page_kind="tentative_rulings_index")
    for url in LANDING_PAGES
]


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or ROOT,
        allowed_hosts={"sonoma.courts.ca.gov", "www.sonoma.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-rulings/" in parsed.path.lower(),
        default_division="Tentative Rulings",
    )


def discover_live_pages(html: str, page_url: str | None = None):
    source_page = page_url or ROOT
    refs: list[PageRef] = []
    for link in extract_links(html):
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"sonoma.courts.ca.gov", "www.sonoma.courts.ca.gov"}:
            continue
        path = parsed.path.lower()
        if "/online-services/tentative-rulings/" not in path:
            continue
        refs.append(
            PageRef(
                url=url,
                title=clean_text(link.text) or "Sonoma tentative rulings",
                page_kind="tentative_rulings_page",
            )
        )
    return refs
