"""Amador County tentative-rulings scraper.

Discovery
---------
Amador's public legacy page is not a form. It is four dropdowns whose option
values point directly at historical PDFs. The page says new rulings moved to
the portal after February 15, 2022, but the dropdowns still expose 2020-2022
PDFs.

Parsing
-------
Amador uses four overlapping PDF styles, all in the 2020-2022 legacy archive:

  Style A: "AMADOR SUPERIOR COURT LAW AND MOTION TENTATIVE RULINGS" + date.
           Each ruling: "<CASE_NUMBER> <PARTY_LIST>" then "TENTATIVE RULING:"
           then disposition.
  Style B: "AMADOR SUPERIOR COURT CASE MANAGEMENT CONFERENCE TENTATIVE RULINGS"
           + 'Family Law Cases' or 'Civil Cases' + date.
           Same per-ruling shape as Style A.
  Style C: "DEPARTMENT N TENTATIVE RULINGS 8:30 A.M., <date>" - numbered
           cases (1., 2., ...) with multi-motion subdivisions.
  Style D: Calendar-table format with header row "Calendar  Primary Party /
           Attorney Case Number Secondary Party / Attorney", DEPT N, judge
           name, date, then event-style entries with "Tentative Ruling:"
           (lowercase).

All four share a common anchor: "TENTATIVE RULING:" (case-insensitive). The
parser is style-agnostic and uses the most recent case-number line above each
anchor as the ruling header.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import pypdf

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

BASE = "https://www.amadorcourt.org/os-tentativerulings.aspx"
LANDING_PAGES = [BASE]
WAYBACK_PDF_PATTERNS = [
    "www.amadorcourt.org/tentativeRulings/*",
    "amadorcourt.org/tentativeRulings/*",
]

_SELECT_DIVISIONS = {
    "selectid1": "Civil Law and Motion",
    "selectid2": "Civil Case Management Conference",
    "selectid3": "Family Law Case Management",
    "selectid4": "Child Support",
}

_PATH_DIVISIONS = {
    "CivilLawAndMotion": "Civil Law and Motion",
    "CivilCaseMgtConference": "Civil Case Management Conference",
    "FamilyLawCaseMgt": "Family Law Case Management",
    "ChildSupport": "Child Support",
}


def _division_for(raw_url: str, parent_attrs: dict[str, str] | None) -> str | None:
    if parent_attrs:
        select_id = (parent_attrs.get("id") or parent_attrs.get("name") or "").lower()
        if select_id in _SELECT_DIVISIONS:
            return _SELECT_DIVISIONS[select_id]
    for segment, division in _PATH_DIVISIONS.items():
        if f"/{segment}/" in raw_url:
            return division
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    refs: list[PdfRef] = []
    source_page = page_url or base_url
    for link in extract_links(html):
        if ".pdf" not in link.url.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.amadorcourt.org", "amadorcourt.org"}:
            continue
        if "/tentativerulings/" not in parsed.path.lower():
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_for(link.url, link.parent_attrs),
                link_text=link.text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)


def ref_from_wayback_url(url: str, wayback_ts: str | None = None) -> PdfRef:
    return PdfRef(
        url=url,
        filename=filename_from_url(url),
        wayback_ts=wayback_ts,
        division_hint=_division_for(url, None),
    )


# ============================================================ PARSE


# Case-number formats observed:
#   18-CVC-10752, 13-FCD-05303, 19-DCS-04140    (modern with dashes)
#   19 CVC 11019, 21 FC 7597, 21 CVC 12114      (older, space separated)
CASE_NUMBER_RE = re.compile(
    r"\b(?P<num>\d{2}[\s-]+[A-Z]{2,5}[\s-]+\d{4,6})\b"
)

# Disposition anchor. Used across Styles A-D, both capitalised and
# title-case ("Tentative Ruling:" in the calendar-table style).
TENTATIVE_RULING_ANCHOR_RE = re.compile(
    r"^\s*\(?\s*TENTATIVE\s+RULING\s*\)?\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# Numbered ruling header for Style C (DEPARTMENT N TENTATIVE RULINGS).
# "1. <CASE_NUMBER> <CASE_TITLE>" on its own line.
STYLE_C_HEADER_RE = re.compile(
    r"^(?P<idx>\d{1,3})\.\s+(?P<rest>.*?\b\d{2}[\s-]+[A-Z]{2,5}[\s-]+\d{4,6}\b.*?)\s*$",
    re.MULTILINE,
)

# Date in long form ("Friday, January 10, 2020", "January 10, 2020", "April 11, 2022").
LONG_DATE_RE = re.compile(
    r"(?:(?:Mon|Tues|Wed|Thurs|Fri|Satur|Sun)day,\s+)?"
    r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)
# Date in short form ("2/3/2020", "1/12/2022").
SHORT_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

# Continued-to extractor.
CONTINUED_TO_RE = re.compile(
    r"CONTINUED\s+TO\s+(?:[\w:.]+\s+(?:a\.m\.|p\.m\.|AM|PM)\s+on\s+)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

# Marker for end-of-document boilerplate (footer label).
DOCUMENT_FOOTER_RE = re.compile(
    r"^[A-Z][A-Z &/]*TENTATIVE RULINGS[- (]+Rev\..*$",
    re.MULTILINE,
)

# Page numbers, "Page 2 of 5", or stand-alone digits.
PAGE_NUMBER_RE = re.compile(r"^\s*(?:Page\s+\d+\s+of\s+\d+|\d{1,3})\s*$", re.IGNORECASE)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}


def _parse_date(text: str) -> date | None:
    m = LONG_DATE_RE.search(text)
    if m:
        mo = m.group(1).upper()
        if mo in _MONTHS:
            try:
                return date(int(m.group(3)), _MONTHS[mo], int(m.group(2)))
            except ValueError:
                pass
    m = SHORT_DATE_RE.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return None


def _detect_division(header_text: str, hint: str | None) -> str | None:
    upper = header_text.upper()
    if "LAW AND MOTION" in upper or "LAW & MOTION" in upper:
        return "Law and Motion"
    if "CASE MANAGEMENT CONFERENCE" in upper or "CASE MANAGEMENT TENTATIVE" in upper:
        if "FAMILY" in upper:
            return "Family Law Case Management"
        if "CIVIL" in upper:
            return "Civil Case Management Conference"
        return "Case Management Conference"
    if "FAMILY LAW" in upper:
        return "Family Law Case Management"
    if "CHILD SUPPORT" in upper:
        return "Child Support"
    if "PROBATE" in upper:
        return "Probate"
    return hint


def _detect_dept_from_header(header_text: str) -> str | None:
    """Pull dept number from 'DEPARTMENT N' header lines or 'DEPT N' shortcuts."""
    m = re.search(r"(?:DEPARTMENT|DEPT\.?)\s+(\d{1,3})\b", header_text, re.IGNORECASE)
    return m.group(1) if m else None


def _detect_style(header_text: str) -> str:
    upper = header_text.upper()
    if "LAW AND MOTION TENTATIVE RULINGS" in upper:
        return "amador-lawmotion"
    if "CASE MANAGEMENT CONFERENCE TENTATIVE" in upper:
        return "amador-cmc"
    if re.search(r"DEPARTMENT\s+\d+\s+TENTATIVE RULINGS", upper):
        return "amador-dept"
    if re.search(r"DEPT\s+\d+", upper):
        return "amador-calendar-table"
    return "amador-other"


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    division: str | None
    dept: str | None
    style: str


def _extract_doc_meta(
    page1_text: str,
    dept_hint: str | None,
    division_hint: str | None,
) -> _DocMeta:
    head = "\n".join(page1_text.splitlines()[:20])
    return _DocMeta(
        hearing_date=_parse_date(head),
        division=_detect_division(head, division_hint),
        dept=_detect_dept_from_header(head) or dept_hint,
        style=_detect_style(head),
    )


def _strip_page_artifacts(page_texts: list[str]) -> list[str]:
    out: list[str] = []
    for t in page_texts:
        lines = [l for l in t.splitlines() if not PAGE_NUMBER_RE.match(l)]
        # Drop the footer label entirely.
        joined = "\n".join(lines)
        joined = DOCUMENT_FOOTER_RE.sub("", joined)
        out.append(joined)
    return out


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDENIED\b|\bDENIES\b|\bDISMISSED?\b", upper))
    has_granted = bool(re.search(r"\bGRANTED?\b|\bSUSTAINED\b", upper))
    has_continued = bool(re.search(
        r"\bCONTINUED TO\b|\bHEARING (?:IS )?CONTINUED\b|\bIS CONTINUED FOR\b|\bMATTER IS CONTINUED\b",
        upper,
    ))
    has_appearance = bool(re.search(
        r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:NECESSARY|REQUIRED)\b"
        r"|\bORDERED TO APPEAR\b"
        r"|\bAPPEAR PERSONALLY\b",
        upper,
    ))
    has_no_appearance = "NO APPEARANCES NECESSARY" in upper or "NO APPEARANCE NECESSARY" in upper
    has_off_cal = bool(re.search(r"\bOFF\s+CALENDAR\b|\bDROPPED\s+FROM\b|\bVACATED\b", upper))
    has_no_tentative = "THERE IS NO TENTATIVE RULING" in upper or "NO TENTATIVE RULING ISSUED" in upper

    # Precedence: denied > granted > continued > off > appearance > other
    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_off_cal:
        outcome = "off_calendar"
    elif has_no_tentative:
        outcome = "appearance_required"
    elif has_appearance and not has_no_appearance:
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


def _split_case_header(rest: str) -> tuple[str, str]:
    """Split 'N. <CASE_NUMBER> <TITLE>' or '<CASE_NUMBER> <TITLE>' into pieces."""
    m = CASE_NUMBER_RE.search(rest)
    if not m:
        return "", rest.strip(", \t")
    case_number = m.group("num")
    before = rest[: m.start()].strip(", \t")
    after = rest[m.end():].strip(", \t")
    title = (before + " " + after).strip(", \t") if before else after
    # Squash internal repeated whitespace.
    title = " ".join(title.split())
    # Strip the prefix index marker if any survived.
    title = re.sub(r"^\d{1,3}\.\s*", "", title)
    return case_number, title


def _normalize_case_number(num: str) -> str:
    """Collapse internal whitespace to dashes for stability."""
    return re.sub(r"\s+", "-", num.strip())


# Line containing a case number where the case number sits early in the line
# (used for no-anchor parsing in Style C).
CASE_HEADER_LINE_RE = re.compile(
    r"^\s*(?:(?P<idx>\d{1,3})\.\s+)?"
    r"(?P<num>\d{2}[\s-]+[A-Z]{2,5}[\s-]+\d{4,6})\s+"
    r"(?P<title>\S.*?)\s*$",
    re.MULTILINE,
)


def _parse_no_anchor(
    plain: str,
    page_for_offset,
    meta: _DocMeta,
    source_url: str,
    source_sha256: str,
) -> list[Ruling]:
    """Split into rulings using case-number lines as boundaries (Style C)."""
    headers: list[re.Match[str]] = []
    seen_cases: set[str] = set()
    for hm in CASE_HEADER_LINE_RE.finditer(plain):
        title = (hm.group("title") or "").strip()
        # Skip page-break continuation markers like "Tentative Ruling Continued:".
        if re.search(r"^Tentative Ruling Continued", title, re.IGNORECASE):
            continue
        # De-dup by case number; the first occurrence is the real header,
        # subsequent ones are likely continuation lines.
        case_norm = _normalize_case_number(hm.group("num"))
        if case_norm in seen_cases:
            continue
        seen_cases.add(case_norm)
        headers.append(hm)

    if not headers:
        return []

    rulings: list[Ruling] = []
    for i, hm in enumerate(headers):
        case_number = _normalize_case_number(hm.group("num"))
        case_title = " ".join((hm.group("title") or "").split())
        header_start = hm.start()
        header_end = hm.end()
        section_end = headers[i + 1].start() if i + 1 < len(headers) else len(plain)
        disposition_text = plain[header_end:section_end].strip()
        outcome, conditional, continued_to = _classify(disposition_text)
        page_start = page_for_offset(header_start)
        trimmed_end = header_end + len(plain[header_end:section_end].rstrip())
        page_end = max(page_start, page_for_offset(max(header_start, trimmed_end - 1)))

        idx_raw = hm.group("idx")
        ruling_index = int(idx_raw) if idx_raw else (i + 1)
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
                motion_type="",
                outcome=outcome,
                outcome_text=disposition_text,
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=plain[header_start:section_end].strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=meta.style or "amador-dept",
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.now(UTC),
            )
        )
    return rulings


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
        # Style C: numbered "N. <CASE_NUMBER> ..." headers, no TENTATIVE RULING anchor.
        # Each section runs from one header to the next.
        return _parse_no_anchor(
            plain=plain,
            page_for_offset=page_for_offset,
            meta=meta,
            source_url=source_url,
            source_sha256=source_sha256,
        )

    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        # Region above this anchor to look for the most recent case header.
        region_start = anchors[i - 1].end() if i > 0 else 0
        region_end = anchor.start()
        region = plain[region_start:region_end]

        # Style C: a numbered header "N. <CASE_NUMBER> ..." anywhere in the region.
        # Otherwise: the LAST occurrence of a CASE NUMBER in the region.
        header_match = None
        for hm in STYLE_C_HEADER_RE.finditer(region):
            header_match = hm
        if header_match is not None:
            header_start = region_start + header_match.start()
            header_end = region_start + header_match.end()
            ruling_index = int(header_match.group("idx"))
            case_number, case_title = _split_case_header(header_match.group("rest"))
        else:
            cn_match = None
            for cm in CASE_NUMBER_RE.finditer(region):
                cn_match = cm
            if cn_match is None:
                continue
            # The header is the *line* containing the case number.
            line_start = region.rfind("\n", 0, cn_match.start()) + 1
            line_end = region.find("\n", cn_match.end())
            if line_end == -1:
                line_end = len(region)
            header_start = region_start + line_start
            header_end = region_start + line_end
            ruling_index = i + 1
            case_number, case_title = _split_case_header(region[line_start:line_end])

        case_number = _normalize_case_number(case_number)

        # Disposition: from end-of-anchor-line to next ruling's header (or end of doc).
        disposition_start = anchor.end()
        if i + 1 < len(anchors):
            disposition_end = anchors[i + 1].start()
            # Trim trailing next-header content if a header sits between them.
            next_region = plain[disposition_start:disposition_end]
            cuts = list(CASE_NUMBER_RE.finditer(next_region))
            style_c_cuts = list(STYLE_C_HEADER_RE.finditer(next_region))
            if style_c_cuts:
                disposition_end = disposition_start + style_c_cuts[-1].start()
            elif cuts:
                # Cut at the start of the line containing the last case number
                last = cuts[-1]
                line_start = next_region.rfind("\n", 0, last.start()) + 1
                disposition_end = disposition_start + line_start
        else:
            disposition_end = len(plain)

        disposition_text = plain[disposition_start:disposition_end].strip()
        # The case-title line shouldn't include extraneous body content.
        outcome, conditional, continued_to = _classify(disposition_text)

        # Body region between header line and disposition anchor.
        body_text = plain[header_end:anchor.start()].strip()
        # Many bodies are empty (the disposition follows directly after the anchor).

        page_start = page_for_offset(header_start)
        trimmed_end = disposition_start + len(plain[disposition_start:disposition_end].rstrip())
        page_end = max(page_start, page_for_offset(max(header_start, trimmed_end - 1)))

        full_text = plain[header_start:disposition_end].strip()
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
                motion_type="",  # Amador rarely puts a motion-type line above the anchor
                outcome=outcome,
                outcome_text=disposition_text,
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
