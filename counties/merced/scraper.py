"""Merced County tentative-rulings scraper.

Discovery
---------
Merced publishes five stable weekday PDFs. Each source can hold several
courtroom calendars.

Parsing
-------
The PDFs use calendar sections headed by courtrooms and divisions. Rulings are
anchored by either a bare case-number row or a `Case No.` row:

    22CV-03950  Dignity Health vs Premier Surgical Group Corporation
    Order Show Cause re: Status of Corporation
    Appearance required.

Some probate/family sections use:

    Case No. PR25-00012   Estate of Bennett, Bruce Allen
    Tentative Ruling: No Appearance Required: Absent objection...
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

BASE = "https://www.merced.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"www.merced.courts.ca.gov", "merced.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-rulings/" in parsed.path,
        default_division="Civil Law and Motion",
    )


# ============================================================ PARSE


_CASE_NUMBER_INNER = (
    r"\d{2}[A-Z]{2,3}-\d{4,6}(?:-[A-Z]{2,5})?"  # 22CV-03950, 22CV-03146-APP
    r"|[A-Z]{1,3}\d{2}-\d{4,6}"  # PR25-00012, LC25-00114
)
CASE_ANCHOR_RE = re.compile(
    rf"^\s*(?:Case\s+No\.?\s+)?(?P<num>{_CASE_NUMBER_INNER})\s+(?P<title>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
LONG_DATE_RE = re.compile(
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?[,]?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
COURTROOM_RE = re.compile(r"^\s*Courtroom\s+(?P<dept>\d+)\b", re.IGNORECASE | re.MULTILINE)
SECTION_RE = re.compile(
    r"^\s*(?P<section>"
    r"Civil\s+Law\s+and\s+Motion\s+Tentative\s+Rulings"
    r"|Short\s+Cause\s+Court\s+Trials"
    r"|Probate\s+Calendar"
    r"|Law\s*&\s*Motion\s+Calendar"
    r"|Case\s+Management\s+Conferences?"
    r")\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
TENTATIVE_PREFIX_RE = re.compile(r"^\s*Tentative\s+Ruling\s*:\s*", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")
NON_TITLE_START_RE = re.compile(
    r"^(?:Motion|Order\s+(?:to\s+)?Show|Case\s+Management|Default|Appearance\s+required|"
    r"No\s+Appearance|Tentative\s+Ruling|The\s+|Plaintiff|Defendant|Court\s+|Matter\s+)",
    re.IGNORECASE,
)
CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?[,]?\s+(?P<year>\d{4})",
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
    text = " ".join(raw.split())
    upper = text.upper()
    if "PROBATE" in upper:
        return "Probate"
    if "LAW & MOTION" in upper or "LAW AND MOTION" in upper:
        return "Civil Law and Motion"
    if "SHORT CAUSE" in upper:
        return "Short Cause Court Trials"
    if "CASE MANAGEMENT" in upper:
        return "Case Management Conference"
    return text.title()


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    negative_appearance = bool(re.search(r"NO\s+APPEARANCE\s+(?:IS\s+)?(?:REQUIRED|NECESSARY)", upper))
    has_denied = bool(re.search(r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANT(?:ED|S)?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bIS\s+CONTINUED\b|\bMATTER\s+CONTINUED\b", upper))
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


def _split_block(block: str, title_first_line: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return title_first_line, "", ""

    title_lines = [title_first_line.strip()]
    idx = 0
    while idx < len(lines):
        s = lines[idx]
        if TENTATIVE_PREFIX_RE.match(s):
            break
        if NON_TITLE_START_RE.match(s):
            break
        title_lines.append(s)
        idx += 1

    rest = "\n".join(lines[idx:]).strip()
    if not rest:
        return " ".join(title_lines), "", ""

    prefixed = TENTATIVE_PREFIX_RE.match(rest)
    if prefixed:
        body = rest[prefixed.end():].strip()
        return " ".join(title_lines), "", body

    rest_lines = [line.strip() for line in rest.splitlines() if line.strip()]
    if not rest_lines:
        return " ".join(title_lines), "", ""
    if TENTATIVE_PREFIX_RE.match(rest_lines[0]):
        body = TENTATIVE_PREFIX_RE.sub("", "\n".join(rest_lines), count=1).strip()
        return " ".join(title_lines), "", body
    motion = rest_lines[0]
    body = "\n".join(rest_lines[1:]).strip()
    return " ".join(title_lines), motion, body


def _ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def _split_embedded_disposition(title: str, motion: str, body: str) -> tuple[str, str, str]:
    if body:
        return title, motion, body
    disp = re.search(
        r"\b(?:DROPPED\s+from\s+calendar|CONTINUED\s+(?:to|on)|GRANTED|DENIED|"
        r"Appearance\s+required|No\s+Appearance\s+Required)\b",
        title,
        re.IGNORECASE,
    )
    if not disp:
        return title, motion, body
    before = title[: disp.start()].strip(" -–")
    motion_match = re.search(
        r"\b(?:OSC\s+re:[^,]+|Status\s+Conference|Petition\s+for[^,]+|"
        r"Case\s+Management\s+Conference|Motion\s+(?:to|for|re|in|by|of)\b.+)$",
        before,
        re.IGNORECASE,
    )
    if not motion_match:
        return title, motion, body
    body = title[disp.start():].strip()
    motion = motion or motion_match.group(0).strip()
    title = before[: motion_match.start()].strip(" -–")
    return title, motion, body


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
    hearing_date = _parse_date(plain[:4000])
    if hearing_date is None:
        return []

    anchors = [
        anchor for anchor in CASE_ANCHOR_RE.finditer(plain)
        if not re.match(r"^(?:and\s+#?|#)", anchor.group("title").strip(), re.IGNORECASE)
        and not re.match(
            r"^(?:is|are|was|were|should|shall|to)\b.*\b(?:consolidat|related|transfer)",
            anchor.group("title").strip(),
            re.IGNORECASE,
        )
    ]
    if not anchors:
        return []

    rulings: list[Ruling] = []
    current_dept = dept_hint
    current_division = division_hint or "Civil Law and Motion"
    for i, anchor in enumerate(anchors):
        region_start = anchors[i - 1].end() if i > 0 else 0
        region = plain[region_start:anchor.start()]
        for sm in SECTION_RE.finditer(region):
            current_division = _section_name(sm.group("section"))
        for dm in COURTROOM_RE.finditer(region):
            current_dept = dm.group("dept")

        block_start = anchor.end()
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        title, motion, body = _split_block(plain[block_start:block_end], anchor.group("title"))
        title, motion, body = _split_embedded_disposition(title, motion, body)
        if not body and motion:
            body = motion
            motion = ""
        outcome, conditional, continued_to = _classify(body or motion)
        page_start = _page_for_offset(offsets, anchor.start())
        page_end = max(page_start, _page_for_offset(offsets, max(anchor.start(), block_end - 1)))
        case_number = anchor.group("num").upper()

        rulings.append(
            Ruling(
                ruling_id=_ruling_id(source_sha256, len(rulings) + 1, case_number),
                county=COUNTY_SLUG,
                division=current_division,
                dept=current_dept,
                hearing_date=hearing_date,
                ruling_index=len(rulings) + 1,
                case_number=case_number,
                case_title=" ".join(title.split()),
                motion_type=" ".join(motion.split()),
                outcome=outcome,
                outcome_text=body.strip(),
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=plain[anchor.start():block_end].strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style="merced-calendar",
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
