"""Orange County tentative-ruling discovery.

Orange publishes index pages for civil, family, and probate/mental-health
tentatives. Each index links to stable current PDFs, usually named
`*rulings.pdf`. History for those stable URLs is a Wayback problem rather than
a live-site pagination problem.
"""

from __future__ import annotations

from urllib.parse import urlparse

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs

BASE = "https://www.occourts.org"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings/civil-tentative-rulings",
    f"{BASE}/online-services/tentative-rulings/family-law-tentative-rulings",
    f"{BASE}/online-services/tentative-rulings/probate-tentative-rulings",
]


def _division_from_page(page_url: str) -> str | None:
    path = urlparse(page_url).path.lower()
    if "family-law" in path:
        return "Family Law"
    if "probate" in path:
        return "Probate"
    if "civil" in path:
        return "Civil"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if ".pdf" not in link.url.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {
            "www.occourts.org",
            "occourts.org",
            "live-jcc-oc.pantheonsite.io",
        }:
            continue
        if "/tentative-rulings/" not in parsed.path.lower():
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_from_page(source_page),
                link_text=link.text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)
