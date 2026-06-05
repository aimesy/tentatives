"""Nevada County tentative-rulings scraper.

Discovery
---------
The Nevada page is a static Drupal page with accordion sections for Nevada
City and Truckee. Ruling documents are court-hosted files under
`/system/files/tentative-rulings/`. Current pages may include Word documents;
discovery returns both PDFs and DOCX files for archiving. Parsing handles PDFs
and supported Word-text calendars.

Parsing
-------
Nevada PDFs share a single structural pattern:

  Page-1 header:  "<MONTH DAY, YEAR> <Location> <Division> Tentative Rulings"
                  (e.g. "April 27, 2026 Truckee Probate Tentative Rulings")
  Per ruling:     "N. <CASE_NUMBER>  <CASE_TITLE>"
                  (possibly multi-line for long titles)
                  <blank>
                  <disposition body, continues until next "N." header or doc end>

Some variants:
  - Guardianship: "Case No.  P10-15099" is the case-number marker
  - Long titles wrap to the next line ("vs. <something>" on a new line)
  - Body may include "Department A" / "Dept. A" references for dept binding

Case-number formats:
  CL0002502, PR0000974      (modern, 2 letters + 6-8 digits, no dash)
  TP19-7245                 (legacy, letters + 2 digits + dash + digits)
  P10-15099, P12-15336      (single-letter prefix)
  CVPM18-0001               (case-management code)
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import pypdf

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

BASE = "https://www.nevada.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings",
]
PARSE_EXTENSIONS = {".pdf", ".docx"}


def _division_from_text(text: str) -> str | None:
    low = text.lower()
    if "case management" in low or "cmc" in low:
        return "Case Management"
    if "family" in low:
        return "Family Law"
    if "probate" in low:
        return "Probate"
    if "civil" in low or "law and motion" in low or "law & motion" in low:
        return "Law and Motion"
    if "guardianship" in low:
        return "Guardianship"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        lower_url = link.url.lower().split("?", 1)[0]
        if not lower_url.endswith((".pdf", ".docx")):
            continue
        text = link.text
        if "tentative" not in text.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.nevada.courts.ca.gov", "nevada.courts.ca.gov"}:
            continue
        if "/system/files/tentative-rulings/" not in parsed.path.lower():
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_from_text(text),
                link_text=text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)


# ============================================================ PARSE


# Case-number formats observed in Nevada PDFs.
# - Modern, 2-4 letter prefix + 4-8 digits: CL0002502, CU0001483, PR0000974, CVPM18-0001
# - Legacy, letters + 2 digits + dash + digits: TP19-7245, P10-15099
_CASE_NUMBER_INNER = (
    r"[A-Z]{1,5}\d{2}-\d{4,6}"      # P10-15099, TP19-7245, CVPM18-0001
    r"|[A-Z]{2,5}\d{4,8}"           # CL0002502, CU0001483, PR0000974
)
CASE_NUMBER_RE = re.compile(rf"\b(?P<num>{_CASE_NUMBER_INNER})\b")

# Ruling header: "N.  <CASE_NUMBER>  <TITLE>" or with "Case No." prefix
# (guardianship variant).
RULING_HEADER_RE = re.compile(
    rf"^(?P<idx>\d{{1,3}})\.\s+(?:Case\s+No\.?\s+)?"
    rf"(?P<num>{_CASE_NUMBER_INNER})"
    r"\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)
DOCX_RULING_HEADER_RE = re.compile(
    rf"^(?:\d{{1,3}}\.\s+)?(?:Case\s+No\.?\s+)?"
    rf"(?P<num>{_CASE_NUMBER_INNER})"
    r"\s+(?P<title>.+?)\s*$"
)

# Long date "April 27, 2026" or short "4/27/2026" or "05/07/2026".
LONG_DATE_RE = re.compile(r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})\b")
SHORT_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

# Department from header or body ("Dept. A", "Department 3", "in Dept. A").
INLINE_DEPT_RE = re.compile(r"\b(?:Dept\.|Department)\s+(\d+|[A-Z])\b", re.IGNORECASE)

# Page-number footers ("1", "2", "Page 1 of 3").
PAGE_NUMBER_RE = re.compile(r"^\s*(?:Page\s+\d+\s+of\s+\d+|\d{1,3})\s*$", re.IGNORECASE)

# Continued-to extractor.
CONTINUED_TO_RE = re.compile(
    r"(?:continued\s+(?:on[^.,]*?to|to)"
    r"|continues\s+(?:the\s+)?(?:case\s+management\s+conference|matter|hearing|cmc)\s+to"
    r"|matter\s+is\s+continued\s+to)\s+"
    r"(?:[\w:.]+\s+(?:a\.m\.|p\.m\.|AM|PM)\s+(?:on\s+)?)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _parse_date(text: str) -> date | None:
    for m in LONG_DATE_RE.finditer(text):
        mo = m.group(1).upper()
        if mo in _MONTHS:
            try:
                return date(int(m.group(3)), _MONTHS[mo], int(m.group(2)))
            except ValueError:
                continue
    m = SHORT_DATE_RE.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return None


def _detect_division(header_text: str, hint: str | None) -> str | None:
    upper = header_text.upper()
    if "GUARDIANSHIP" in upper:
        return "Guardianship"
    if "PROBATE" in upper:
        return "Probate"
    if "CASE MANAGEMENT" in upper:
        return "Case Management"
    if "LAW & MOTION" in upper or "LAW AND MOTION" in upper or "CIVIL" in upper:
        return "Law and Motion"
    if "FAMILY" in upper:
        return "Family Law"
    return hint


def _detect_location(header_text: str) -> str | None:
    """Nevada has Truckee and Nevada City branches; capture this as motion-type prefix."""
    upper = header_text.upper()
    if "TRUCKEE" in upper:
        return "Truckee"
    if "NEVADA CITY" in upper:
        return "Nevada City"
    return None


def _detect_dept(text: str, hint: str | None) -> str | None:
    m = INLINE_DEPT_RE.search(text)
    if m:
        return m.group(1)
    return hint


def _detect_style(header_text: str) -> str:
    upper = header_text.upper()
    if "PROBATE" in upper:
        return "nevada-probate"
    if "GUARDIANSHIP" in upper:
        return "nevada-guardianship"
    if "CASE MANAGEMENT" in upper:
        return "nevada-cmc"
    if "LAW & MOTION" in upper or "LAW AND MOTION" in upper or "CIVIL" in upper:
        return "nevada-lawmotion"
    return "nevada-other"


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    division: str | None
    dept: str | None
    style: str
    location: str | None


def _extract_doc_meta(
    page1_text: str, dept_hint: str | None, division_hint: str | None
) -> _DocMeta:
    head = "\n".join(page1_text.splitlines()[:10])
    return _DocMeta(
        hearing_date=_parse_date(head),
        division=_detect_division(head, division_hint),
        dept=_detect_dept(head, dept_hint),
        style=_detect_style(head),
        location=_detect_location(head),
    )


def _strip_page_artifacts(page_texts: list[str]) -> list[str]:
    out: list[str] = []
    for t in page_texts:
        lines = [l for l in t.splitlines() if not PAGE_NUMBER_RE.match(l)]
        out.append("\n".join(lines))
    return out


def _docx_paragraph_lines(docx_bytes: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
    except (KeyError, ET.ParseError, zipfile.BadZipFile):
        return []

    lines: list[str] = []
    for para in root.findall(f".//{_W_NS}p"):
        parts: list[str] = []
        for node in para.iter():
            if node.tag == f"{_W_NS}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W_NS}tab":
                parts.append("\t")
            elif node.tag == f"{_W_NS}br":
                parts.append("\n")
        for line in "".join(parts).splitlines():
            clean = line.strip()
            if clean:
                lines.append(clean)
    return lines


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDEN(?:IED|IES)\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANTED?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(
        r"\b(?:IS\s+|HEREBY\s+)?CONTINUED\s+(?:ON|TO)\b"
        r"|\bCONTINUES\s+(?:THE\s+(?:MATTER|CASE\s+MANAGEMENT|HEARING)|(?:THIS\s+|THE\s+)?CMC)\b"
        r"|\bMATTER\s+IS\s+CONTINUED\b",
        upper,
    ))
    has_appearance = bool(re.search(
        r"\bAPPEARANCES?\s+(?:ARE\s+)?REQUIRED\b"
        r"|\bAPPEAR(?:ANCE)?\s+(?:IS\s+)?REQUIRED\b"
        r"|\bPERSONAL\s+APPEARANCE\b",
        upper,
    ))
    has_no_appearance = bool(re.search(
        r"\bNO\s+APPEARANCES?\s+(?:ARE\s+)?(?:NECESSARY|REQUIRED)\b"
        r"|\bAPPEARANCE\s+IS\s+NOT\s+NECESSARY\b",
        upper,
    ))
    has_off_cal = bool(re.search(r"\bOFF\s+CALENDAR\b|\bVACATED\b|\bDROPPED\s+FROM\b", upper))

    # Precedence: continued/off > denied > granted > appearance > no_appearance/other.
    # CMC continuances usually appear together with "no appearances are required";
    # the continuance is the substantive ruling, so it wins.
    if has_continued:
        outcome = "continued"
    elif has_off_cal:
        outcome = "off_calendar"
    elif has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
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


def _parse_docx(
    docx_bytes: bytes,
    source_url: str,
    source_sha256: str,
    dept_hint: str | None,
    division_hint: str | None,
) -> list[Ruling]:
    lines = _docx_paragraph_lines(docx_bytes)
    if not lines:
        return []

    header_text = lines[0]
    hearing_date = _parse_date(header_text)
    if hearing_date is None:
        return []

    division = _detect_division(header_text, division_hint)
    style = _detect_style(header_text)
    location = _detect_location(f"{header_text}\n{source_url}")
    default_dept = _detect_dept(header_text, dept_hint)

    headers: list[tuple[int, re.Match[str]]] = []
    for idx, line in enumerate(lines[1:], start=1):
        match = DOCX_RULING_HEADER_RE.match(line)
        if match:
            headers.append((idx, match))
    if not headers:
        return []

    rulings: list[Ruling] = []
    for ruling_index, (line_idx, hm) in enumerate(headers, start=1):
        next_line_idx = headers[ruling_index][0] if ruling_index < len(headers) else len(lines)
        body_lines = lines[line_idx + 1:next_line_idx]
        body = "\n".join(body_lines).strip()
        section_text = "\n".join([lines[line_idx], *body_lines]).strip()

        case_number = hm.group("num")
        case_title = " ".join(hm.group("title").split())
        outcome, conditional, continued_to = _classify(body)
        local_dept = default_dept or _detect_dept(section_text, dept_hint)

        ruling_id = hashlib.sha256(
            f"{source_sha256}:{ruling_index}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=division,
                dept=local_dept,
                hearing_date=hearing_date,
                ruling_index=ruling_index,
                case_number=case_number,
                case_title=case_title,
                motion_type=location or "",
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=section_text,
                page_start=1,
                page_end=1,
                source_sha256=source_sha256,
                source_url=source_url,
                style=f"{style}-docx",
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
    if pdf_bytes.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return _parse_docx(
            pdf_bytes,
            source_url=source_url,
            source_sha256=source_sha256,
            dept_hint=dept_hint,
            division_hint=division_hint,
        )
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

    headers = list(RULING_HEADER_RE.finditer(plain))
    if not headers:
        return []

    rulings: list[Ruling] = []
    for i, hm in enumerate(headers):
        idx = int(hm.group("idx"))
        case_number = hm.group("num")
        case_title = " ".join(hm.group("title").split())

        start = hm.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(plain)
        section_text = plain[start:end]
        body = section_text[hm.end() - hm.start():].strip()
        outcome, conditional, continued_to = _classify(body)

        local_dept = meta.dept or _detect_dept(section_text, dept_hint)

        page_start = page_for_offset(start)
        content_end = start + len(section_text.rstrip())
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
                # Nevada uses the location as the only "motion type" signal.
                motion_type=meta.location or "",
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
