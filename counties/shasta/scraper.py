"""Shasta County tentative-rulings scraper.

Discovery
---------
Shasta routes department PDFs through `tentatived<N>.pdf` filenames. The
historical "d10/d11" identifiers map to current dept numbers 24, 44, 51, etc.

Parsing
-------
Modern Shasta PDFs share a clean layout:

  Page-1 header:
    Tentative Rulings [and Resolution Review Hearings]
    <MONTH DAY, YEAR>
    Department <NN>

  Section markers (time-based, optional):
    8:30 a.m. - Law & Motion
    2:00 p.m.

  Per ruling:
    <TITLE in ALL CAPS or 'IN RE' form>   (often one line; can be two)
    CASE NUMBER:   <CASE_NUM>             (or "Case Number:   <CASE_NUM>")
    <body that starts with "Tentative Ruling on ..." and continues
     until the next CASE NUMBER line or end of doc>

  Probate variant adds higher-level section headers like "CONSERVATORSHIPS"
  before runs of CONSERVATORSHIP OF <NAME> blocks.

Case-number formats:
    26CV-0210058, 25CV-0208122      (modern civil)
    23PC-0032005, 25PC-0032767      (modern probate)
    23PB-0031963                    (older probate)
    CVPB19-0029935, CVPG09-0026137  (legacy)

A handful of PDFs are placeholders ("There are no tentative rulings ...");
parse() returns [] for those.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import ParseResult

import pypdf

from counties.static_pdf import discover_static_pdfs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

BASE = "https://shasta.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]

_OLD_TO_CURRENT_DEPT = {
    "d10": "24",
    "d7": "44",
    "d5": "51",
    "d6": "52",
    "d11": "53",
    "d8": "63",
    "d3": "64",
}


def _dept_hint(parsed: ParseResult, text: str, _page_url: str) -> str | None:
    hay = f"{parsed.path} {text}".lower()
    m = re.search(r"department\s+(\d+)", hay)
    if m:
        return m.group(1)
    for old, current in _OLD_TO_CURRENT_DEPT.items():
        if old in hay:
            return current
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE):
    return discover_static_pdfs(
        html,
        page_url=page_url or base_url,
        allowed_hosts={"shasta.courts.ca.gov", "www.shasta.courts.ca.gov"},
        path_test=lambda parsed, _text: "/system/files/tentative/" in parsed.path,
        default_division="Civil / Probate / Family Law",
        dept_hint=_dept_hint,
    )


# ============================================================ PARSE


_CASE_NUMBER_INNER = (
    r"\d{2}[A-Z]{2,4}-\d{4,8}"        # 26CV-0210058, 25CVG-01439, 23PC-0032005
    r"|[A-Z]{2,5}\d{2,4}-\d{4,8}"     # CVPB19-0029935, CVCV19-0191680
    r"|\d{4,8}"                        # legacy bare digits (193585 etc.)
)

# Modern anchor: "CASE NUMBER: <NUM>" (any case, optionally with trailing junk).
CASE_NUMBER_ANCHOR_RE = re.compile(
    rf"(?i)\bCase\s+Number:?\s+(?P<num>{_CASE_NUMBER_INNER})\b"
)
# Legacy anchor for dept-11/12 PDFs: "(Case No. NNNNNN)" on its own line.
LEGACY_CASE_NUMBER_ANCHOR_RE = re.compile(
    rf"\(Case\s+No\.?\s+(?P<num>{_CASE_NUMBER_INNER})\)",
    re.IGNORECASE,
)

# Page-1 header bits.
HEADER_DATE_RE = re.compile(
    r"^([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})\s*$", re.MULTILINE
)
HEADER_DEPT_RE = re.compile(r"^\s*Department\s+(\d+)\s*$", re.MULTILINE | re.IGNORECASE)

# Section-time markers ("8:30 a.m. - Law & Motion", "2:00 p.m.").
SECTION_TIME_RE = re.compile(
    r"^\**\s*(?P<time>\d{1,2}:\d{2}\s+[apAP]\.?[mM]\.?)"
    r"(?:\s*[-–]\s*(?P<label>.+?))?\s*\**\s*$",
    re.MULTILINE,
)

# Probate top-section markers (e.g., CONSERVATORSHIPS, GUARDIANSHIPS).
PROBATE_SECTION_RE = re.compile(
    r"^\s*(?P<section>"
    r"CONSERV\s?ATORSHIPS?"
    r"|GUARDIANSHIPS?"
    r"|TRUSTS?"
    r"|DECEDENT'?S?\s+ESTATES?"
    r"|PROBATE"
    r"|ADOPTIONS?"
    r")\s*$",
    re.MULTILINE,
)

# Page-number lines.
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")

# Continued-to extractor. Skips optional intermediate "Monday," or a time prefix.
CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(?:[\w:.]+\s+(?:a\.m\.|p\.m\.|AM|PM)\s+(?:on\s+)?)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE | re.DOTALL,
)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}


def _parse_long_date(text: str) -> date | None:
    m = HEADER_DATE_RE.search(text)
    if m:
        mo = m.group(1).upper()
        if mo in _MONTHS:
            try:
                return date(int(m.group(3)), _MONTHS[mo], int(m.group(2)))
            except ValueError:
                pass
    # Fallback: any "Month DD, YYYY" near top.
    fallback = re.search(r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})\b", text)
    if fallback:
        mo = fallback.group(1).upper()
        if mo in _MONTHS:
            try:
                return date(int(fallback.group(3)), _MONTHS[mo], int(fallback.group(2)))
            except ValueError:
                pass
    return None


def _detect_division(header_text: str, hint: str | None) -> str | None:
    upper = header_text.upper()
    if "PROBATE" in upper or "CONSERV" in upper:
        return "Probate"
    if "RESOLUTION REVIEW" in upper or "LAW & MOTION" in upper or "LAW AND MOTION" in upper:
        return "Law and Motion"
    if "FAMILY" in upper:
        return "Family Law"
    return hint


def _detect_dept(header_text: str, hint: str | None) -> str | None:
    m = HEADER_DEPT_RE.search(header_text)
    if m:
        return m.group(1)
    return hint


def _detect_style(header_text: str) -> str:
    upper = header_text.upper()
    if "PROBATE" in upper or "CONSERV" in upper:
        return "shasta-probate"
    if "RESOLUTION REVIEW" in upper:
        return "shasta-resolution-review"
    return "shasta-lawmotion"


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    division: str | None
    dept: str | None
    style: str


def _extract_doc_meta(
    page1_text: str, dept_hint: str | None, division_hint: str | None
) -> _DocMeta:
    head = "\n".join(page1_text.splitlines()[:10])
    return _DocMeta(
        hearing_date=_parse_long_date(head),
        division=_detect_division(head, division_hint),
        dept=_detect_dept(head, dept_hint),
        style=_detect_style(head),
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
    has_denied = bool(re.search(
        r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b|\bMOTION\s+IS\s+OVERRULED\b",
        upper,
    ))
    has_granted = bool(re.search(
        r"\bGRANTED?\b|\bSUSTAINED\b|\bAPPROVED\b|\bPETITION\s+IS\s+(?:HEREBY\s+)?ALLOWED\b",
        upper,
    ))
    has_continued = bool(re.search(
        r"\bCONTINUED\s+TO\b|\bCONTINUES\s+(?:THE|THIS)\b|\bMATTER\s+IS\s+CONTINUED\b",
        upper,
    ))
    has_appearance = bool(re.search(
        r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:NECESSARY|REQUIRED)\b"
        r"|\bAPPEAR(?:ANCE)?\s+(?:IS\s+)?(?:NECESSARY|REQUIRED)\b"
        r"|\bAPPEAR\s+TO\s+DISCUSS\b"
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


def _extract_title_above(plain: str, header_start: int) -> str:
    """Walk upward from a CASE NUMBER line to capture the case-title block.

    The title is the contiguous non-blank lines immediately preceding the case
    number, stopping at a blank line, a previous case-number line, a section
    marker, or the top of the doc.
    """
    before = plain[:header_start]
    title_lines: list[str] = []
    for line in reversed(before.splitlines()):
        s = line.strip()
        if not s:
            if title_lines:
                break
            continue
        if "CASE NUMBER" in s.upper() or CASE_NUMBER_ANCHOR_RE.match(line):
            break
        if SECTION_TIME_RE.match(line) or PROBATE_SECTION_RE.match(line):
            break
        # Skip decorative dividers like "******".
        if re.match(r"^[*=-]{3,}$", s):
            break
        # Stop at a "Tentative Ruling" body marker (so we don't slurp a prior body).
        if re.match(r"^\s*Tentative Ruling", line):
            break
        title_lines.append(s)
        if len(title_lines) >= 4:
            break
    title_lines.reverse()
    return _normalize_text(" ".join(" ".join(title_lines).split()))


def _normalize_text(s: str) -> str:
    """Repair pypdf's habit of inserting a space mid-word (e.g. 'CONSERV ATORSHIP')."""
    # Collapse split words like "CONSERV ATORSHIP" -> "CONSERVATORSHIP".
    for split, joined in [
        ("CONSERV ATORSHIP", "CONSERVATORSHIP"),
        ("CONSERV ATEE", "CONSERVATEE"),
        ("DA VID", "DAVID"),
        ("CHA VEZ", "CHAVEZ"),
        ("TRA VIS", "TRAVIS"),
    ]:
        s = s.replace(split, joined)
    return s


def _extract_motion_type(body: str) -> str:
    """Pull a short motion-type from the body's leading 'Tentative Ruling on X:' clause."""
    m = re.match(r"\s*Tentative\s+Ruling\s+(?:on|re|regarding)\s+([^:.\n]+)[:.]", body, re.IGNORECASE)
    if m:
        return " ".join(m.group(1).split())
    # First non-blank line, capped at 120 chars.
    for line in body.splitlines():
        s = line.strip()
        if s:
            return s[:120]
    return ""


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

    # Modern anchors plus legacy "(Case No. NNN)" anchors.
    anchors = sorted(
        list(CASE_NUMBER_ANCHOR_RE.finditer(plain))
        + list(LEGACY_CASE_NUMBER_ANCHOR_RE.finditer(plain)),
        key=lambda m: m.start(),
    )
    if not anchors:
        return []

    rulings: list[Ruling] = []
    current_section: str | None = None
    current_time: str | None = None
    for i, anchor in enumerate(anchors):
        # Pick up any probate-section header in the region above this anchor.
        region_start = anchors[i - 1].end() if i > 0 else 0
        region = plain[region_start:anchor.start()]
        for sm in PROBATE_SECTION_RE.finditer(region):
            section = " ".join(sm.group("section").split())
            # Collapse "CONSERV ATORSHIPS" -> "Conservatorships".
            current_section = _normalize_text(section).title()
        for tm in SECTION_TIME_RE.finditer(region):
            current_time = tm.group("time").strip()

        case_number = anchor.group("num")

        # Disposition: from end of this anchor line to start of next anchor line.
        disposition_start = anchor.end()
        if i + 1 < len(anchors):
            # Cut at the start of the next anchor's title block.
            disposition_end = anchors[i + 1].start()
            # Walk back to nearest blank line before the next title.
            next_region = plain[disposition_start:disposition_end]
            idx = len(next_region)
            # Locate the first non-blank line scanning backwards from end:
            while idx > 0:
                prev_newline = next_region.rfind("\n", 0, idx - 1)
                if prev_newline == -1:
                    break
                segment = next_region[prev_newline + 1:idx - 1]
                if not segment.strip():
                    break
                idx = prev_newline + 1
            # Use only the part up to the boundary so far.
            disposition_end = disposition_start + idx
        else:
            disposition_end = len(plain)

        disposition_text = plain[disposition_start:disposition_end].strip()
        outcome, conditional, continued_to = _classify(disposition_text)
        motion_type = _extract_motion_type(disposition_text)

        # Title: walk up from this anchor.
        case_title = _extract_title_above(plain, anchor.start())

        # If we're in a probate section and the title is empty, prepend section.
        if current_section and not case_title:
            case_title = current_section

        # Header offset for page calculation: start of title block.
        header_start = anchor.start()
        if case_title:
            # Approximate: walk back through title lines.
            t_idx = anchor.start()
            blanks_to_skip = 1
            while t_idx > 0:
                prev_newline = plain.rfind("\n", 0, t_idx - 1)
                if prev_newline == -1:
                    t_idx = 0
                    break
                line = plain[prev_newline + 1:t_idx - 1]
                if not line.strip():
                    if blanks_to_skip <= 0:
                        t_idx = prev_newline + 1
                        break
                    blanks_to_skip -= 1
                t_idx = prev_newline + 1
            header_start = t_idx

        page_start = page_for_offset(header_start)
        trimmed_end = disposition_start + len(plain[disposition_start:disposition_end].rstrip())
        page_end = max(page_start, page_for_offset(max(header_start, trimmed_end - 1)))

        ruling_id = hashlib.sha256(
            f"{source_sha256}:{i + 1}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=current_section or meta.division,
                dept=meta.dept,
                hearing_date=meta.hearing_date,
                ruling_index=i + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=disposition_text,
                conditional=conditional,
                continued_to=continued_to,
                body_text=current_time or "",
                full_text=plain[header_start:disposition_end].strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=meta.style,
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.utcnow(),
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
