"""Santa Clara County tentative-rulings scraper.

Discovery
---------
Santa Clara routes department-specific PDFs through stable per-dept URLs.
Dept 1 = civil law-and-motion, Dept 2/7 = probate, Dept 19/22 = complex civil.

Parsing
-------
Every page repeats the same five-line department header. Rulings start on
page 2+ using a `LINE N <CASE_NUM> <PARTY_TITLE>` anchor, often broken into
several lines by pypdf:

    LINE 1  23CV416606 Zhao  Zheng vs
    Ming Lin
    Demurrer/ Motion to Strike
    <body...>

Dept 12 uses a tabular variant where one logical row may flow as:
    LINE 1  24CV431273  Telly, et al
                          v.
                          Sanchez etl al
                          MOTION FOR SUMMARY JUDGEMENT

Both share the `LINE N` anchor with a case number immediately following.
Case-number formats observed:
    23CV416606, 24CV431273       (civil)
    24PR198048                    (probate)
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

BASE = "https://santaclara.courts.ca.gov/online-services/tentative-rulings"
DEPARTMENT_PAGE_SLUGS = {
    1: "department-1",
    2: "department-2",
    6: "department-6",
    7: "department-7",
    10: "department-10",
    12: "department-12",
    13: "department-13",
    16: "dept-16",
    19: "dept-19",
    22: "dept-22",
}
DEPARTMENTS = list(DEPARTMENT_PAGE_SLUGS)
LANDING_PAGES = [
    f"{BASE}/{slug}-tentative-rulings"
    for slug in DEPARTMENT_PAGE_SLUGS.values()
]


def _dept_hint(parsed: ParseResult, _text: str, page_url: str) -> str | None:
    m = re.search(r"dept[-_ ]?(\d+)", parsed.path, re.I)
    if not m:
        m = re.search(r"(?:department|dept)-(\d+)-", page_url, re.I)
    return m.group(1) if m else None


def _division_hint(_parsed: ParseResult, _text: str, page_url: str) -> str | None:
    if re.search(r"(?:department|dept)-(?:2|7)-", page_url, re.I):
        return "Probate"
    if re.search(r"(?:department|dept)-(?:19|22)-", page_url, re.I):
        return "Complex Civil"
    return "Civil Law and Motion"


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"santaclara.courts.ca.gov", "www.santaclara.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative-ruling/" in parsed.path,
        dept_hint=_dept_hint,
        division_hint=_division_hint,
    )


# ============================================================ PARSE


# LINE N anchor — "LINE 1  23CV416606  Zhao Zheng vs Ming Lin".
# Allow a case number to be on the same line as LINE N, or on a following
# line if pypdf split the row.
LINE_ANCHOR_RE = re.compile(
    r"^\s*LINE\s+(?P<idx>\d{1,3})\s*[:.]?\s*$"
    r"|^\s*LINE\s+(?P<idx2>\d{1,3})\s+(?P<rest>.+?)\s*$",
    re.MULTILINE,
)

# Case-number formats observed in SCC PDFs.
_CASE_NUMBER_INNER = (
    r"\d{2}[A-Z]{2,3}\d{5,8}"        # 23CV416606, 24PR198048, 24CV431273
)
CASE_NUMBER_RE = re.compile(rf"\b(?P<num>{_CASE_NUMBER_INNER})\b")

# Header bits.
HEADER_DEPT_RE = re.compile(r"^\s*Department\s+(\d+)\b", re.MULTILINE | re.IGNORECASE)
HEADER_DATE_RE = re.compile(
    r"DATE:\s*(?P<m1>\d{1,2}/\d{1,2}/\d{2,4})"
    r"|DATE:\s*(?P<m2>[A-Z][a-z]+\.?\s+\d{1,2}\s*,\s+\d{4})"
    r"|Hearing\s+date,\s*time,\s*and\s*department:\s*(?P<m4>[A-Z][a-z]+\.?\s+\d{1,2}\s*,\s+\d{4})"
    r"|\bon\s+(?P<m6>[A-Z][a-z]+\.?\s+\d{1,2}\s*,\s+\d{4})\s+at\b"
    r"|^\s*(?P<m5>[A-Z][a-z]+\.?\s+\d{1,2}\s+\d{4})\s*$"
    r"|^\s*(?P<m3>[A-Z][a-z]+\.?\s+\d{1,2}\s*,\s+\d{4})(?:\s+at\b.*)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
DIVISION_RE = re.compile(
    r"(?P<div>"
    r"PROBATE\s+LAW\s+AND\s+MOTION\s+TENTATIVE\s+RULINGS"
    r"|LAW\s+AND\s+MOTION\s+TENTATIVE\s+RULINGS"
    r"|CIVIL\s+TENTATIVE\s+RULINGS"
    r"|COMPLEX\s+CIVIL\s+TENTATIVE\s+RULINGS"
    r")",
    re.IGNORECASE,
)

# Page-number lines.
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}
_MONTHS.update({name[:3].upper(): value for name, value in list(_MONTHS.items())})

# Continued-to extractor.
CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
    r"(?:[\w:.]+\s+(?:a\.m\.|p\.m\.|AM|PM)\s+(?:on\s+)?)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE | re.DOTALL,
)


def _parse_date(text: str) -> date | None:
    for m in HEADER_DATE_RE.finditer(text):
        d_str = m.group("m1") or m.group("m2") or m.group("m3") or m.group("m4") or m.group("m5") or m.group("m6")
        if not d_str:
            continue
        d_str = d_str.strip()
        if "/" in d_str:
            parts = d_str.split("/")
            try:
                year = int(parts[2])
                if year < 100:
                    year += 2000
                return date(year, int(parts[0]), int(parts[1]))
            except ValueError:
                continue
        mm = re.match(r"([A-Z][a-z]+)\.?\s+(\d{1,2})\s*,?\s+(\d{4})", d_str, re.IGNORECASE)
        if mm:
            mo = mm.group(1).upper()
            if mo in _MONTHS:
                try:
                    return date(int(mm.group(3)), _MONTHS[mo], int(mm.group(2)))
                except ValueError:
                    continue
    return None


def _detect_division(header_text: str, hint: str | None) -> str | None:
    m = DIVISION_RE.search(header_text)
    if m:
        text = " ".join(m.group("div").upper().split())
        if "PROBATE" in text:
            return "Probate Law and Motion"
        if "COMPLEX" in text:
            return "Complex Civil"
        if "LAW AND MOTION" in text:
            return "Law and Motion"
        return text.title()
    return hint


def _detect_dept(header_text: str, hint: str | None) -> str | None:
    m = HEADER_DEPT_RE.search(header_text)
    if m:
        return m.group(1)
    return hint


def _build_header_signature(text: str) -> str:
    """First non-trivial line on page 1 that we'll use to detect repeats."""
    for line in text.splitlines():
        s = line.strip()
        if s and "SUPERIOR COURT" in s.upper():
            return s
    return ""


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
    head = "\n".join(page1_text.splitlines()[:120])
    judge = None
    jm = re.search(
        r"Honorable\s+([A-Z][A-Za-z .\-]+?)(?:,\s+Presiding|\s*$|\n)",
        head,
        re.MULTILINE,
    )
    if jm:
        judge = " ".join(jm.group(1).split())
    division = _detect_division(head, division_hint)
    style = (
        "santa-clara-probate" if division and "PROBATE" in division.upper()
        else "santa-clara-civil"
    )
    return _DocMeta(
        hearing_date=_parse_date(head),
        division=division,
        dept=_detect_dept(head, dept_hint),
        style=style,
        judge=judge,
    )


def _strip_repeating_header(pages: list[str]) -> list[str]:
    """Pages share a multi-line header. Compare first N lines across pages and
    drop the lines that repeat verbatim."""
    if len(pages) < 2:
        return pages
    page_lines = [p.splitlines() for p in pages]
    min_len = min(len(p) for p in page_lines)
    prefix_len = 0
    for i in range(min_len):
        ref = page_lines[0][i].strip()
        if all(p[i].strip() == ref for p in page_lines[1:]):
            prefix_len = i + 1
        else:
            break
    # Also detect repeating "LAW AND MOTION TENTATIVE RULINGS" + page-number lines.
    out: list[str] = []
    for i, lines in enumerate(page_lines):
        if i == 0:
            out.append("\n".join(lines))
        else:
            kept = lines[prefix_len:]
            # Drop pure-numeric and "LAW AND MOTION TENTATIVE RULINGS" lines.
            kept = [
                l for l in kept
                if not PAGE_NUMBER_RE.match(l)
                and not re.match(r"\s*(?:LAW AND MOTION|PROBATE LAW AND MOTION|COMPLEX CIVIL)\s+TENTATIVE\s+RULINGS\s*$", l, re.IGNORECASE)
            ]
            out.append("\n".join(kept))
    return out


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(
        r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b|\bMOTION\s+IS\s+OVERRULED\b"
        r"|\bDEMURRER\s+IS\s+OVERRULED\b",
        upper,
    ))
    has_granted = bool(re.search(
        r"\bGRANTED?\b|\bSUSTAINED\b|\bAPPROVED\b",
        upper,
    ))
    has_continued = bool(re.search(
        r"\bCONTINUED\s+TO\b|\bCONTINUED\s+FOR\b|\bHEARING\s+(?:IS|MUST)\s+(?:BE\s+)?CONTINUED\b"
        r"|\bMATTER\s+IS\s+CONTINUED\b",
        upper,
    ))
    has_appearance = bool(re.search(
        r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:NECESSARY|REQUIRED)\b"
        r"|\bORDERED\s+TO\s+COME\s+TO\s+THE\s+HEARING\b"
        r"|\bORDERED\s+TO\s+APPEAR\b",
        upper,
    ))
    has_off_cal = bool(re.search(r"\bOFF\s+CALENDAR\b|\bVACATED\b|\bDROPPED\s+FROM\b", upper))

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


def _select_case_matches(matches: list[re.Match[str]], plain: str) -> list[re.Match[str]]:
    """Choose the ruling block occurrence when TOC rows repeat a case number."""
    best: dict[str, tuple[int, re.Match[str]]] = {}
    doc_len = max(len(plain), 1)
    for cm in matches:
        num = cm.group("num")
        before = plain[max(0, cm.start() - 600):cm.start()]
        after = plain[cm.end():cm.end() + 800]
        line_start = plain.rfind("\n", 0, cm.start()) + 1
        line_end = plain.find("\n", cm.end())
        if line_end == -1:
            line_end = len(plain)
        current_line = plain[line_start:line_end]
        score = 0
        if re.search(r"Case\s+No\.?\s*$", before[-100:], re.IGNORECASE):
            score += 12
        if re.search(r"Case\s+Name\b", before[-400:], re.IGNORECASE):
            score += 8
        if re.search(r"Calendar\s+Line", before[-400:], re.IGNORECASE):
            score += 6
        if re.search(r"\bLINE\s+\d{1,3}\b", current_line, re.IGNORECASE):
            score += 2
        if re.search(
            r"\b(?:Before\s+the\s+court|Pursuant\s+to|Parties?\s+to\s+appear|"
            r"I\.\s+BACKGROUND|This\s+matter)\b",
            after[:700],
            re.IGNORECASE,
        ):
            score += 5
        if re.search(r"Scroll\s+down\s+to\s+Lines?", after[:350], re.IGNORECASE):
            score -= 12
        # Later occurrence wins ties; TOC entries generally precede the full ruling.
        score = score * 1_000_000 + int(cm.start() / doc_len * 999_999)
        if num not in best or score > best[num][0]:
            best[num] = (score, cm)
    return sorted((cm for _score, cm in best.values()), key=lambda m: m.start())


def _case_name_before(plain: str, case_start: int) -> str:
    segment = plain[max(0, case_start - 700):case_start]
    m = re.search(
        r"Case\s+Name:?\s+(?P<title>.+?)(?:\n\s*Case\s+No\.?:?\s*)?$",
        segment,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return ""
    title = " ".join(line.strip() for line in m.group("title").splitlines() if line.strip())
    return re.sub(r"\s+", " ", title).strip()


def _looks_like_motion_line(line: str) -> bool:
    if not line or len(line) > 220:
        return False
    if re.search(
        r"\b(?:Motion|Demurrer|Petition|Order\s+of\s+Examination|OSC|"
        r"Order\s+to\s+Show\s+Cause|Minor.?s\s+Compromise|Sanctions?)\b",
        line,
        re.IGNORECASE,
    ):
        return True
    return bool(re.match(r"^[A-Z0-9 ,/&'.\-:()]+$", line) and len(line) >= 8 and " VS " not in line.upper())


def _split_after_case(block_lines: list[str], title_hint: str) -> tuple[str, str, str]:
    title_lines: list[str] = []
    motion_type = ""
    body_start_idx: int | None = None
    if title_hint:
        for j, line in enumerate(block_lines):
            s = line.strip()
            if not s:
                continue
            if _looks_like_motion_line(s):
                motion_type = s
                body_start_idx = j + 1
            else:
                body_start_idx = j
            break
        if body_start_idx is None:
            body_start_idx = len(block_lines)
        title_hint = re.split(r"\.?\s*Scroll\s+down\s+to\s+Lines?", title_hint, flags=re.IGNORECASE)[0]
        return title_hint.strip(" ."), motion_type, "\n".join(block_lines[body_start_idx:]).strip()

    for j, line in enumerate(block_lines):
        s = line.strip()
        if not s:
            if title_lines or motion_type:
                continue
            continue
        if title_lines and _looks_like_motion_line(s):
            motion_type = s
            body_start_idx = j + 1
            break
        if title_lines and re.match(r"^(?:On|Before|Pursuant|This matter|Parties? to appear)\b", s, re.IGNORECASE):
            body_start_idx = j
            break
        title_lines.append(s)
        if len(title_lines) >= 5:
            body_start_idx = j + 1
            break

    if body_start_idx is None:
        body_start_idx = len(block_lines)
    title = re.sub(r"\s+", " ", " ".join(title_lines)).strip()
    title = re.split(r"\.?\s*Scroll\s+down\s+to\s+Lines?", title, flags=re.IGNORECASE)[0].strip(" .")
    body = "\n".join(block_lines[body_start_idx:]).strip()
    return title, motion_type, body


def _parse_formal_packet(
    plain: str,
    page_offsets: list[int],
    page_for_offset,
    meta: _DocMeta,
    source_sha256: str,
    source_url: str,
) -> list[Ruling]:
    if not re.search(r"\bCase\s+No\.?\b", plain, re.IGNORECASE):
        return []
    if re.search(r"\bCalendar\s+Line\b|\bLINE\s*#\s*CASE\s*#", plain, re.IGNORECASE):
        return []
    if not re.search(r"\babove-entitled\s+actions?\s+came\s+on\s+for\s+hearing\b", plain, re.IGNORECASE):
        return []
    cm = CASE_NUMBER_RE.search(plain)
    if not cm:
        return []
    case_number = cm.group("num")
    before = plain[max(0, cm.start() - 600):cm.start()]
    title = ""
    tm = re.search(r"In\s+the\s+Matter\s+of:\s*(?P<title>.+?)(?=\bCase\s+No\.?|\Z)", before, re.IGNORECASE | re.DOTALL)
    if tm:
        title = " ".join(line.strip() for line in tm.group("title").splitlines() if line.strip())
    if not title:
        title = _case_name_before(plain, cm.start())
    body_match = re.search(r"\bThe\s+above-entitled\s+actions?\s+came\s+on\s+for\s+hearing\b", plain, re.IGNORECASE)
    body_start = body_match.start() if body_match else cm.end()
    body = plain[body_start:].strip()
    outcome, conditional, continued_to = _classify(body)
    page_start = page_for_offset(cm.start())
    page_end = max(page_start, page_for_offset(max(cm.start(), len(plain) - 1)))
    ruling_id = hashlib.sha256(
        f"{source_sha256}:1:{case_number}".encode("utf-8")
    ).hexdigest()[:32]
    return [
        Ruling(
            ruling_id=ruling_id,
            county=COUNTY_SLUG,
            division=meta.division,
            dept=meta.dept,
            hearing_date=meta.hearing_date,
            ruling_index=1,
            case_number=case_number,
            case_title=re.sub(r"\s+", " ", title).strip(" ,"),
            motion_type="",
            outcome=outcome,
            outcome_text=body,
            conditional=conditional,
            continued_to=continued_to,
            body_text=meta.judge or "",
            full_text=plain[cm.start():].strip(),
            page_start=page_start,
            page_end=page_end,
            source_sha256=source_sha256,
            source_url=source_url,
            style=f"{meta.style}-formal",
            parser_version=PARSER_VERSION,
            ingest_ts=datetime.now(UTC),
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

    meta = _extract_doc_meta(raw_pages[0], dept_hint, division_hint)
    if meta.hearing_date is None:
        return []

    pages = _strip_repeating_header(raw_pages)
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

    formal_rows = _parse_formal_packet(plain, page_offsets, page_for_offset, meta, source_sha256, source_url)
    if formal_rows:
        return formal_rows

    # Find case-number occurrences. Each selected occurrence is one ruling.
    # TOC rows often repeat a case number before the full ruling block, so
    # choose the best occurrence for each case number rather than the first.
    case_matches: list[re.Match[str]] = list(CASE_NUMBER_RE.finditer(plain))
    if not case_matches:
        return []
    case_matches = _select_case_matches(case_matches, plain)

    rulings: list[Ruling] = []
    ruling_index_counter = 0
    for i, cm in enumerate(case_matches):
        case_number = cm.group("num")
        case_start = cm.start()
        case_end = cm.end()
        line_start = case_start

        # 1-based position within the PDF (schema contract). The court's own
        # "LINE N" labels are deliberately not used as the index: a single PDF
        # can hold multiple calendars (e.g. 9:00 and 9:01 A.M.) that each restart
        # numbering at LINE 1, plus "Scroll down to Line N" cross-references, so
        # those labels collide and aren't positional.
        ruling_index_counter += 1
        ruling_index = ruling_index_counter

        # The block runs to the next selected case number (or end of doc).
        block_end = case_matches[i + 1].start() if i + 1 < len(case_matches) else len(plain)
        block = plain[case_end:block_end]
        block_lines = block.splitlines()
        case_title, motion_type, body = _split_after_case(
            block_lines,
            _case_name_before(plain, case_start),
        )

        outcome, conditional, continued_to = _classify(body or motion_type)

        page_start = page_for_offset(line_start)
        content_end = case_end + len(plain[case_end:block_end].rstrip())
        page_end = max(page_start, page_for_offset(max(line_start, content_end - 1)))

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
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text=meta.judge or "",
                full_text=plain[line_start:block_end].strip(),
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
