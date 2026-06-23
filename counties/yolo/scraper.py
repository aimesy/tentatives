"""Yolo County public calendar-page tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from counties.common import PageRef, PdfRef, absolute_url, clean_text, extract_links, filename_from_url

BASE = "https://www.yolo.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings-calendar",
    f"{BASE}/online-services/probate-note-calendar",
]
PAGE_CAPTURE_URLS = [
    PageRef(
        url=f"{BASE}/online-services/tentative-rulings-calendar",
        title="Yolo Tentative Rulings Calendar",
        page_kind="tentative_rulings_calendar",
    ),
    PageRef(
        url=f"{BASE}/online-services/probate-note-calendar",
        title="Yolo Probate Note Calendar",
        page_kind="probate_note_calendar",
    ),
]


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def _calendar_document_paths(html: str) -> list[str]:
    text = html.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0022", '"')
    paths = re.findall(r"/document/[A-Za-z0-9_.-]+", text)
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _document_page_refs(html: str, page_url: str) -> list[PageRef]:
    refs: list[PageRef] = []
    for path in _calendar_document_paths(html):
        title = "Yolo probate notes" if "probate" in path else "Yolo tentative ruling"
        refs.append(
            PageRef(
                url=absolute_url(path, page_url),
                title=title,
                page_kind="document_page",
            )
        )
    return refs


def _division_for_url(url: str) -> str:
    low = url.lower()
    if "probate" in low:
        return "Probate Notes"
    return "Tentative Rulings"


def _pdf_refs_from_document(html: str, page_url: str) -> list[PdfRef]:
    refs: list[PdfRef] = []
    for link in extract_links(html):
        url = absolute_url(link.url, page_url)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.yolo.courts.ca.gov", "yolo.courts.ca.gov"}:
            continue
        if not parsed.path.lower().endswith(".pdf"):
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_for_url(url),
                link_text=clean_text(link.text) or filename_from_url(url),
                source_page_url=page_url,
            )
        )
    return refs


def discover_live_pages(html: str, page_url: str | None = None):
    return _document_page_refs(html, page_url or LANDING_PAGES[0])


def discover_live_page_extra(session, errors=None):
    refs: list[PageRef] = []
    for url in LANDING_PAGES:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        refs.extend(_document_page_refs(response.text, url))
    return refs


def discover_live_extra(session, errors=None):
    refs: list[PdfRef] = []
    for url in LANDING_PAGES:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        for page_ref in _document_page_refs(response.text, url):
            doc = session.get(page_ref.url, timeout=60)
            doc.raise_for_status()
            refs.extend(_pdf_refs_from_document(doc.text, page_ref.url))
    return refs
