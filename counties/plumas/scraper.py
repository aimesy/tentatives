"""Plumas County tentative-rulings scraper.

Discovery
---------
Plumas publishes Department 2 PDFs from a static tentative-rulings page.

Parsing
-------
The PDFs are compact calendar packets. Each row begins with `Case No.`, then a
case number, case title, and a `Tentative Ruling:` body. Section headings like
`PROBATE CALENDAR`, `LAW & MOTION CALENDAR`, and `CASE MANAGEMENT
CONFERENCE` assign the division for following rows.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, date, datetime

import pypdf

from counties.static_pdf import discover_static_pdfs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

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


# ============================================================ PARSE


_CASE_NUMBER_INNER = (
    r"[A-Z]{1,3}\d{2}-\d{4,6}"  # PR23-00058, CV25-00176, LC25-00283
    r"|\d{4,6}M?"  # 27031M
)
CASE_ANCHOR_RE = re.compile(
    rf"^\s*Case\s+No\.?\s+(?P<num>{_CASE_NUMBER_INNER})\s+(?P<title>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
LONG_DATE_RE = re.compile(
    r"\b(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
DEPT_RE = re.compile(r"Department\s+(?P<dept>Two|2)\b", re.IGNORECASE)
SECTION_RE = re.compile(
    r"^\s*(?P<section>"
    r"PROBATE\s+CALENDAR"
    r"|LAW\s*&\s*MOTION\s+CALENDAR"
    r"|CASE\s+MANAGEMENT\s+CONFERENCES?"
    r"|FAMILY\s+LAW\s+CALENDAR"
    r")\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
TENTATIVE_PREFIX_RE = re.compile(r"^\s*Tentative\s+Ruling\s*:\s*", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")
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


def _parse_date(text: str) -> date | None:
    for m in LONG_DATE_RE.finditer(text):
        month = _MONTHS.get(m.group("month").upper())
        if not month:
            continue
        try:
            return date(int(m.group("year")), month, int(m.group("day")))
        except ValueError:
            continue
    return None


def _section_name(raw: str) -> str:
    upper = raw.upper()
    if "PROBATE" in upper:
        return "Probate"
    if "LAW" in upper and "MOTION" in upper:
        return "Law and Motion"
    if "CASE MANAGEMENT" in upper:
        return "Case Management Conference"
    if "FAMILY" in upper:
        return "Family Law"
    return " ".join(raw.split()).title()


def _dept_from_header(text: str, hint: str | None) -> str | None:
    m = DEPT_RE.search(text)
    if not m:
        return hint
    return "2"


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    negative_appearance = bool(re.search(r"NO\s+APPEARANCE\s+(?:IS\s+)?(?:REQUIRED|NECESSARY)", upper))
    has_denied = bool(re.search(r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANT(?:ED|S)?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bCONTINUE\s+TO\b|\bIS\s+CONTINUED\b", upper))
    has_off_calendar = bool(re.search(r"\bOFF\s+CALENDAR\b|\bVACATED\b|\bDROPPED\s+FROM\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCE\s+(?:IS\s+)?(?:REQUIRED|NECESSARY)\b|\bAPPEARANCES?\s+REQUIRED\b", upper))

    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_off_calendar:
        outcome = "off_calendar"
    elif has_appearance and not negative_appearance:
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


def _split_block(block: str, title_first_line: str) -> tuple[str, str]:
    lines = block.splitlines()
    title_lines = [title_first_line.strip()]
    idx = 0
    while idx < len(lines):
        s = lines[idx].strip()
        if not s:
            idx += 1
            break
        if TENTATIVE_PREFIX_RE.match(s):
            break
        title_lines.append(s)
        idx += 1
    rest = "\n".join(lines[idx:]).strip()
    rest = TENTATIVE_PREFIX_RE.sub("", rest, count=1).strip()
    return " ".join(title_lines), rest


def _motion_from_body(body: str) -> str:
    text = body.strip()
    m = re.match(r"(?:No\s+)?Appearance\s+(?:Required|Necessary)\s*:\s*(?P<motion>[^.\n]{3,120})", text, re.IGNORECASE)
    if m:
        return " ".join(m.group("motion").split())
    return ""


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

    pages = _strip_pages(raw_pages)
    plain, offsets = _join_pages(pages)
    hearing_date = _parse_date(plain[:2500])
    if hearing_date is None:
        return []
    dept = _dept_from_header(plain[:1000], dept_hint)

    anchors = list(CASE_ANCHOR_RE.finditer(plain))
    if not anchors:
        return []

    rulings: list[Ruling] = []
    current_division = division_hint or "Civil / Probate / Family Law"
    for i, anchor in enumerate(anchors):
        region_start = anchors[i - 1].end() if i > 0 else 0
        region = plain[region_start:anchor.start()]
        for sm in SECTION_RE.finditer(region):
            current_division = _section_name(sm.group("section"))

        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        title, body = _split_block(plain[anchor.end():block_end], anchor.group("title"))
        outcome, conditional, continued_to = _classify(body)
        page_start = _page_for_offset(offsets, anchor.start())
        page_end = max(page_start, _page_for_offset(offsets, max(anchor.start(), block_end - 1)))
        case_number = anchor.group("num").upper()

        rulings.append(
            Ruling(
                ruling_id=_ruling_id(source_sha256, len(rulings) + 1, case_number),
                county=COUNTY_SLUG,
                division=current_division,
                dept=dept,
                hearing_date=hearing_date,
                ruling_index=len(rulings) + 1,
                case_number=case_number,
                case_title=" ".join(title.split()),
                motion_type=_motion_from_body(body),
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=plain[anchor.start():block_end].strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style="plumas-calendar",
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
