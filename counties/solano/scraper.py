"""Solano County tentative-rulings scraper.

Discovery
---------
Solano publishes a small set of department-specific PDFs at stable URLs
(`dept_3.pdf`, `dept_7.pdf`, ...). The page lists each department; we pick up
PDFs whose filenames match the known set and infer dept from filename.

Parsing
-------
Two PDF styles share a common ruling shape:

  Style A (civil law-and-motion, depts 3, 7, 8):
    Page-1 header:
        DEPARTMENT <WORD>
        JUDGE <NAME>
        <PHONE>
        TENTATIVE RULINGS SCHEDULED FOR
        <DAY-OF-WEEK>, <MONTH DAY, YEAR>

  Style B (probate dept 5 = misc_dept, dept 22):
    Page-1 header:
        DEPARTMENT <WORD>
        [HONORABLE <NAME>]
        <PHONE>
        TENTATIVE RULINGS AND PROBATE PREGRANTS
        CALENDAR DATE: <MONTH DAY, YEAR>

Both use the same per-ruling layout:
    <CASE_TITLE>            (one or more lines, often party names)
    Case No. <CASE_NUMBER>
    <MOTION_TYPE>           (one line)
    TENTATIVE RULING        (anchor; no colon)
    <disposition body>

Case-number formats observed: CU24-08708, CU25-09269, CU26-00205, CL25-11400,
and lowercase variants like cu23-04949.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import ParseResult

import pypdf

from counties.static_pdf import discover_static_pdfs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

BASE = "https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings"
LANDING_PAGES = [BASE]

_WORDS = {
    "three": "3",
    "seven": "7",
    "eight": "8",
    "twenty-two": "22",
}


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    m = re.search(r"dept_(\d+)", parsed.path, re.I)
    if m:
        return m.group(1)
    lower = text.lower()
    for word, number in _WORDS.items():
        if word in lower:
            return number
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    allowed_names = {"dept_3.pdf", "dept_7.pdf", "dept_8.pdf", "dept_22.pdf", "misc_dept.pdf"}
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"solano.courts.ca.gov", "www.solano.courts.ca.gov"},
        path_test=lambda parsed, _text: parsed.path.rsplit("/", 1)[-1].lower() in allowed_names,
        default_division="Civil / Probate",
        dept_hint=_dept_hint,
    )


# ============================================================ PARSE


# Case-number formats: CU24-08708, CL25-11400, PR24-00307.
# Civil depts use "Case No. <NUMBER>"; probate depts put the case number on its
# own line without a prefix.
_CASE_NUMBER_INNER = r"[A-Z]{1,3}\d{2}-\d{4,6}|[A-Z]{2,4}\d{5,8}"
CASE_NUMBER_RE = re.compile(
    rf"\b(?:Case\s+No\.?\s*)?(?P<num>{_CASE_NUMBER_INNER})\b",
    re.IGNORECASE,
)
# Case number alone on its own line (no Case No. prefix).
CASE_NUMBER_LINE_RE = re.compile(
    rf"^\s*(?:Case\s+No\.?\s*)?(?P<num>{_CASE_NUMBER_INNER})\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# "TENTATIVE RULING" / "PREGRANT ORDER" anchors. Both signal the disposition
# block. Probate (dept 22, misc_dept) uses PREGRANT ORDER for pre-approved
# matters where no objection has been filed.
TENTATIVE_RULING_ANCHOR_RE = re.compile(
    r"^\s*(?:TENTATIVE\s+RULING|PREGRANT\s+ORDER)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Header bits.
HEADER_DEPT_WORD_RE = re.compile(
    r"DEPARTMENT\s+([A-Z]+(?:[- ][A-Z]+)?)\s*$",
    re.MULTILINE,
)
HEADER_DEPT_NUM_RE = re.compile(r"DEPARTMENT\s+(\d+)\s*$", re.MULTILINE)
LONG_DATE_RE = re.compile(
    r"(?:(?:Mon|Tues|Wed|Thurs|Fri|Satur|Sun)day,\s+)?"
    r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)
JUDGE_RE = re.compile(
    r"(?:JUDGE|HONORABLE)\s+(?P<name>[A-Z][A-Za-z .\-]+?)\s*$",
    re.MULTILINE,
)

# Page-number lines.
PAGE_NUMBER_RE = re.compile(r"^\s*Page\s+\d+\s*$", re.IGNORECASE)

# Continued-to extractor.
CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

_DEPT_WORDS: dict[str, str] = {
    "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5",
    "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9", "TEN": "10",
    "ELEVEN": "11", "TWELVE": "12", "THIRTEEN": "13", "FOURTEEN": "14",
    "FIFTEEN": "15", "SIXTEEN": "16", "SEVENTEEN": "17", "EIGHTEEN": "18",
    "NINETEEN": "19", "TWENTY": "20", "TWENTY-ONE": "21", "TWENTY-TWO": "22",
    "TWENTY-THREE": "23", "TWENTY-FOUR": "24", "TWENTY-FIVE": "25",
}

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}


def _parse_long_date(text: str) -> date | None:
    for m in LONG_DATE_RE.finditer(text):
        mo = m.group(1).upper()
        if mo in _MONTHS:
            try:
                return date(int(m.group(3)), _MONTHS[mo], int(m.group(2)))
            except ValueError:
                continue
    return None


def _detect_dept_from_header(header_text: str) -> str | None:
    m = HEADER_DEPT_NUM_RE.search(header_text)
    if m:
        return m.group(1)
    m = HEADER_DEPT_WORD_RE.search(header_text)
    if m:
        return _DEPT_WORDS.get(m.group(1).upper())
    return None


def _detect_division(header_text: str) -> str | None:
    upper = header_text.upper()
    if "PROBATE" in upper:
        return "Probate / Civil"
    return "Civil"


def _detect_style(header_text: str) -> str:
    upper = header_text.upper()
    if "PROBATE PREGRANTS" in upper:
        return "solano-probate"
    return "solano-civil"


def _detect_judge(header_text: str) -> str | None:
    m = JUDGE_RE.search(header_text)
    return " ".join(m.group("name").split()) if m else None


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    division: str | None
    dept: str | None
    style: str
    judge: str | None


def _extract_doc_meta(
    page1_text: str, dept_hint: str | None, division_hint: str | None
) -> _DocMeta:
    head = "\n".join(page1_text.splitlines()[:25])
    return _DocMeta(
        hearing_date=_parse_long_date(head),
        division=_detect_division(head) or division_hint,
        dept=_detect_dept_from_header(head) or dept_hint,
        style=_detect_style(head),
        judge=_detect_judge(head),
    )


def _strip_page_artifacts(page_texts: list[str]) -> list[str]:
    out: list[str] = []
    for t in page_texts:
        lines = [l for l in t.splitlines() if not PAGE_NUMBER_RE.match(l)]
        out.append("\n".join(lines))
    return out


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    # OVERRULED is ambiguous on its own (typically rejects an objection, not a
    # motion). We only count it as denied if it appears next to "MOTION".
    has_denied = bool(re.search(
        r"\bDEN(?:IED|IES)\b|\bDISMISS(?:ED|ES)?\b"
        r"|\bMOTION\s+(?:IS\s+)?OVERRULED\b",
        upper,
    ))
    has_granted = bool(re.search(r"\bGRANTED?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(
        r"\b(?:IS\s+)?CONTINUED\s+TO\b|\bCONTINUES\s+THE\b|\bCOURT\s+CONTINUES\b",
        upper,
    ))
    has_appearance = bool(re.search(
        r"\bPARTIES\s+(?:AND\s+COUNSEL\s+)?(?:ARE\s+)?TO\s+APPEAR\b"
        r"|\bAPPEARANCES?\s+(?:ARE\s+)?REQUIRED\b"
        r"|\bAPPEAR\s+FOR\s+HEARING\b",
        upper,
    ))
    has_off_cal = bool(re.search(r"\bOFF\s+CALENDAR\b|\bDROPPED\s+FROM\b|\bVACATED\b", upper))

    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_off_cal:
        outcome = "off_calendar"
    elif has_appearance:
        outcome = "appearance_required"
    else:
        outcome = "other"

    continued_to: date | None = None
    if has_continued:
        m = CONTINUED_TO_RE.search(text)
        if m:
            mo = m.group("month").upper()
            mi = _MONTHS.get(mo)
            if mi:
                try:
                    continued_to = date(int(m.group("year")), mi, int(m.group("day")))
                except ValueError:
                    pass

    return outcome, conditional, continued_to


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

    meta = _extract_doc_meta(raw_pages[0], dept_hint, division_hint)
    if meta.hearing_date is None:
        return []

    pages = _strip_page_artifacts(raw_pages)
    joined_parts: list[str] = []
    page_offsets: list[int] = []
    cursor = 0
    SEP = "\n\n"
    for p in pages:
        page_offsets.append(cursor)
        joined_parts.append(p)
        cursor += len(p) + len(SEP)
    plain = SEP.join(joined_parts)

    def page_for_offset(offset: int) -> int:
        page = 1
        for i, start in enumerate(page_offsets):
            if start <= offset:
                page = i + 1
            else:
                break
        return page

    anchors = list(TENTATIVE_RULING_ANCHOR_RE.finditer(plain))
    if not anchors:
        return []

    rulings: list[Ruling] = []
    ruling_index = 0
    for i, anchor in enumerate(anchors):
        # Region above this anchor to find the most recent Case No.
        region_start = anchors[i - 1].end() if i > 0 else 0
        region_end = anchor.start()
        region = plain[region_start:region_end]

        cn_match = None
        for cm in CASE_NUMBER_RE.finditer(region):
            cn_match = cm
        if cn_match is None:
            continue
        case_number = cn_match.group("num").upper()

        # Title: lines above the Case No. line within this region.
        cn_line_start = region.rfind("\n", 0, cn_match.start()) + 1
        # Find the previous blank line (or start of region) — title is the
        # contiguous non-blank lines immediately preceding the Case No. line.
        before = region[:cn_line_start]
        title_lines: list[str] = []
        for line in reversed(before.splitlines()):
            if not line.strip():
                if title_lines:
                    break
                continue
            # Stop if we've hit a previous TENTATIVE RULING block.
            if "TENTATIVE RULING" in line.upper():
                break
            title_lines.append(line.strip())
        title_lines.reverse()
        case_title = " ".join(" ".join(title_lines).split())

        # Motion type: lines between Case No. line and the anchor.
        cn_line_end = region.find("\n", cn_match.end())
        if cn_line_end == -1:
            cn_line_end = len(region)
        motion_lines: list[str] = []
        for line in region[cn_line_end:].splitlines():
            if not line.strip():
                if motion_lines:
                    break
                continue
            motion_lines.append(line.strip())
        motion_type = " ".join(" ".join(motion_lines).split())

        # Disposition: from end of anchor to start of next ruling's title block.
        disposition_start = anchor.end()
        if i + 1 < len(anchors):
            next_region = plain[disposition_start:anchors[i + 1].start()]
            next_case_iter = list(CASE_NUMBER_RE.finditer(next_region))
            if next_case_iter:
                # Cut at the start of the line containing the next case number's
                # title block - find the blank line preceding it.
                next_case = next_case_iter[0]
                # Walk back from next_case.start() to find a blank-line boundary.
                idx = next_case.start()
                # Find the line beginning, then walk back through non-blank lines.
                while idx > 0:
                    prev_newline = next_region.rfind("\n", 0, idx - 1)
                    if prev_newline == -1:
                        idx = 0
                        break
                    line_before = next_region[prev_newline + 1:idx - 1]
                    if not line_before.strip():
                        idx = prev_newline + 1
                        break
                    idx = prev_newline + 1
                disposition_end = disposition_start + idx
            else:
                disposition_end = anchors[i + 1].start()
        else:
            disposition_end = len(plain)

        disposition_text = plain[disposition_start:disposition_end].strip()
        outcome, conditional, continued_to = _classify(disposition_text)

        # The header for the ruling starts at the case-title block.
        header_start = region_start + cn_line_start
        if title_lines:
            # Recompute header_start as the start of the first title line.
            # Step back through title lines to find true start.
            t_idx = cn_line_start
            for _ in title_lines:
                prev_newline = region.rfind("\n", 0, t_idx - 1)
                if prev_newline == -1:
                    t_idx = 0
                    break
                t_idx = prev_newline + 1
            header_start = region_start + t_idx

        page_start = page_for_offset(header_start)
        trimmed_end = disposition_start + len(plain[disposition_start:disposition_end].rstrip())
        page_end = max(page_start, page_for_offset(max(header_start, trimmed_end - 1)))

        ruling_index += 1
        ruling_id = hashlib.sha256(
            f"{source_sha256}:{ruling_index}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=meta.division,
                dept=meta.dept,
                hearing_date=meta.hearing_date,
                ruling_index=ruling_index,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=disposition_text,
                conditional=conditional,
                continued_to=continued_to,
                body_text=meta.judge or "",
                judge=meta.judge,
                full_text=plain[header_start:disposition_end].strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=meta.style,
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
