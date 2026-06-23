"""Fresno County tentative-rulings scraper.

Discovery
---------
Fresno publishes department-specific PDFs from a single static tentative-rulings
page. Department numbers are embedded in the PDF filenames.

Parsing
-------
The current PDFs use a Fresno pleading-style packet. Most actual tentative
rulings start with:

    Tentative Ruling
    Re: <case title>
    Superior Court Case No. <case number>
    Hearing Date: <date> (Dept. <dept>)
    Motion: <motion>
    Tentative Ruling:
    <body>

The cover page can also list continued matters before the full ruling packet
begins. Those are parsed as continued rows when they carry a case number.
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

BASE = "https://www.fresno.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]


def _dept_hint(parsed: ParseResult, _text: str, _page_url: str) -> str | None:
    m = re.search(r"dept[-_ ]?(\d+)", parsed.path, re.I)
    return m.group(1) if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.fresno.courts.ca.gov", "fresno.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-rulings/" in parsed.path,
        default_division="Civil Law and Motion",
        dept_hint=_dept_hint,
    )


# ============================================================ PARSE


CASE_NUMBER_RE = re.compile(r"\b(?P<num>\d{2}[A-Z]{3,5}\d{5})\b")
BLOCK_START_RE = re.compile(
    r"(?im)^\s*(?:\(\d{1,3}\)\s*)?\n?\s*Tentative\s+Ruling\s*\n\s*Re:\s*"
)
HEADER_DATE_RE = re.compile(
    r"Tentative\s+Rulings\s+for\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
HEADER_DEPT_RE = re.compile(r"Department\s+(?P<dept>\d{1,4})\b", re.IGNORECASE)
HEARING_DATE_RE = re.compile(
    r"Hearing\s+Date:\s*(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})"
    r"(?:\s*\(Dept\.?\s*(?P<dept>\d{1,4})\))?",
    re.IGNORECASE,
)
CONTINUED_ROW_RE = re.compile(
    r"(?im)^\s*(?P<num>\d{2}[A-Z]{3,5}\d{5})\s+"
    r"(?P<title>[^\n]*?)\s+is\s+continued\s+to\s+"
    r"(?P<body>[^\n]+)"
)
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")
SIGNATURE_RE = re.compile(
    r"\n\s*Tentative\s+Ruling\s*\n\s*Issued\s+By:.*\Z",
    re.IGNORECASE | re.DOTALL,
)
MOTION_BOILERPLATE_RE = re.compile(
    r"\s*If\s+oral\s+argument\s+is\s+timely\s+requested\b.*",
    re.IGNORECASE | re.DOTALL,
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


def _parse_long_date(value: str) -> date | None:
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", value)
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
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bIS\s+CONTINUED\b", upper))
    has_off_calendar = bool(re.search(r"\bOFF\s+CALENDAR\b|\bTAKE[N]?\s+OFF\s+CALENDAR\b|\bVACATED\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:REQUIRED|REQUESTED|NECESSARY)\b", upper))

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


def _strip_pages(page_texts: list[str]) -> list[str]:
    out: list[str] = []
    for text in page_texts:
        lines = [line for line in text.splitlines() if not PAGE_NUMBER_RE.match(line)]
        out.append("\n".join(lines))
    return out


def _join_pages(page_texts: list[str]) -> tuple[str, list[int]]:
    offsets: list[int] = []
    parts: list[str] = []
    cursor = 0
    sep = "\n\n"
    for page in page_texts:
        offsets.append(cursor)
        parts.append(page)
        cursor += len(page) + len(sep)
    return sep.join(parts), offsets


def _page_for_offset(offsets: list[int], offset: int) -> int:
    page = 1
    for i, start in enumerate(offsets):
        if start <= offset:
            page = i + 1
        else:
            break
    return page


def _doc_date(text: str) -> date | None:
    m = HEADER_DATE_RE.search(text)
    return _parse_long_date(m.group("date")) if m else None


def _doc_dept(text: str, hint: str | None) -> str | None:
    m = HEADER_DEPT_RE.search(text)
    return m.group("dept") if m else hint


def _ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def _clean_motion_type(text: str) -> str:
    return " ".join(MOTION_BOILERPLATE_RE.sub("", text).split())


def _make_ruling(
    *,
    index: int,
    case_number: str,
    case_title: str,
    motion_type: str,
    body: str,
    full_text: str,
    start: int,
    end: int,
    offsets: list[int],
    source_sha256: str,
    source_url: str,
    hearing_date: date,
    dept: str | None,
    style: str,
) -> Ruling:
    outcome, conditional, continued_to = _classify(body)
    page_start = _page_for_offset(offsets, start)
    page_end = max(page_start, _page_for_offset(offsets, max(start, end - 1)))
    return Ruling(
        ruling_id=_ruling_id(source_sha256, index, case_number),
        county=COUNTY_SLUG,
        division="Civil Law and Motion",
        dept=dept,
        hearing_date=hearing_date,
        ruling_index=index,
        case_number=case_number,
        case_title=" ".join(case_title.split()),
        motion_type=_clean_motion_type(motion_type),
        outcome=outcome,
        outcome_text=body.strip(),
        conditional=conditional,
        continued_to=continued_to,
        body_text="",
        full_text=full_text.strip(),
        page_start=page_start,
        page_end=page_end,
        source_sha256=source_sha256,
        source_url=source_url,
        style=style,
        parser_version=PARSER_VERSION,
        ingest_ts=datetime.now(UTC),
    )


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

    pages = _strip_pages(raw_pages)
    plain, offsets = _join_pages(pages)
    hearing_date = _doc_date(plain)
    if hearing_date is None:
        return []
    dept = _doc_dept(plain, dept_hint)

    rulings: list[Ruling] = []
    seen_cases: set[str] = set()

    first_block = BLOCK_START_RE.search(plain)
    cover_text = plain[: first_block.start()] if first_block else plain
    for cm in CONTINUED_ROW_RE.finditer(cover_text):
        case_number = cm.group("num")
        if case_number in seen_cases:
            continue
        title = cm.group("title").strip()
        body = f"is continued to {cm.group('body').strip()}"
        seen_cases.add(case_number)
        rulings.append(
            _make_ruling(
                index=len(rulings) + 1,
                case_number=case_number,
                case_title=title,
                motion_type="Continued matter",
                body=body,
                full_text=cm.group(0),
                start=cm.start(),
                end=cm.end(),
                offsets=offsets,
                source_sha256=source_sha256,
                source_url=source_url,
                hearing_date=hearing_date,
                dept=dept,
                style="fresno-cover-continued",
            )
        )

    starts = list(BLOCK_START_RE.finditer(plain))
    for i, start_match in enumerate(starts):
        block_start = start_match.start()
        block_end = starts[i + 1].start() if i + 1 < len(starts) else len(plain)
        block = plain[block_start:block_end]

        header = re.search(
            r"(?is)Re:\s*(?P<title>.*?)\s*Superior\s+Court\s+Case\s+No\.?\s*"
            r"(?P<num>\d{2}[A-Z]{3,5}\d{5})",
            block,
        )
        if not header:
            continue
        case_number = header.group("num")
        if case_number in seen_cases:
            continue
        hd = HEARING_DATE_RE.search(block)
        block_date = _parse_long_date(hd.group("date")) if hd else hearing_date
        block_dept = hd.group("dept") if hd and hd.group("dept") else dept
        motion_match = re.search(
            r"(?is)\n\s*Motion:\s*(?P<motion>.*?)(?=\n\s*Tentative\s+Ruling\s*:)",
            block,
        )
        body_match = re.search(r"(?is)\n\s*Tentative\s+Ruling\s*:\s*(?P<body>.*)", block)
        if not body_match:
            continue
        body = SIGNATURE_RE.sub("", body_match.group("body")).strip()
        motion = motion_match.group("motion").strip() if motion_match else ""
        seen_cases.add(case_number)
        rulings.append(
            _make_ruling(
                index=len(rulings) + 1,
                case_number=case_number,
                case_title=header.group("title"),
                motion_type=motion,
                body=body,
                full_text=block,
                start=block_start,
                end=block_end,
                offsets=offsets,
                source_sha256=source_sha256,
                source_url=source_url,
                hearing_date=block_date or hearing_date,
                dept=block_dept,
                style="fresno-formal-ruling",
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
