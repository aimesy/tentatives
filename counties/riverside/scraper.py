"""Riverside County tentative-rulings scraper.

Discovery
---------
Riverside publishes region and department PDFs from its tentative-rulings page.

Parsing
-------
The observed PDFs use a numbered table. Each item starts with `1.`, then table
labels, a case number, case title, hearing name, and a `Tentative Ruling:` body.
The parser keeps this as a deterministic table splitter.
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

BASE = "https://www.riverside.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]
READER_FALLBACK_LANDING_PAGES = True


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    # Require the "department"/"dept" keyword (with an optional separator) before
    # the code. The old pattern's bare ^/ alternatives never matched the keyword
    # and instead fabricated departments out of unrelated filename fragments
    # (e.g. "T01tentative.pdf" → "T01").
    hay = f"{parsed.path} {text}"
    m = re.search(r"(?:department|dept)\.?\s*[:#-]?\s*([A-Z]{0,3}\d{1,3})", hay, re.I)
    return m.group(1).upper() if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.riverside.courts.ca.gov", "riverside.courts.ca.gov"},
        path_test=lambda parsed, text: (
            parsed.path.lower().endswith(".pdf")
            and (
                "ruling" in parsed.path.lower()
                or "ruling" in text.lower()
                or "tentative" in parsed.path.lower()
                or "tentative" in text.lower()
            )
        ),
        default_division="Law and Motion",
        dept_hint=_dept_hint,
    )


# ============================================================ PARSE


ITEM_RE = re.compile(r"^\s*(?P<idx>\d{1,3})\.\s*$", re.MULTILINE)
TABLE_HEADER_RE = re.compile(r"^\s*CASE\s+#\s+CASE\s+NAME\s+HEARING\s+NAME\s*$", re.IGNORECASE | re.MULTILINE)
CASE_NUMBER_RE = re.compile(r"\b(?P<num>CV[A-Z]{2}\d{7}|[A-Z]{2,5}\d{7})\b", re.IGNORECASE)
HEADER_DATE_RE = re.compile(
    r"Tentative\s+Rulings\s+for\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
HEADER_DEPT_RE = re.compile(r"Department\s+(?P<dept>[A-Z]{0,3}\d{1,3})\b", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
TENTATIVE_RE = re.compile(
    r"^\s*(?:Tentative|Summary\s+of)\s+Ruling\s*:\s*(?P<body>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
MOTION_START_RE = re.compile(
    r"\b(MOTION|DEMURRER|PETITION|APPLICATION|EX\s+PARTE|ORDER\s+TO\s+SHOW|OSC|HEARING)\b",
    re.IGNORECASE,
)
CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
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


def _doc_date(text: str) -> date | None:
    m = HEADER_DATE_RE.search(text)
    return _parse_long_date(m.group("date")) if m else _parse_long_date(text[:1000])


def _doc_dept(text: str, hint: str | None) -> str | None:
    m = HEADER_DEPT_RE.search(text)
    return m.group("dept").upper() if m else hint


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANT(?:ED|S)?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bCONTINUES\s+THE\b|\bIS\s+CONTINUED\b", upper))
    has_off_calendar = bool(re.search(r"\bOFF\s+CALENDAR\b|\bTAKEN\s+OFF\s+CALENDAR\b|\bVACATED\b|\bMOOT\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:REQUIRED|REQUESTED|NECESSARY)\b|\bNO\s+TENTATIVE\s+RULING\b", upper))

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


def _split_title_motion(lines: list[str]) -> tuple[str, str]:
    cleaned = [
        line.strip()
        for line in lines
        if line.strip()
        and line.strip().upper() not in {"CASE #", "CASE NAME", "HEARING NAME"}
        and not re.match(r"^CASE\s+#\s+CASE\s+NAME\s+HEARING\s+NAME$", line.strip(), re.IGNORECASE)
    ]
    if not cleaned:
        return "", ""
    combined = " ".join(cleaned)
    m = MOTION_START_RE.search(combined)
    if m:
        return combined[: m.start()].strip(), combined[m.start():].strip()
    if len(cleaned) == 1:
        return cleaned[0], ""
    return " ".join(cleaned[:-1]), cleaned[-1]


def _ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def _split_embedded_table_blocks(block: str) -> list[tuple[int, int]]:
    headers = list(TABLE_HEADER_RE.finditer(block))
    if len(headers) <= 1:
        return [(0, len(block))]
    starts = [0] + [header.start() for header in headers[1:]]
    return [
        (start, starts[i + 1] if i + 1 < len(starts) else len(block))
        for i, start in enumerate(starts)
    ]


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

    items = list(ITEM_RE.finditer(plain))
    if not items:
        return []

    rulings: list[Ruling] = []
    for i, item in enumerate(items):
        item_end = items[i + 1].start() if i + 1 < len(items) else len(plain)
        item_block = plain[item.end():item_end]
        for rel_start, rel_end in _split_embedded_table_blocks(item_block):
            block_start = item.end() + rel_start
            block_end = item.end() + rel_end
            block = item_block[rel_start:rel_end]
            cn = CASE_NUMBER_RE.search(block)
            if not cn:
                continue
            case_number = cn.group("num").upper()

            before_body = block[: cn.start()] + block[cn.end():]
            tr = TENTATIVE_RE.search(block)
            if tr:
                before_body = block[:tr.start()]
                title_motion_text = before_body[cn.end():]
                body = block[tr.end():].strip()
                if tr.group("body"):
                    body = f"{tr.group('body').strip()}\n{body}".strip()
            else:
                title_motion_text = before_body
                body = block[cn.end():].strip()

            title, motion = _split_title_motion(title_motion_text.splitlines())
            outcome, conditional, continued_to = _classify(body)
            page_start = _page_for_offset(offsets, block_start)
            page_end = max(page_start, _page_for_offset(offsets, max(block_start, block_end - 1)))
            index = len(rulings) + 1
            rulings.append(
                Ruling(
                    ruling_id=_ruling_id(source_sha256, index, case_number),
                    county=COUNTY_SLUG,
                    division=division_hint or "Law and Motion",
                    dept=dept,
                    hearing_date=hearing_date,
                    ruling_index=index,
                    case_number=case_number,
                    case_title=" ".join(title.split()),
                    motion_type=" ".join(motion.split()),
                    outcome=outcome,
                    outcome_text=body,
                    conditional=conditional,
                    continued_to=continued_to,
                    body_text="",
                    full_text=plain[block_start:block_end].strip(),
                    page_start=page_start,
                    page_end=page_end,
                    source_sha256=source_sha256,
                    source_url=source_url,
                    style="riverside-numbered-table",
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
