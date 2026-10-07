"""Ventura County public tentative-rulings/probate-notes discovery."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from counties.common import PdfRef
from counties.new_county_parsers import parse_ventura as parse

BASE = "https://www2.ventura.courts.ca.gov/CaseInquiry/TentativeRulings"
LANDING_PAGES = [BASE]

TOKEN_RE = re.compile(r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"')
VIEW_FILE_RE = re.compile(r'href="(?P<href>[^"]*/CaseInquiry/ViewFile/(?P<id>\d+)[^"]*)"', re.IGNORECASE)


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def _pacific_today() -> date:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def _form_date(value: date) -> str:
    return f"{value.month}/{value.day}/{value.year}"


def _token(html: str) -> str | None:
    match = TOKEN_RE.search(html)
    return match.group(1) if match else None


def discover_live_extra(session, errors=None):
    refs: list[PdfRef] = []
    response = session.get(BASE, timeout=60)
    response.raise_for_status()
    token = _token(response.text)
    if not token:
        return refs

    today = _pacific_today()
    for offset in range(-2, 8):
        hearing_date = today + timedelta(days=offset)
        data = {
            "SearchCaseNumber": "",
            "SearchFromDate": _form_date(hearing_date),
            "__RequestVerificationToken": token,
        }
        result = session.post(BASE, data=data, headers={"Referer": BASE}, timeout=60)
        result.raise_for_status()
        token = _token(result.text) or token
        seen_ids: set[str] = set()
        for match in VIEW_FILE_RE.finditer(result.text):
            file_id = match.group("id")
            if file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            refs.append(
                PdfRef(
                    url=urljoin(BASE, match.group("href")),
                    filename=f"ventura-{hearing_date.isoformat()}-{file_id}.pdf",
                    division_hint="Tentative Rulings / Probate Notes",
                    link_text=f"Ventura {hearing_date.isoformat()} ViewFile {file_id}",
                    source_page_url=f"{BASE}?hearing_date={hearing_date.isoformat()}",
                )
            )
    return refs
