"""El Dorado County tentative-rulings scraper.

The court publishes tentative rulings in at least four different PDF styles,
varying by department and calendar type:

  Style A: "Probate Tentative Rulings" (dept 9 probate)
           Header includes 'Dept. N' on its own line.
           Ruling header: "1. <CASE_NUMBER> <CASE_TITLE>"
  Style B: "LAW AND MOTION CALENDAR" (dept 4 civil)
           No dept in header. Has '– N –' page footer, footnotes, '/ / /' marks.
           Ruling header: "1. <CASE_TITLE>, <CASE_NUMBER>"
  Style C: "PROBATE CALENDAR" (dept 4 probate)
           No dept in header. '– N –' page footer. Often short rulings.
           Ruling header: "1. <CASE_TITLE>, <CASE_NUMBER>"
  Style D: "LAW & MOTION TENTATIVE RULINGS" (dept 12)
           Multi-line header includes 'DEPARTMENT 12'.
           Ruling header: "1. <CASE_TITLE>      <CASE_NUMBER>" (whitespace-separated)

Rather than detect+dispatch by style, the parser is style-agnostic:

  1. Strip repeating page headers/footers (detected dynamically across pages).
  2. Find all "TENTATIVE RULING #N:" anchors — universal across styles.
  3. For each anchor, scan backward for the ruling's case header line
     (matches "^N. ... <CASE_NUMBER> ..." on a single line where N is the index
     of the disposition anchor that follows).
  4. Body = text between case header and disposition anchor.
  5. Disposition = text from anchor to (next anchor's case header) or end.

Metadata (date, division, dept) comes from page-1 header, with optional
caller-supplied dept_hint as fallback when the header doesn't include it.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urljoin

import pypdf

from counties.common import PdfRef
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION


# ============================================================ DISCOVERY


PDF_HREF_RE = re.compile(
    r'href="(/system/files/[^"]+\.pdf)"',
    re.IGNORECASE,
)
DEPT_PAGE_RE = re.compile(
    r'href="(/online-services/tentative-rulings/tentative-rulings-dept-\d+)"',
    re.IGNORECASE,
)
TENTATIVE_PDF_RE = re.compile(
    r"/system/files/(tentative-rulings?|tentative-ruling)/",
    re.IGNORECASE,
)
BASE = "https://www.eldorado.courts.ca.gov"

# Per-dept landing pages the scheduled backfill polls. EDC publishes 12
# numbered departments at predictable URLs; the index page links to all of
# them but listing them explicitly here lets the daily harvest hit each one
# in parallel without an extra round-trip discovery step.
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings/tentative-rulings-dept-{n}"
    for n in range(1, 13)
]


def _dept_from_landing_url(url: str) -> str | None:
    m = re.search(r"tentative-rulings-dept-(\d+)", url)
    return m.group(1) if m else None


def _dept_from_pdf_filename(url: str) -> str | None:
    """Pull dept from EDC PDF filenames like '.../tr-d-09-2026-05-18.pdf'.

    Captures with no landing page (Wayback, direct PDF) lose the
    `_dept_from_landing_url` hint, but the dept is often baked into the
    filename itself for the published civil tentative rulings.
    """
    m = re.search(r"/tr-d-0*(\d{1,3})-", url)
    return m.group(1) if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    """Extract PDF links from a dept landing page's HTML.

    If `page_url` is given and looks like a per-dept landing page, the dept is
    encoded into each returned PdfRef so callers can pass it to parse().
    """
    dept_hint = _dept_from_landing_url(page_url or "")
    seen: set[str] = set()
    refs: list[PdfRef] = []
    for m in PDF_HREF_RE.finditer(html):
        path = m.group(1)
        # Only keep tentative-ruling PDFs, not the assorted PDFs courts also link.
        if not TENTATIVE_PDF_RE.search(path):
            continue
        url = urljoin(base_url + "/", path.lstrip("/"))
        if url in seen:
            continue
        seen.add(url)
        refs.append(
            PdfRef(
                url=url,
                filename=path.rsplit("/", 1)[-1],
                dept_hint=dept_hint,
            )
        )
    return refs


def discover_dept_pages(html: str, base_url: str = BASE) -> list[str]:
    """From any EDC tentative-rulings page, list URLs of all dept landing pages."""
    seen: set[str] = set()
    urls: list[str] = []
    for m in DEPT_PAGE_RE.finditer(html):
        path = m.group(1)
        url = urljoin(base_url + "/", path.lstrip("/"))
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return sorted(urls)


# ============================================================ PARSE


# A case number is alphanumeric, has at least 2 letters and at least 3 digits.
# Covers all observed formats:
#   25PR0206, 26PR0099, 24CV1535      (modern: <YY><LL><####>)
#   PP20200121, SP20140014            (legacy: <LL><YYYY><####>)
#   SC20210148, SFL20210053           (legacy with 2-3 letter prefix)
#   24FL0473, 23FL0933                (modern Family Law)
CASE_NUMBER_RE = re.compile(
    r"\b((?:\d{2}[A-Z]{2,4}\d{3,8}|[A-Z]{2,4}(?:19|20)\d{6}|[A-Z]{2,4}\d{6,8}))\b"
)

# Disposition anchor — universal across styles. "TENTATIVE RULING" optionally
# followed by space or #, then index, then colon. e.g.:
#   TENTATIVE RULING #1:
#   TENTATIVE RULING # 1:
#   TENTATIVE RULING #1:  (with trailing whitespace)
TENTATIVE_RULING_ANCHOR_RE = re.compile(
    r"TENTATIVE\s+RULING\s*#\s*(\d{1,3})\s*:",
    re.IGNORECASE,
)

# Ruling header line: "N. ... <CASE_NUMBER> ..." — must contain a case number on
# the same line to distinguish from numbered sub-sections inside a ruling body.
RULING_HEADER_LINE_RE = re.compile(
    r"^(?P<idx>\d{1,3})\.\s+(?P<rest>.*?"
    r"\b(?:\d{2}[A-Z]{2,4}\d{3,8}|[A-Z]{2,4}(?:19|20)\d{6}|[A-Z]{2,4}\d{6,8})\b"
    r".*?)\s*$",
    re.MULTILINE,
)

# Date in long form: "MAY 18, 2026" or "May 18, 2026".
LONG_DATE_RE = re.compile(
    r"\b([A-Z][A-Za-z]+)\s+(\d(?:\s*\d)?),\s+(\d(?:\s*\d){3})\b"
)

# Continuation marker — lines of just "/ / /" or "///".
CONTINUATION_LINE_RE = re.compile(r"^\s*/\s*/\s*/\s*$")

# Common boilerplate strings appended to dispositions. Stripped from outcome_text
# but recorded so callers can see what was removed if needed.
BOILERPLATE_PATTERNS = [
    re.compile(
        r"\s*IF A PARTY OR PARTIES WISH TO APPEAR REMOTELY,?\s+"
        r"INSTRUCTIONS FOR REMOTE\s+APPEARANCES CAN BE FOUND ON THE COURT[’']S\s+WEBSITE\.?\s*",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\s*NO HEARING ON THIS MATTER WILL BE HELD.*?(?=$|\n\s*\n)",
        re.IGNORECASE | re.DOTALL,
    ),
]

# "CONTINUED TO MONDAY, JULY 6, 2026", "HEARING CONTINUED TO ...",
# "CONTINUES THE MATTER TO ...", and time-prefixed "... TO 9:00 A.M. JULY 6, 2026".
CONTINUED_TO_RE = re.compile(
    r"CONTINUE[SD]?(?:\s+THE\s+MATTER)?\s+TO\s+"
    r"(?:[\w:.]+\s+(?:a\.m\.|p\.m\.|AM|PM)\s+(?:on\s+)?)?"  # optional time
    r"(?:[A-Z]+,?\s+)?"                                      # optional weekday
    r"(?P<month>[A-Z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}


def _parse_long_date(s: str) -> date | None:
    m = LONG_DATE_RE.search(s)
    if not m:
        return None
    month = m.group(1).upper()
    if month not in _MONTHS:
        return None
    day = int(re.sub(r"\s+", "", m.group(2)))
    year = int(re.sub(r"\s+", "", m.group(3)))
    return date(year, _MONTHS[month], day)


def _detect_division(header_text: str) -> str | None:
    """Look at the first few lines of page-1 to identify division."""
    upper = re.sub(r"\s+", " ", header_text.upper())
    if "PROBATE" in upper:
        return "Probate"
    if "LAW AND MOTION" in upper or "LAW & MOTION" in upper or "LAW AMP; MOTION" in upper:
        return "Law and Motion"
    if "FAMILY" in upper:
        return "Family Law"
    if "CIVIL" in upper:
        return "Civil"
    if "CRIMINAL" in upper:
        return "Criminal"
    return None


def _detect_dept_in_header(header_text: str) -> str | None:
    """Look for 'Dept. N' or 'DEPARTMENT N' in the first few lines of page-1."""
    m = re.search(r"(?:Dept\.|DEPARTMENT)\s+(\d{1,3})\b", header_text)
    return m.group(1) if m else None


def _detect_style(header_text: str) -> str:
    """Tag the style based on header characteristics, for debugging/audit."""
    upper = re.sub(r"\s+", " ", header_text.upper())
    if "PROBATE TENTATIVE RULINGS" in upper:
        return "probate-dept-header"
    if "LAW AND MOTION CALENDAR" in upper:
        return "lawandmotion-calendar"
    if "PROBATE CALENDAR" in upper:
        return "probate-calendar"
    if "LAW & MOTION TENTATIVE RULINGS" in upper or "LAW AMP; MOTION" in upper:
        return "lawandmotion-tentative-rulings"
    return "unknown"


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    division: str | None
    dept: str | None
    style: str


@dataclass(frozen=True)
class _CaseHeaderMatch:
    start: int
    end: int
    rest: str


def _normalize_date_text(s: str) -> str:
    """Smooth PDF extractor line splits inside dates."""
    normalized = re.sub(r"\s+", " ", s)
    normalized = re.sub(r"\s+,", ",", normalized)
    return normalized


def _extract_doc_meta(page1_text: str, dept_hint: str | None) -> _DocMeta:
    """Pull hearing date, division, dept from the first few lines of page 1."""
    head = "\n".join(page1_text.splitlines()[:20])
    style = _detect_style(head)
    # Style B (LAW AND MOTION CALENDAR) and Style C (PROBATE CALENDAR) never
    # print the dept in the header — by court convention they're Dept 4.
    style_default_dept = {
        "lawandmotion-calendar": "4",
        "probate-calendar": "4",
    }.get(style)
    return _DocMeta(
        hearing_date=_parse_long_date(_normalize_date_text(head)),
        division=_detect_division(head),
        dept=_detect_dept_in_header(head) or dept_hint or style_default_dept,
        style=style,
    )


def _line_looks_like_page_number(line: str) -> bool:
    """True for '1', '– 1 –', '- 1 -', '\\ufeff1 ' etc."""
    s = line.strip()
    if not s:
        return False
    s = s.replace("–", "-").replace("—", "-")
    s = s.strip(" -\t")
    return s.isdigit()


def _find_repeating_prefix_suffix(pages: list[list[str]]) -> tuple[int, int]:
    """Find how many lines at top and bottom of each page are 'header'/'footer'.

    A line is part of the header if it (or a page-number lookalike) appears at
    the same position on every page. Same for footer.
    """
    if len(pages) < 2:
        return 0, 0

    def equiv(a: str, b: str) -> bool:
        if _line_looks_like_page_number(a) and _line_looks_like_page_number(b):
            return True
        return a.strip() == b.strip()

    min_len = min(len(p) for p in pages)
    if min_len == 0:
        return 0, 0

    # Prefix
    prefix_len = 0
    for i in range(min_len):
        ref = pages[0][i]
        if all(equiv(p[i], ref) for p in pages[1:]):
            prefix_len = i + 1
        else:
            break

    # Suffix - independent count from the bottom
    suffix_len = 0
    for i in range(1, min_len - prefix_len + 1):
        ref = pages[0][-i]
        if all(equiv(p[-i], ref) for p in pages[1:]):
            suffix_len = i
        else:
            break

    return prefix_len, suffix_len


def _strip_headers_and_footers(page_texts: list[str]) -> list[str]:
    """Strip the auto-detected repeating header/footer lines from each page."""
    page_lines = [t.splitlines() for t in page_texts]
    prefix_len, suffix_len = _find_repeating_prefix_suffix(page_lines)
    out: list[str] = []
    for lines in page_lines:
        end = len(lines) - suffix_len if suffix_len else len(lines)
        out.append("\n".join(lines[prefix_len:end]))
    return out


def _strip_continuation_marks(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines()
        if not CONTINUATION_LINE_RE.match(line)
    )


def _line_offsets(text: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    cursor = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        out.append((cursor, cursor + len(line), line))
        cursor += len(raw_line)
    if text and not text.endswith(("\n", "\r")) and not out:
        out.append((0, len(text), text))
    return out


def _looks_like_case_header_fragment(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if CASE_NUMBER_RE.fullmatch(s.strip(", ")):
        return True
    if s == ",":
        return True
    if re.match(r"^\d{1,3}\.\d", s) or re.match(r"^\d{1,3}\.\)", s):
        return False
    if re.match(r"^(?:LAW AND MOTION|LAW & MOTION|PROBATE|CALENDAR|DEPARTMENT)\b", s, re.IGNORECASE):
        return False
    if re.search(r"\bV\.\s+\S", s, re.IGNORECASE):
        return True
    if s.upper() == s and re.search(r"[A-Z]", s):
        return True
    if _looks_like_narrative(s):
        return False
    return True


def _find_case_header(region: str, anchor_idx: int) -> _CaseHeaderMatch | None:
    """Find this anchor's source-backed case header in the preceding text.

    The primary parser handles the common single-line shape. This fallback only
    fires for PDFs whose extractor splits "N.", title fragments, and case number
    across separate lines.
    """
    matches: list[_CaseHeaderMatch] = []
    for hm in RULING_HEADER_LINE_RE.finditer(region):
        if int(hm.group("idx")) == anchor_idx:
            matches.append(
                _CaseHeaderMatch(
                    start=hm.start(),
                    end=hm.end(),
                    rest=hm.group("rest"),
                )
            )
    if matches:
        return matches[-1]

    lines = _line_offsets(region)
    for line_no, (start, end, line) in enumerate(lines):
        m = re.match(r"^\s*(?P<idx>\d{1,3})\.\s*(?P<rest>.*)$", line)
        if not m or int(m.group("idx")) != anchor_idx:
            continue

        rest = m.group("rest").strip()
        if rest and not _looks_like_case_header_fragment(rest):
            continue

        parts: list[str] = [rest] if rest else []
        header_end = end
        nonblank_parts = 1 if rest else 0
        found_case_number = bool(CASE_NUMBER_RE.search(rest))

        for _next_start, next_end, next_line in lines[line_no + 1:]:
            stripped = next_line.strip()
            if not stripped:
                header_end = next_end
                continue
            if TENTATIVE_RULING_ANCHOR_RE.search(stripped):
                break
            if re.match(r"^\d{1,3}\.\s*", stripped):
                break
            if not _looks_like_case_header_fragment(stripped):
                break

            parts.append(stripped)
            header_end = next_end
            nonblank_parts += 1
            if CASE_NUMBER_RE.search(stripped):
                found_case_number = True
                break
            if nonblank_parts >= 8:
                break

        if found_case_number:
            matches.append(
                _CaseHeaderMatch(
                    start=start,
                    end=header_end,
                    rest=" ".join(p for p in parts if p).strip(),
                )
            )

    return matches[-1] if matches else None


def _classify(disposition_text: str) -> tuple[str, bool, date | None]:
    """Return (primary_outcome, conditional, continued_to)."""
    cleaned = disposition_text
    for pat in BOILERPLATE_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    text = cleaned.upper()
    conditional = "ABSENT OBJECTION" in text

    has_denied = bool(re.search(r"\bDENIED\b|\bDISMISSES\b", text))
    has_granted = bool(re.search(r"\bGRANTED\b", text))
    has_continued = bool(re.search(r"\bCONTINUED TO\b|\bHEARING CONTINUED\b|\bCONTINUES THE MATTER\b", text))
    has_appearance = bool(re.search(r"\bAPPEARANCES ARE REQUIRED\b", text))
    has_off_cal = bool(re.search(r"\bOFF CALENDAR\b|\bDROPPED FROM (?:THE )?CALENDAR\b", text))

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
        m = CONTINUED_TO_RE.search(disposition_text)
        if m:
            month = m.group("month").upper()
            if month in _MONTHS:
                try:
                    continued_to = date(
                        int(m.group("year")),
                        _MONTHS[month],
                        int(m.group("day")),
                    )
                except ValueError:
                    pass

    return outcome, conditional, continued_to


def _strip_boilerplate(text: str) -> str:
    cleaned = text
    for pat in BOILERPLATE_PATTERNS:
        cleaned = pat.sub("", cleaned)
    return cleaned.strip()


def _split_case_header(rest: str) -> tuple[str, str]:
    """Given the part of a header line after the leading 'N. ', return (case_number, case_title).

    Handles all four observed formats:
      Style A: "25PR0206 MATTER OF ANDRESEN TRUST"        → first token is the number
      Style B/C: "CAPITAL ONE, N.A. v. McGINNIS, 25CV1362" → last comma-separated token is the number
      Style D: "MARIA DE LA CRUZ V. JUAN ... SFL20210053"  → last whitespace token is the number
    """
    m = CASE_NUMBER_RE.search(rest)
    if not m:
        return "", rest.strip(", \t")
    case_number = m.group(1)
    # Title = everything before case_number, possibly minus trailing ", " or whitespace.
    before = rest[: m.start()].rstrip(", \t")
    after = rest[m.end():].strip(", \t")
    title = (before + " " + after).strip(", \t") if after else before
    return case_number, title


def _extract_motion_type(lines: list[str]) -> tuple[str, int]:
    """Pull motion-type line(s) starting at lines[0].

    Returns (motion_type_text, lines_consumed). Motion type can be:
      - A single short title-like line (Styles A, B, C single-motion case)
      - Multiple '(<LETTER>) ...' lines (B, C multi-motion)
      - Empty (Style D — body starts immediately)
    """
    if not lines:
        return "", 0
    consumed_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            break
        # Multi-motion marker (A), (B), (C)
        if re.match(r"^\([A-Z]\)\s+\S", line):
            consumed_lines.append(line)
            i += 1
            continue
        # Single-line title: short, no sentence-ish punctuation, no leading lowercase
        # (which would suggest narrative continuation).
        if i == 0:
            if (
                len(line) <= 120
                and not _looks_like_narrative(line)
            ):
                consumed_lines.append(line)
                i += 1
                continue
        break
    return "\n".join(consumed_lines), i


def _looks_like_narrative(line: str) -> bool:
    """Heuristic: does this line look like body prose rather than a motion-type title?"""
    if len(line) > 130:
        return True
    # Narrative sentences typically have multiple periods OR end with a period.
    # Title lines like "Motion for Judgment on the Pleadings" don't.
    # But "Mr. Laub's Motion..." has a period; check for sentence-end period followed by space + capital.
    if re.search(r"\.\s+[A-Z]", line):
        return True
    # Body lines often start with " " (indented) or with a date-like phrase.
    if re.match(r"^\s*(?:On|Pending|This|The|Defendant|Plaintiff|Petitioner|Respondent|Decedent|At the|In this|Letters|Default)\b", line):
        return True
    return False


# ----------------------------------------------------------------- parse()


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
) -> list[Ruling]:
    """Extract all rulings from one EDC tentative-rulings PDF.

    `dept_hint`: department number ("9", "12", ...) supplied by the discovery
    layer (which knows what dept page the PDF was linked from). Used when the
    PDF header doesn't include the dept (Styles B, C).
    """
    if source_sha256 is None:
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    raw_pages = [page.extract_text() or "" for page in reader.pages]
    if not raw_pages:
        return []

    dept_hint = dept_hint or _dept_from_pdf_filename(source_url or "")
    meta = _extract_doc_meta(raw_pages[0], dept_hint)
    if meta.hearing_date is None:
        return []  # if we can't find a date, this isn't a tentatives PDF we recognise

    stripped_pages = _strip_headers_and_footers(raw_pages)
    stripped_pages = [_strip_continuation_marks(p) for p in stripped_pages]

    # Join pages with a separator so we can map offsets back to page numbers.
    joined_parts: list[str] = []
    page_offsets: list[int] = []  # offset into `plain` where page i starts
    cursor = 0
    SEP = "\n\n"
    for page in stripped_pages:
        page_offsets.append(cursor)
        joined_parts.append(page)
        cursor += len(page) + len(SEP)
    plain = SEP.join(joined_parts)

    def page_for_offset(offset: int) -> int:
        page = 1
        for i, start in enumerate(page_offsets):
            if start <= offset:
                page = i + 1
            else:
                break
        return page

    # Find disposition anchors.
    anchors = list(TENTATIVE_RULING_ANCHOR_RE.finditer(plain))
    if not anchors:
        return []

    header_matches: list[tuple[int, _CaseHeaderMatch | None]] = []
    for i, anchor in enumerate(anchors):
        anchor_idx = int(anchor.group(1))
        region_start = 0 if i == 0 else anchors[i - 1].end()
        region = plain[region_start:anchor.start()]
        header_matches.append((region_start, _find_case_header(region, anchor_idx)))

    # For each anchor, scan backward for the case-header line whose idx matches.
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        anchor_idx = int(anchor.group(1))

        region_start, header_match = header_matches[i]
        if header_match is None:
            # Couldn't find a header for this anchor — skip it (don't crash).
            continue

        header_start_abs = region_start + header_match.start
        header_end_abs = region_start + header_match.end
        case_number, case_title = _split_case_header(header_match.rest)

        # Lines after the header are motion-type and then body.
        after_header = plain[header_end_abs:anchor.start()]
        # Skip the immediate newline following the header.
        after_lines = after_header.lstrip("\n").splitlines()
        motion_type, lines_consumed = _extract_motion_type(after_lines)
        body_text = "\n".join(after_lines[lines_consumed:]).strip()

        # Disposition runs from this anchor to the next ruling's case header
        # (or end of doc).
        if i + 1 < len(anchors):
            next_i = i + 1
            while (
                next_i < len(anchors)
                and header_matches[next_i][1] is None
                and int(anchors[next_i].group(1)) == anchor_idx
            ):
                next_i += 1
            next_region_start, next_header = header_matches[next_i] if next_i < len(anchors) else (len(plain), None)
            if next_header is not None:
                disposition_end_abs = next_region_start + next_header.start
            else:
                disposition_end_abs = len(plain)
        else:
            disposition_end_abs = len(plain)

        disposition_text = plain[anchor.start():disposition_end_abs]
        # Drop the "TENTATIVE RULING #N:" marker itself from the captured text.
        disposition_text = disposition_text[anchor.end() - anchor.start():].strip()
        while True:
            duplicate_anchor = TENTATIVE_RULING_ANCHOR_RE.match(disposition_text)
            if duplicate_anchor is None:
                break
            disposition_text = disposition_text[duplicate_anchor.end():].strip()
        outcome_text = _strip_boilerplate(disposition_text)
        outcome, conditional, continued_to = _classify(disposition_text)

        # Page span — from the case header to the last char of non-whitespace
        # in the disposition.
        page_start = page_for_offset(header_start_abs)
        trimmed_end = anchor.start() + len(plain[anchor.start():disposition_end_abs].rstrip())
        page_end = max(page_start, page_for_offset(max(header_start_abs, trimmed_end - 1)))

        full_text = plain[header_start_abs:disposition_end_abs].strip()
        # Include the loop position and case number so two calendars in one PDF
        # that both number rulings from 1 (e.g. an AM and PM session) can't
        # collide on anchor_idx alone.
        ruling_id = hashlib.sha256(
            f"{source_sha256}:{i}:{anchor_idx}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=meta.division,
                dept=meta.dept,
                hearing_date=meta.hearing_date,
                ruling_index=anchor_idx,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=outcome_text,
                conditional=conditional,
                continued_to=continued_to,
                body_text=body_text,
                full_text=full_text,
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


def parse_file(path: str, source_url: str | None = None, dept_hint: str | None = None) -> list[Ruling]:
    """Convenience wrapper for tests and CLI use."""
    with open(path, "rb") as f:
        data = f.read()
    if source_url is None:
        source_url = f"file://{path}"
    return parse(data, source_url=source_url, dept_hint=dept_hint)
