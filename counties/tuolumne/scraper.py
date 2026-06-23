"""Tuolumne County tentative-rulings scraper.

Discovery
---------
Tuolumne publishes direct PDFs for tentative rulings and case notes.

Parsing
-------
The observed tentative-ruling PDF is a consolidated calendar with one ruling
per page. Each page repeats a header, then a case row:

    Department 2 June 3, 2026   8:30 am Date Filed DA Case #
    CV68039 01/27/2026 1 Petition in re: ...

The narrative ruling starts after the generated calendar timestamp near the end
of the header block.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, date, datetime
from urllib.parse import ParseResult

import pypdf

from counties.static_pdf import discover_static_pdfs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

BASE = "https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes"
LANDING_PAGES = [BASE]


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}"
    m = re.search(r"(?:department|dept|tr[-_ ]?d|case[-_ ]?notes?[-_ ]?d)(?:[-_ ]?)(\d+)", hay, re.I)
    return m.group(1) if m else None


def _division_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}"
    if re.search(r"case[-_ ]?notes?", hay, re.I):
        return "Case Notes"
    return "Civil Law and Motion"


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.tuolumne.courts.ca.gov", "tuolumne.courts.ca.gov"},
        path_test=lambda parsed, text: (
            "/system/files/tentative-rulings/" in parsed.path
        ),
        dept_hint=_dept_hint,
        division_hint=_division_hint,
    )


# ============================================================ PARSE


HEADER_RE = re.compile(
    r"Department\s+(?P<dept>\d+)\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
CASE_ROW_RE = re.compile(
    r"^\s*(?P<num>[A-Z]{2,5}\d{5,7})\s+"
    r"(?P<filed>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<calendar_index>\d{1,3})\s+"
    r"(?P<title>.+?)\s*$",
    re.MULTILINE,
)
TIMESTAMP_RE = re.compile(
    r"^\s*\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[ap]\.?m\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
TRACKING_RE = re.compile(
    r"\b(?:File\s+Tracking|High\s+Density|Complaint\s+File\s+Tracking|Petition\s+File\s+Tracking)\b",
    re.IGNORECASE,
)
EVENT_RE = re.compile(
    r"\b(?:Motion|Petition|Case\s+Management|Conference|Review|Hearing|Trial|OSC|Order|FURTHER)\b",
    re.IGNORECASE,
)
NARRATIVE_START_RE = re.compile(
    r"^(?:This|The|Before|Pursuant|Plaintiff|Defendant|Petitioner|Respondent|If)\b",
    re.IGNORECASE,
)
CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE | re.DOTALL,
)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


def _parse_long_date(text: str) -> date | None:
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", text)
    if not m:
        return None
    month = _MONTHS.get(m.group(1).upper())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANT(?:ED|S)?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bSET\s+FOR\s+HEARING\b|\bWILL\s+BE\s+SET\b", upper))
    has_off_calendar = bool(re.search(r"\bOFF\s+CALENDAR\b|\bVACATED\b|\bDROPPED\s+FROM\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:REQUIRED|NECESSARY)\b|\bMUST\s+APPEAR\b", upper))

    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_off_calendar:
        outcome = "off_calendar"
    elif has_appearance:
        outcome = "appearance_required"
    else:
        outcome = "other"

    continued_to = None
    if has_continued:
        m = CONTINUED_TO_RE.search(text)
        if m:
            month = _MONTHS.get(m.group("month").upper())
            if month:
                try:
                    continued_to = date(int(m.group("year")), month, int(m.group("day")))
                except ValueError:
                    pass
    return outcome, conditional, continued_to


def _page_meta(text: str, dept_hint: str | None) -> tuple[date | None, str | None]:
    m = HEADER_RE.search(text)
    if not m:
        return _parse_long_date(text), dept_hint
    return _parse_long_date(m.group("date")), m.group("dept") or dept_hint


def _split_page(page_text: str, case_match: re.Match[str]) -> tuple[str, str, str]:
    after_case_line = page_text[case_match.end():]
    timestamp_match = None
    for tm in TIMESTAMP_RE.finditer(after_case_line):
        timestamp_match = tm
    if timestamp_match:
        header_tail = after_case_line[: timestamp_match.start()]
        body = after_case_line[timestamp_match.end():].strip()
    else:
        lines = after_case_line.splitlines()
        split_idx = None
        body_start_idx = None
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped and NARRATIVE_START_RE.match(stripped):
                split_idx = idx
                body_start_idx = idx
                break
            if not stripped:
                first_body = next((later.strip() for later in lines[idx + 1:] if later.strip()), "")
                if NARRATIVE_START_RE.match(first_body):
                    split_idx = idx
                    body_start_idx = idx + 1
                    break
        if split_idx is None:
            header_tail = after_case_line
            body = ""
        else:
            header_tail = "\n".join(lines[:split_idx])
            body = "\n".join(lines[body_start_idx if body_start_idx is not None else split_idx + 1:]).strip()

    title_lines = [case_match.group("title").strip()]
    motion_lines: list[str] = []
    title_done = False
    for raw in header_tail.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("Attorney:"):
            title_done = True
            continue
        if re.match(r"^\d{2}/\d{2}/\d{4}\b", s) or TRACKING_RE.search(s):
            continue
        if not title_done and not EVENT_RE.search(s):
            title_lines.append(s)
            continue
        title_done = True
        if EVENT_RE.search(s):
            motion_lines.append(s)
        elif motion_lines and not NARRATIVE_START_RE.match(s):
            motion_lines.append(s)

    return " ".join(title_lines), " / ".join(motion_lines), body


def _ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    if source_sha256 is None:
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return []
    raw_pages = [page.extract_text() or "" for page in reader.pages]
    if not raw_pages:
        return []

    rulings: list[Ruling] = []
    for page_index, page_text in enumerate(raw_pages, start=1):
        case_match = CASE_ROW_RE.search(page_text)
        if not case_match:
            continue
        hearing_date, dept = _page_meta(page_text, dept_hint)
        if hearing_date is None:
            continue
        case_title, motion_type, body = _split_page(page_text, case_match)
        outcome, conditional, continued_to = _classify(body)
        case_number = case_match.group("num").upper()
        index = len(rulings) + 1
        rulings.append(
            Ruling(
                ruling_id=_ruling_id(source_sha256, index, case_number),
                county=COUNTY_SLUG,
                division=division_hint or "Civil Law and Motion",
                dept=dept,
                hearing_date=hearing_date,
                ruling_index=index,
                case_number=case_number,
                case_title=" ".join(case_title.split()),
                motion_type=" ".join(motion_type.split()),
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=page_text.strip(),
                page_start=page_index,
                page_end=page_index,
                source_sha256=source_sha256,
                source_url=source_url,
                style="tuolumne-consolidated-calendar",
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.now(UTC),
            )
        )

    return rulings


def parse_file(
    path: str,
    source_url: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    with open(path, "rb") as f:
        data = f.read()
    if source_url is None:
        source_url = f"file://{path}"
    return parse(data, source_url=source_url, dept_hint=dept_hint, division_hint=division_hint)
