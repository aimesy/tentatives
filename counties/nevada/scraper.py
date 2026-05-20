"""Nevada County tentative-ruling discovery.

The Nevada page is a static Drupal page with accordion sections for Nevada
City and Truckee. Ruling documents are court-hosted files under
`/system/files/tentative-rulings/`. Current pages may include Word documents;
this discovery module returns PDFs only because the archive parser pipeline is
currently PDF-based.
"""

from __future__ import annotations

from urllib.parse import urlparse

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs

BASE = "https://www.nevada.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings",
]


def _division_from_text(text: str) -> str | None:
    low = text.lower()
    if "case management" in low or "cmc" in low:
        return "Case Management"
    if "family" in low:
        return "Family Law"
    if "probate" in low:
        return "Probate"
    if "civil" in low or "law and motion" in low or "law & motion" in low:
        return "Law and Motion"
    if "guardianship" in low:
        return "Guardianship"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if not link.url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        text = link.text
        if "tentative" not in text.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.nevada.courts.ca.gov", "nevada.courts.ca.gov"}:
            continue
        if "/system/files/tentative-rulings/" not in parsed.path.lower():
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_from_text(text),
                link_text=text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)
