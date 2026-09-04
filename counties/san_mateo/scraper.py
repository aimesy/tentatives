"""San Mateo County public tentative-ruling source discovery."""

from __future__ import annotations

from urllib.parse import ParseResult

from counties.new_county_parsers import parse_san_mateo as parse
from counties.static_pdf import discover_static_pdfs

BASE = "https://sanmateo.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [
    BASE,
    f"{BASE}/civil-law-motion-tentative-rulings",
    f"{BASE}/presiding-judge-law-motion-calendar-tentative-rulings",
    f"{BASE}/probate-department-tentative-rulings",
    f"{BASE}/complex-law-and-motion-tentative-rulings",
    f"{BASE}/special-set-matters-tentative-rulings",
]
ALLOWED_SOURCE_HOSTS = {"web.sanmateocourt.org"}
WAYBACK_PDF_PATTERNS = [
    "https://web.sanmateocourt.org/online_services/law_and_motion_tentative_rulings/lawmotion/*/*.pdf",
    "https://web.sanmateocourt.org/online_services/law_and_motion_tentative_rulings/LawMotion/*/*.pdf",
    "https://web.sanmateocourt.org/online_services/law_and_motion_tentative_rulings/webfiles/*.pdf",
    "https://web.sanmateocourt.org/online_services/probate_tentative_rulings/webfiles/*.pdf",
]


def _division_hint(_parsed: ParseResult, text: str, page_url: str) -> str | None:
    hay = f"{page_url} {text}".lower()
    if "probate" in hay:
        return "Probate"
    if "complex" in hay:
        return "Complex Civil"
    if "presiding" in hay:
        return "Presiding Judge Law and Motion"
    if "special" in hay:
        return "Special Set Matters"
    if "civil" in hay:
        return "Civil Law and Motion"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={
            "sanmateo.courts.ca.gov",
            "www.sanmateo.courts.ca.gov",
            "web.sanmateocourt.org",
        },
        path_test=lambda parsed, text: (
            parsed.path.lower().endswith(".pdf")
            and "tentative" in f"{parsed.path} {text}".lower()
        ),
        division_hint=_division_hint,
    )
