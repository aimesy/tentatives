"""Amador County tentative-ruling discovery.

Amador's public legacy page is not a form. It is four dropdowns whose option
values point directly at historical PDFs. The page says new rulings moved to
the portal after February 15, 2022, but the dropdowns still expose 2020-2022
PDFs.
"""

from __future__ import annotations

from urllib.parse import urlparse

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs

BASE = "https://www.amadorcourt.org/os-tentativerulings.aspx"
LANDING_PAGES = [BASE]
WAYBACK_PDF_PATTERNS = [
    "www.amadorcourt.org/tentativeRulings/*",
    "amadorcourt.org/tentativeRulings/*",
]

_SELECT_DIVISIONS = {
    "selectid1": "Civil Law and Motion",
    "selectid2": "Civil Case Management Conference",
    "selectid3": "Family Law Case Management",
    "selectid4": "Child Support",
}

_PATH_DIVISIONS = {
    "CivilLawAndMotion": "Civil Law and Motion",
    "CivilCaseMgtConference": "Civil Case Management Conference",
    "FamilyLawCaseMgt": "Family Law Case Management",
    "ChildSupport": "Child Support",
}


def _division_for(raw_url: str, parent_attrs: dict[str, str] | None) -> str | None:
    if parent_attrs:
        select_id = (parent_attrs.get("id") or parent_attrs.get("name") or "").lower()
        if select_id in _SELECT_DIVISIONS:
            return _SELECT_DIVISIONS[select_id]
    for segment, division in _PATH_DIVISIONS.items():
        if f"/{segment}/" in raw_url:
            return division
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    refs: list[PdfRef] = []
    source_page = page_url or base_url
    for link in extract_links(html):
        if ".pdf" not in link.url.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.amadorcourt.org", "amadorcourt.org"}:
            continue
        if "/tentativerulings/" not in parsed.path.lower():
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_for(link.url, link.parent_attrs),
                link_text=link.text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)
