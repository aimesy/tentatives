"""Monterey County public API-backed tentative-ruling discovery."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from counties.common import PdfRef
from counties.new_county_parsers import parse_monterey as parse

BASE = "https://www.monterey.courts.ca.gov/online-services/tentative-rulings"
PORTAL = "https://portal.monterey.courts.ca.gov/calendars/tentative-rulings"
API_BASE = "https://api.monterey.courts.ca.gov/api/tentativerulings"
LANDING_PAGES = [BASE]
ALLOWED_SOURCE_HOSTS = {"api.monterey.courts.ca.gov"}


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def _pacific_today() -> date:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return value or "tentative-ruling"


def discover_live_extra(session, errors=None):
    refs: list[PdfRef] = []
    today = _pacific_today()
    for offset in range(-7, 15):
        hearing_date = today + timedelta(days=offset)
        date_url = f"{API_BASE}/date?date={hearing_date.isoformat()}"
        response = session.get(date_url, timeout=60)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            case_id = row.get("caseId")
            document_id = row.get("documentId") or row.get("documentVersionId")
            if case_id is None or document_id is None:
                continue
            case_number = str(row.get("caseNumber") or "case")
            dept = str(row.get("department") or "").replace("Department", "").strip() or None
            filename = _safe_filename(f"{hearing_date.isoformat()}-{case_number}-{document_id}") + ".pdf"
            refs.append(
                PdfRef(
                    url=f"{API_BASE}/{case_id}/doc/{document_id}",
                    filename=filename,
                    dept_hint=dept,
                    division_hint="Tentative Rulings",
                    link_text=str(row.get("description") or "Tentative Ruling"),
                    source_page_url=date_url,
                )
            )
    return refs
