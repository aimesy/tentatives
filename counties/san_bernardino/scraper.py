"""San Bernardino County tentative-rulings scraper.

Discovery
---------
San Bernardino's legacy page exposes a table of direct civil PDF links. The
department and date are embedded in filenames like `CVS24060426.pdf`.

Parsing
-------
Two observed styles are supported:

* Full memorandum packets with one case number and a `Motion:` or `Motion(s):`
  metadata block.
* Numbered department lists where each item starts with
  `13. Party v. Party, Case No. CIVSB...`.
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

BASE = "https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx"
LANDING_PAGES = [BASE]


def _dept_hint(parsed: ParseResult, _text: str, _page_url: str) -> str | None:
    m = re.search(r"CV([RS]\d{2})\d{6}\.pdf", parsed.path, re.I)
    return m.group(1).upper() if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"old.sb-court.org"},
        path_test=lambda parsed, _text: (
            "/desktopmodules/tentativerulings/tentativerulings/" in parsed.path.lower()
        ),
        default_division="Civil",
        dept_hint=_dept_hint,
    )


# ============================================================ PARSE


CASE_NUMBER_PATTERN = r"(?:CIV[A-Z]{2}\s*\d{7}|LLT(?:SB|RS)\s*\d{7})"
CASE_NUMBER_RE = re.compile(rf"\b(?P<num>{CASE_NUMBER_PATTERN})\b", re.IGNORECASE)
LIST_HEADER_RE = re.compile(
    r"^\s*(?P<idx>\d{1,3})\.\s+(?P<title>.+?),?\s+"
    rf"(?:Case\s+No\.?\s+)?(?P<num>{CASE_NUMBER_PATTERN})(?:\s*\([^)]*\))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CASE_TABLE_ITEM_RE = re.compile(r"^\s*(?P<idx>\d{1,3})\.\s*$\s*^\s*CASE\s+NUMBER\s*$", re.IGNORECASE | re.MULTILINE)
FORMAL_CASE_LINE_RE = re.compile(rf"^\s*(?P<num>{CASE_NUMBER_PATTERN})\s*$", re.IGNORECASE | re.MULTILINE)
HEADER_FOR_RE = re.compile(rf"TENTATIVE\s+RULING\s+FOR\s+(?P<num>{CASE_NUMBER_PATTERN})", re.IGNORECASE)
CASE_NUMBER_TAIL_RE = re.compile(
    rf"^(?:&\s*)?{CASE_NUMBER_PATTERN}(?:\s*,\s*(?:&\s*)?{CASE_NUMBER_PATTERN})*\s*$",
    re.IGNORECASE,
)
MOTION_FIELD_RE = re.compile(
    r"(?is)^\s*Motion(?:s|\(s\))?\s*:\s*(?P<motion>.*?)"
    r"(?=^\s*(?:Movants?|Respondents?|RELEVANT|PROCEDURAL|ANALYSIS|RULING)\b)",
    re.MULTILINE,
)
LONG_DATE_RE = re.compile(
    r"\b(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
URL_DATE_RE = re.compile(r"CV[A-Z](?P<dept>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<y>\d{2})\.pdf", re.IGNORECASE)
DEPT_RE = re.compile(r"\bDepartment\s+(?P<dept>[RS]-?\d{2}|[RS]\d{2})\b|\bDept\.?\s+(?P<dept2>[RS]-?\d{2})\b", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\s*(?:Page\s*\|\s*)?\d{1,3}\s*$|^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
LIST_DATE_LINE_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4},.*(?:Dept\.?|Department)\s+[RS]-?\d{2}\s*$", re.IGNORECASE)
RULING_SECTION_RE = re.compile(
    r"^\s*(?:TENTATIVE\s+)?RULING(?:\(S\))?:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CONTINUED_TO_RE = re.compile(
    r"(?:continued|sets?|reset)\s+(?:to|for)\s+"
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
    for m in LONG_DATE_RE.finditer(text):
        month = _MONTHS.get(m.group("month").upper())
        if not month:
            continue
        try:
            return date(int(m.group("year")), month, int(m.group("day")))
        except ValueError:
            continue
    return None


def _parse_url_date(source_url: str) -> date | None:
    m = URL_DATE_RE.search(source_url)
    if not m:
        return None
    try:
        return date(2000 + int(m.group("y")), int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None


def _dept_from(text: str, hint: str | None, source_url: str) -> str | None:
    m = DEPT_RE.search(text)
    if m:
        return (m.group("dept") or m.group("dept2")).replace("-", "").upper()
    m = URL_DATE_RE.search(source_url)
    if m:
        prefix = re.search(r"CV(?P<prefix>[RS])", source_url, re.IGNORECASE)
        if prefix:
            return f"{prefix.group('prefix').upper()}{m.group('dept')}"
    return hint


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDEN(?:IED|IES|Y)\b|\bOVERRULED\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANT(?:ED|S)?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bSETS?\s+THE\s+CASE\b|\bOSC\s+RE:\s+STATUS\b", upper))
    has_off_calendar = bool(re.search(r"\bOFF\s+CALENDAR\b|\bVACATED\b|\bMOOT\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:REQUIRED|REQUESTED|NECESSARY)\b|\bWILL\s+HEAR\s+ARGUMENT\b", upper))

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


def _ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def _normalize_case_number(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


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
    case_number = _normalize_case_number(case_number)
    return Ruling(
        ruling_id=_ruling_id(source_sha256, index, case_number),
        county=COUNTY_SLUG,
        division="Civil",
        dept=dept,
        hearing_date=hearing_date,
        ruling_index=index,
        case_number=case_number,
        case_title=" ".join(case_title.split()),
        motion_type=" ".join(motion_type.split()),
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


def _parse_list_style(
    plain: str,
    offsets: list[int],
    hearing_date: date,
    dept: str | None,
    source_sha256: str,
    source_url: str,
) -> list[Ruling]:
    headers = list(LIST_HEADER_RE.finditer(plain))
    if not headers:
        return []
    rulings: list[Ruling] = []
    for i, header in enumerate(headers):
        start = header.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(plain)
        section = plain[header.end():end]
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        motion_lines: list[str] = []
        body_start = 0
        for j, line in enumerate(lines):
            if LIST_DATE_LINE_RE.match(line):
                body_start = j + 1
                continue
            if re.match(r"^Tentative\s+Rulings?$", line, re.IGNORECASE):
                body_start = j + 1
                break
            if not motion_lines:
                motion_lines.append(line)
            else:
                motion_lines.append(line)
        body = "\n".join(lines[body_start:]).strip() if body_start else "\n".join(lines).strip()
        motion = motion_lines[0] if motion_lines else ""
        index = len(rulings) + 1
        rulings.append(
            _make_ruling(
                index=index,
                case_number=header.group("num"),
                case_title=header.group("title"),
                motion_type=motion,
                body=body,
                full_text=plain[start:end],
                start=start,
                end=end,
                offsets=offsets,
                source_sha256=source_sha256,
                source_url=source_url,
                hearing_date=hearing_date,
                dept=dept,
                style="san-bernardino-list",
            )
        )
    return rulings


def _field_lines(lines: list[str], start_label: str, end_labels: set[str]) -> list[str]:
    out: list[str] = []
    active = False
    for line in lines:
        label = line.strip().upper()
        if label == start_label.upper():
            active = True
            continue
        if active and label in {value.upper() for value in end_labels}:
            break
        if active and line.strip():
            out.append(line.strip())
    return out


def _parse_case_table_style(
    plain: str,
    offsets: list[int],
    hearing_date: date,
    dept: str | None,
    source_sha256: str,
    source_url: str,
) -> list[Ruling]:
    starts = list(CASE_TABLE_ITEM_RE.finditer(plain))
    if not starts:
        return []
    rulings: list[Ruling] = []
    for i, start_match in enumerate(starts):
        start = start_match.start()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(plain)
        section = plain[start:end]
        case_match = CASE_NUMBER_RE.search(section)
        if not case_match:
            continue
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        title = " ".join(_field_lines(lines, "CASE NAME", {"TYPE OF HEARING", "TENTATIVE RULING:"}))
        motion = " ".join(_field_lines(lines, "TYPE OF HEARING", {"TENTATIVE RULING:"}))
        body = ""
        for j, line in enumerate(lines):
            if re.match(r"^Tentative\s+Ruling:?\s*$", line, re.IGNORECASE):
                body = "\n".join(lines[j + 1:]).strip()
                break
            m = re.match(r"^Tentative\s+Ruling:\s*(.+)$", line, re.IGNORECASE)
            if m:
                body = "\n".join([m.group(1), *lines[j + 1:]]).strip()
                break
        index = len(rulings) + 1
        rulings.append(
            _make_ruling(
                index=index,
                case_number=case_match.group("num"),
                case_title=title,
                motion_type=motion,
                body=body,
                full_text=section,
                start=start,
                end=end,
                offsets=offsets,
                source_sha256=source_sha256,
                source_url=source_url,
                hearing_date=hearing_date,
                dept=dept,
                style="san-bernardino-case-table",
            )
        )
    return rulings


def _title_before_case(plain: str, case_start: int) -> str:
    before = plain[:case_start]
    chunks = re.split(r"\n\s*\n", before)
    for chunk in reversed(chunks):
        lines = [line.strip(" ,") for line in chunk.splitlines() if line.strip()]
        lines = [
            line
            for line in lines
            if not re.search(r"TENTATIVE|Department|Judge|California Rules|CourtCall|NOTICE", line, re.IGNORECASE)
        ]
        if lines:
            return " ".join(lines[-6:])
    return ""


def _title_before_offset(plain: str, offset: int) -> str:
    """Return the contiguous title block immediately above a metadata field."""
    title_lines: list[str] = []
    for line in reversed(plain[:offset].splitlines()):
        s = line.strip(" ,")
        if not s:
            if title_lines:
                break
            continue
        if re.search(
            r"TENTATIVE|Department|Judge|California Rules|CourtCall|Courtroom|"
            r"request oral argument|tentative ruling system",
            s,
            re.IGNORECASE,
        ):
            if title_lines:
                break
            continue
        title_lines.append(s)
        if len(title_lines) >= 6:
            break
    title_lines.reverse()
    return " ".join(title_lines)


def _title_after_case(plain: str, case_end: int) -> tuple[str, int]:
    title_lines: list[str] = []
    cursor = case_end
    for raw in plain[case_end:].splitlines(keepends=True):
        line_start = cursor
        cursor += len(raw)
        s = raw.strip(" ,")
        s = re.sub(r"\s*[_*=-]{5,}\s*$", "", s).strip(" ,")
        if not s:
            if title_lines:
                break
            continue
        if re.match(r"^[_*=-]{5,}$", s):
            if title_lines:
                break
            continue
        if re.search(r"^(?:TENTATIVE\s+)?RULING|Motion(?:s|\(s\))?:|Movants?:|Respondents?:", s, re.IGNORECASE):
            break
        if not title_lines and CASE_NUMBER_TAIL_RE.match(s):
            continue
        if re.search(r"California Rules|CourtCall|tentative ruling|request oral argument", s, re.IGNORECASE):
            if title_lines:
                break
            continue
        title_lines.append(s)
        if len(title_lines) >= 4:
            break
    title = " ".join(" ".join(title_lines).split())
    return title, cursor


def _motion_from_body(body: str) -> str:
    m = re.search(
        r"\bBefore\s+the\s+Court\s+(?:is|are)\s+(?P<motion>.+?)(?:\.|\n)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return ""
    motion = " ".join(m.group("motion").split())
    return motion[:220]


def _formal_case_anchors(plain: str) -> list[re.Match[str]]:
    anchors: list[re.Match[str]] = []
    for match in FORMAL_CASE_LINE_RE.finditer(plain):
        title, _cursor = _title_after_case(plain, match.end())
        if not title:
            continue
        following = plain[match.end():match.end() + 900]
        if RULING_SECTION_RE.search(following):
            anchors.append(match)
    return anchors


def _parse_formal_section(
    *,
    section: str,
    absolute_start: int,
    index: int,
    offsets: list[int],
    hearing_date: date,
    dept: str | None,
    source_sha256: str,
    source_url: str,
) -> Ruling | None:
    case_match = CASE_NUMBER_RE.search(section)
    if not case_match:
        return None
    case_number = case_match.group("num")
    motion_match = MOTION_FIELD_RE.search(section)
    motion = motion_match.group("motion").strip() if motion_match else ""
    title, _title_cursor = _title_after_case(section, case_match.end())
    if CASE_NUMBER_TAIL_RE.match(title):
        title = ""
    if not title:
        title = _title_before_case(section, case_match.start())
    ruling_matches = list(RULING_SECTION_RE.finditer(section))
    if ruling_matches:
        body = section[ruling_matches[-1].end():].strip()
    elif motion_match:
        body = section[motion_match.end():].strip()
    else:
        body = section[case_match.end():].strip()
    if not motion:
        motion = _motion_from_body(section[case_match.end():]) or _motion_from_body(body)
    return _make_ruling(
        index=index,
        case_number=case_number,
        case_title=title,
        motion_type=motion,
        body=body,
        full_text=section,
        start=absolute_start,
        end=absolute_start + len(section),
        offsets=offsets,
        source_sha256=source_sha256,
        source_url=source_url,
        hearing_date=hearing_date,
        dept=dept,
        style="san-bernardino-formal",
    )


def _parse_formal_style(
    plain: str,
    offsets: list[int],
    hearing_date: date,
    dept: str | None,
    source_sha256: str,
    source_url: str,
) -> list[Ruling]:
    anchors = _formal_case_anchors(plain)
    if len(anchors) > 1:
        rows: list[Ruling] = []
        for i, anchor in enumerate(anchors):
            start = anchor.start()
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
            row = _parse_formal_section(
                section=plain[start:end],
                absolute_start=start,
                index=len(rows) + 1,
                offsets=offsets,
                hearing_date=hearing_date,
                dept=dept,
                source_sha256=source_sha256,
                source_url=source_url,
            )
            if row:
                rows.append(row)
        if rows:
            return rows

    header_case = HEADER_FOR_RE.search(plain)
    case_match = header_case or CASE_NUMBER_RE.search(plain)
    if not case_match:
        return []
    case_number = case_match.group("num")

    motion_match = MOTION_FIELD_RE.search(plain)
    motion = motion_match.group("motion").strip() if motion_match else ""

    if header_case:
        title = _title_before_offset(plain, motion_match.start()) if motion_match else _title_before_case(plain, case_match.start())
    else:
        title, _title_cursor = _title_after_case(plain, case_match.end())
        if CASE_NUMBER_TAIL_RE.match(title):
            title = ""
        if not title:
            title = _title_before_case(plain, case_match.start())

    ruling_matches = list(RULING_SECTION_RE.finditer(plain))
    if ruling_matches:
        body_start = ruling_matches[-1].end()
        body = plain[body_start:].strip()
    elif motion_match:
        body = plain[motion_match.end():].strip()
    else:
        body = plain[case_match.end():].strip()
    if not motion:
        motion = _motion_from_body(plain[case_match.end():]) or _motion_from_body(body)

    return [
        _make_ruling(
            index=1,
            case_number=case_number,
            case_title=title,
            motion_type=motion,
            body=body,
            full_text=plain,
            start=0,
            end=len(plain),
            offsets=offsets,
            source_sha256=source_sha256,
            source_url=source_url,
            hearing_date=hearing_date,
            dept=dept,
            style="san-bernardino-formal",
        )
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
    hearing_date = _parse_url_date(source_url) or _parse_long_date(plain[:1500])
    if hearing_date is None:
        return []
    dept = _dept_from(plain[:1500], dept_hint, source_url)

    table_rows = _parse_case_table_style(plain, offsets, hearing_date, dept, source_sha256, source_url)
    if table_rows:
        return table_rows
    list_rows = _parse_list_style(plain, offsets, hearing_date, dept, source_sha256, source_url)
    if list_rows:
        return list_rows
    return _parse_formal_style(plain, offsets, hearing_date, dept, source_sha256, source_url)


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
