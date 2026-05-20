"""Plumas County tentative-ruling discovery."""

from __future__ import annotations

from counties.static_pdf import discover_static_pdfs

BASE = "https://plumas.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"plumas.courts.ca.gov", "www.plumas.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-ruling/" in parsed.path,
        default_division="Civil / Probate / Family Law",
        dept_hint=lambda _parsed, _text, _page_url: "2",
    )
