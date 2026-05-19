"""Placer County tentative-rulings scraper.

Placer publishes tentative-rulings PDFs at:
  placer.courts.ca.gov/sites/default/files/<YYYY-MM>/<MDDYY> Web.pdf

PDF structure is simpler than EDC or CCC — there is no separate
"TENTATIVE RULING" anchor; each ruling section is delimited entirely
by its header line:

  N. <CASE_NUMBER> <CASE_TITLE>

  <MOTION_TYPE>            (1-3 lines, then blank line)

  <DISPOSITION / BODY>     (continues until the next header)

Case-number formats: `M-CV-0085411` (limited civil), `S-CV-0049514`
(superior civil), generalised as `<LETTER>-<2-3 LETTERS>-<6-10 DIGITS>`.

Page-1 header varies between two observed layouts:
  Style 1:  PLACER COUNTY SUPERIOR COURT
            CIVIL LAW AND MOTION TENTATIVE RULINGS
            <DAY>, <MONTH DAY, YEAR>
  Style 2:  PLACER COUNTY SUPERIOR COURT
            <DAY>, CIVIL LAW AND MOTION
            DEPARTMENT N
            THE HONORABLE <NAME>
            TENTATIVE RULINGS FOR <MONTH DAY, YEAR>, AT 8:30 A.M.

Dept comes from header (Style 2) or from prose ("heard in Department NN").
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterator

import pypdf

from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION


# ============================================================ DISCOVERY


@dataclass(frozen=True)
class PdfRef:
    url: str
    filename: str
    wayback_ts: str | None = None
    dept_hint: str | None = None


def discover_live(html: str, page_url: str | None = None) -> list[PdfRef]:
    """Placer's tentative-ruling pages link to PDFs at
    placer.courts.ca.gov/sites/default/files/<YYYY-MM>/<MDDYY> Web.pdf.
    Discovery against the two department landing pages (law_motion, calendar_notes)
    not yet implemented."""
    return []


# ============================================================ PARSE


# Page-1 header marker.
HEADER_FIRST_RE = re.compile(r"PLACER\s+COUNTY\s+SUPERIOR\s+COURT", re.IGNORECASE)

# Long-form date — captures "May 1, 2026", "APRIL 30, 2026", "MAY 5, 2026" etc.
LONG_DATE_RE = re.compile(r"\b([A-Z][A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})\b")

# Department references.
HEADER_DEPT_RE = re.compile(r"^DEPARTMENT\s+(\d+)\s*$", re.MULTILINE | re.IGNORECASE)
INLINE_DEPT_RE = re.compile(r"\b[Dd]epartment\s+(\d+)\b")

# Ruling header. Case-number formats observed:
#   M-CV-0085411     limited civil
#   S-CV-0049514     superior civil
#   JCCP5336         Judicial Council Coordinated Proceedings
RULING_HEADER_RE = re.compile(
    r"^(?P<idx>\d{1,3})\.\s+"
    r"(?P<case_number>(?:[A-Z]-[A-Z]{2,3}-\d{4,10}|[A-Z]{2,5}\d{3,8}))\s+"
    r"(?P<title>.+?)\s*$",
    re.MULTILINE,
)

# Headers/footers we should drop when stripping repeating lines (these vary just by
# page number across pages, so the generic detector should catch them).
PAGE_NUMBER_LINE_RE = re.compile(r"^\s*(?:Page\s+\d+\s+of\s+\d+|\d{1,4})\s*$", re.IGNORECASE)

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
        month = m.group(1).upper()
        if month in _MONTHS:
            try:
                return date(int(m.group(3)), _MONTHS[month], int(m.group(2)))
            except ValueError:
                continue
    return None


def _detect_dept(text: str, dept_hint: str | None) -> str | None:
    m = HEADER_DEPT_RE.search(text)
    if m:
        return m.group(1)
    m = INLINE_DEPT_RE.search(text)
    if m:
        return m.group(1)
    return dept_hint


def _detect_division(text: str) -> str | None:
    upper = text.upper()
    if "CIVIL LAW AND MOTION" in upper or "CIVIL LAW & MOTION" in upper:
        return "Civil Law and Motion"
    if "PROBATE" in upper:
        return "Probate"
    if "FAMILY LAW" in upper:
        return "Family Law"
    if "LAW AND MOTION" in upper or "LAW & MOTION" in upper:
        return "Law and Motion"
    return None


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    dept: str | None
    division: str | None


def _extract_doc_meta(text: str, dept_hint: str | None) -> _DocMeta:
    head = "\n".join(text.splitlines()[:25])
    if not HEADER_FIRST_RE.search(head):
        return _DocMeta(None, dept_hint, None)
    return _DocMeta(
        hearing_date=_parse_long_date(head),
        dept=_detect_dept(text, dept_hint),
        division=_detect_division(head),
    )


def _strip_repeating_lines(pages: list[list[str]]) -> tuple[int, int]:
    """Detect repeating prefix/suffix lines across pages, ignoring page numbers."""
    if len(pages) < 2:
        return 0, 0

    def equiv(a: str, b: str) -> bool:
        if PAGE_NUMBER_LINE_RE.match(a) and PAGE_NUMBER_LINE_RE.match(b):
            return True
        return a.strip() == b.strip()

    min_len = min(len(p) for p in pages)
    if min_len == 0:
        return 0, 0

    # Prefix - skip up to the first ruling-header. Don't strip past it.
    prefix_len = 0
    for i in range(min_len):
        ref = pages[0][i]
        if RULING_HEADER_RE.match(ref):
            break
        if all(equiv(p[i], ref) for p in pages[1:]):
            prefix_len = i + 1
        else:
            break

    suffix_len = 0
    for i in range(1, min_len - prefix_len + 1):
        ref = pages[0][-i]
        if all(equiv(p[-i], ref) for p in pages[1:]):
            suffix_len = i
        else:
            break

    return prefix_len, suffix_len


def _strip_page_artifacts(page_texts: list[str]) -> list[str]:
    page_lines = [t.splitlines() for t in page_texts]
    prefix_len, suffix_len = _strip_repeating_lines(page_lines)
    out: list[str] = []
    for i, lines in enumerate(page_lines):
        if i == 0:
            # Always keep page 1 — it holds the doc header. We strip the header
            # ourselves by skipping forward to the first ruling.
            out.append("\n".join(lines))
        else:
            end = len(lines) - suffix_len if suffix_len else len(lines)
            out.append("\n".join(lines[prefix_len:end]))
    # Drop any remaining lines that are pure page numbers or "Page N of M".
    out = [
        "\n".join(l for l in page.splitlines() if not PAGE_NUMBER_LINE_RE.match(l))
        for page in out
    ]
    return out


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDENIED\b|\bDENIES\b|\bDISMISSED?\b", upper))
    has_granted = bool(re.search(r"\bGRANTED?\b|\bSUSTAINED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED TO\b|\bHEARING (?:IS )?CONTINUED\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCE\s+(?:OF|REQUIRED|IS REQUIRED)\b|\bAPPEARANCES?\s+ARE\s+REQUIRED\b", upper))
    has_off_cal = bool(re.search(r"\bOFF\s+CALENDAR\b|\bVACATED\b|\bDROPPED\s+FROM\b", upper))

    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_appearance:
        outcome = "appearance_required"
    elif has_off_cal:
        outcome = "off_calendar"
    else:
        outcome = "other"

    continued_to: date | None = None
    if has_continued:
        m = re.search(
            r"CONTINUED\s+TO\s+(?:[\w:.]+\s+(?:a\.m\.|p\.m\.|AM|PM)\s+on\s+)?"
            r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
            text, re.IGNORECASE,
        )
        if m:
            month = m.group("month").capitalize()
            mi = _MONTHS.get(month.upper())
            if mi:
                try:
                    continued_to = date(int(m.group("year")), mi, int(m.group("day")))
                except ValueError:
                    pass

    return outcome, conditional, continued_to


def _split_motion_and_body(text: str) -> tuple[str, str]:
    """Given text after the ruling-header line, identify the motion-type line(s)
    (everything up to the first blank-line gap) and the body (the rest)."""
    lines = text.splitlines()
    # Skip leading blanks.
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    motion_lines: list[str] = []
    while i < len(lines) and lines[i].strip():
        motion_lines.append(lines[i].strip())
        i += 1
    # Skip blanks before body.
    while i < len(lines) and not lines[i].strip():
        i += 1
    body = "\n".join(lines[i:]).strip()
    return " ".join(motion_lines).strip(), body


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
) -> list[Ruling]:
    if source_sha256 is None:
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    raw_pages = [page.extract_text() or "" for page in reader.pages]
    if not raw_pages:
        return []

    meta = _extract_doc_meta(raw_pages[0], dept_hint)
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

    headers = list(RULING_HEADER_RE.finditer(plain))
    if not headers:
        return []

    rulings: list[Ruling] = []
    for i, hm in enumerate(headers):
        idx = int(hm.group("idx"))
        case_number = hm.group("case_number")
        case_title = hm.group("title").strip()

        start = hm.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(plain)
        section_text = plain[start:end]
        # everything after the header line
        after_header = section_text[hm.end() - hm.start():]
        motion_type, body = _split_motion_and_body(after_header)
        # Use body for outcome classification (the disposition is the body).
        outcome, conditional, continued_to = _classify(body or motion_type)

        # If the ruling lacks a separate dept hint, scan its own body for one.
        local_dept = meta.dept or _detect_dept(section_text, dept_hint)

        content_end = start + len(section_text.rstrip())
        page_start = page_for_offset(start)
        page_end = max(page_start, page_for_offset(max(start, content_end - 1)))

        ruling_id = hashlib.sha256(
            f"{source_sha256}:{idx}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=meta.division,
                dept=local_dept,
                hearing_date=meta.hearing_date,
                ruling_index=idx,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=section_text.strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style="placer-civil-law-motion",
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.utcnow(),
            )
        )

    return rulings


def parse_file(path: str, source_url: str | None = None, dept_hint: str | None = None) -> list[Ruling]:
    with open(path, "rb") as f:
        data = f.read()
    if source_url is None:
        source_url = f"file://{path}"
    return parse(data, source_url=source_url, dept_hint=dept_hint)
