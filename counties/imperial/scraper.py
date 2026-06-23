"""Imperial County public tentative-ruling source discovery."""

from __future__ import annotations

from counties.static_pdf import discover_static_pdfs

BASE = "https://www.imperial.courts.ca.gov/general-information/tentative-rulings"
LANDING_PAGES = [
    BASE,
    "https://www.imperial.courts.ca.gov/news/tentative-rulings",
]
WAYBACK_PDF_PATTERNS = [
    "https://www.imperial.courts.ca.gov/system/files/tentative-rulings/*.pdf",
]


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.imperial.courts.ca.gov", "imperial.courts.ca.gov"},
        path_test=lambda parsed, text: (
            "/system/files/tentative-rulings/" in parsed.path.lower()
            or "tentative" in f"{parsed.path} {text}".lower()
        ),
        default_division="Civil Law and Motion",
    )
