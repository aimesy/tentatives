"""Calaveras County tentative-ruling discovery.

Calaveras keeps long static lists for case-management and civil law-and-motion
PDFs. Filenames vary by year and by upload location, so discovery keys off the
link text and the fact that the link target is a court-hosted PDF.
"""

from __future__ import annotations

from urllib.parse import urlparse

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs

BASE = "https://www.calaveras.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings/tentative-rulings-case-management",
    f"{BASE}/online-services/tentative-rulings/tentative-rulings-civil-law-and-motion-calendar",
]


def _division_from_page(page_url: str, text: str) -> str | None:
    haystack = f"{page_url} {text}".lower()
    if "case-management" in haystack or "cmc" in haystack:
        return "Case Management"
    if "civil-law" in haystack or "civil tentative" in haystack:
        return "Civil Law and Motion"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if not link.url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        text = link.text
        if "tentative" not in text.lower() and "cmc" not in text.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.calaveras.courts.ca.gov", "calaveras.courts.ca.gov"}:
            continue
        if not parsed.path.lower().startswith("/system/files/"):
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_from_page(source_page, text),
                link_text=text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)
