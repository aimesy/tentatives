"""Orange County tentative-rulings scraper.

Discovery
---------
Orange publishes index pages for civil, family, and probate/mental-health
tentatives. Each index links to stable current PDFs, usually named
`*rulings.pdf`. History for those stable URLs is a Wayback problem rather than
a live-site pagination problem.

Parsing
-------
Orange uses three closely-related per-dept PDF styles:

  Civil (~33 PDFs):
    Page-1 header:  TENTATIVE RULINGS / DEPT <CMx>/<Cxx> / Judge <NAME>
    Per ruling:     "<idx>.  <CASE_NUMBER>  <CASE_TITLE>  <BODY>"
                    (table layout, fields run together in extracted text)

  Family Law (~2 PDFs):
    Page-1 header:  CENTRAL JUSTICE CENTER / DEPARTMENT C<NN> / Judge <NAME>
    Same per-ruling layout as civil.

  Probate (~6 PDFs):
    Page-1 header:  Superior Court of the State of California / County of Orange
                    TENTATIVE RULINGS FOR DEPARTMENT <CMx>
                    Date: MM/DD/YY
    Per ruling:     "<idx>  <CASE_NAME>  /  <CASE_NUMBER>  /  MOTION TYPE  /  <BODY>"
                    (also tabular, often with the case-number on its own line)

Case-number formats:
  30-2025-01523808[-CU-PO-CJC]   (modern, may include suffix codes)
  01298596, 01184189             (probate / older 8-digit form)
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

BASE = "https://www.occourts.org"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings/civil-tentative-rulings",
    f"{BASE}/online-services/tentative-rulings/family-law-tentative-rulings",
    f"{BASE}/online-services/tentative-rulings/probate-tentative-rulings",
]
ALLOWED_SOURCE_HOSTS = {"live-jcc-oc.pantheonsite.io"}


def _division_from_page(page_url: str) -> str | None:
    path = urlparse(page_url).path.lower()
    if "family-law" in path:
        return "Family Law"
    if "probate" in path:
        return "Probate"
    if "civil" in path:
        return "Civil"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if ".pdf" not in link.url.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {
            "www.occourts.org",
            "occourts.org",
            "live-jcc-oc.pantheonsite.io",
        }:
            continue
        if "/tentative-rulings/" not in parsed.path.lower():
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_from_page(source_page),
                link_text=link.text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)


# ============================================================ PARSE


# Case-number formats:
#   30-2025-01523808[-CU-PO-CJC] (modern; suffix may be on the next line)
#   25D006297                     (family law)
#   01298596 / 01184189           (probate 8-digit)
_CASE_NUMBER_INNER = (
    r"(?<![\d-])30-20\d{2}-\d{6,9}(?:-?\s*(?:[A-Z]{2,4}-){1,3}[A-Z]{2,4})?"  # modern with suffix
    r"|\b\d{2}[A-Z]\d{6}\b"                                          # family law
    r"|\b\d{8}\b"                                                    # probate 8-digit
)
CASE_NUMBER_RE = re.compile(rf"(?P<num>{_CASE_NUMBER_INNER})")

# Header bits.
HEADER_DEPT_RE = re.compile(
    r"(?:DEPT|DEPARTMENT)\s+(?P<dept>[A-Z]{1,3}\d{1,3})\b",
    re.IGNORECASE,
)
HEADER_DATE_RE = re.compile(
    r"Date:?\s*(?P<m1>\d{1,2}/\d{1,2}/\d{2,4})"
    r"|TENTATIVE\s+RULINGS\s*(?:FOR\s+DEPARTMENT\s+[A-Z]{1,3}\d{1,3})?\s*\n+\s*"
    r"(?P<m2>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})"
    r"|(?P<m3>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
JUDGE_RE = re.compile(
    r"(?:HON\.?\s+|Judge\s+)([A-Z][A-Za-z .\-]+?)(?:\s*$|,)",
    re.MULTILINE,
)

# Page-number lines.
PAGE_NUMBER_RE = re.compile(r"^\s*Page\s+\d+(?:\s+of\s+\d+)?\s*$", re.IGNORECASE)

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}

# Continued-to extractor.
CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE | re.DOTALL,
)


def _coerce_header_date(d_str: str) -> date | None:
    d_str = d_str.strip()
    if "/" in d_str:
        parts = d_str.split("/")
        try:
            month = int(parts[0])
            day = int(parts[1])
            year = int(parts[2])
            if year < 100:
                year += 2000
            return date(year, month, day)
        except (ValueError, IndexError):
            return None
    mm = re.match(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", d_str)
    if mm:
        mo = mm.group(1).upper()
        if mo in _MONTHS:
            try:
                return date(int(mm.group(3)), _MONTHS[mo], int(mm.group(2)))
            except ValueError:
                return None
    return None


def _parse_date(text: str) -> date | None:
    # Prefer an explicit "Date:" / labeled hearing date (m1/m2) over a bare
    # "Month D, YYYY" (m3), which can be a stray date elsewhere in the header.
    bare: date | None = None
    for m in HEADER_DATE_RE.finditer(text):
        explicit = m.group("m1") or m.group("m2")
        d_str = explicit or m.group("m3")
        if not d_str:
            continue
        parsed = _coerce_header_date(d_str)
        if parsed is None:
            continue
        if explicit:
            return parsed
        if bare is None:
            bare = parsed
    return bare


def _detect_division(header_text: str, hint: str | None) -> str | None:
    upper = header_text.upper()
    if "PROBATE" in upper:
        return "Probate"
    if "FAMILY" in upper:
        return "Family Law"
    if "CIVIL" in upper or "LAW AND MOTION" in upper:
        return "Civil"
    return hint


def _detect_dept(header_text: str, hint: str | None) -> str | None:
    m = HEADER_DEPT_RE.search(header_text)
    if m:
        return m.group("dept").upper()
    return hint


def _detect_style(header_text: str) -> str:
    upper = header_text.upper()
    if "PROBATE" in upper:
        return "orange-probate"
    if "FAMILY" in upper or "CENTRAL JUSTICE CENTER" in upper:
        return "orange-family"
    return "orange-civil"


def _detect_judge(header_text: str) -> str | None:
    m = JUDGE_RE.search(header_text)
    return " ".join(m.group(1).split()) if m else None


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    division: str | None
    dept: str | None
    style: str
    judge: str | None


def _extract_doc_meta(
    full_text: str, dept_hint: str | None, division_hint: str | None
) -> _DocMeta:
    # Civil/family PDFs announce the date on page 2 after the per-dept
    # boilerplate; allow a generous head window before the first case-number.
    cn_match = CASE_NUMBER_RE.search(full_text)
    head = full_text[:cn_match.start()] if cn_match else full_text[:5000]
    division = _detect_division(head, division_hint)
    dept = _detect_dept(head, dept_hint)
    return _DocMeta(
        hearing_date=_parse_date(head),
        division=division,
        dept=dept,
        style=_detect_style(head),
        judge=_detect_judge(head),
    )


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
        r"\bCONTINUED\s+TO\b|\bMATTER\s+IS\s+CONTINUED\b|\bCONTINUES\s+THE\b",
        upper,
    ))
    has_appearance = bool(re.search(
        r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:NECESSARY|REQUIRED)\b"
        r"|\bORDERED\s+TO\s+APPEAR\b"
        r"|\bPARTIES?\s+(?:ARE\s+)?(?:DIRECTED|REQUESTED)\s+TO\s+APPEAR\b",
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

    full_text = "\n\n".join(raw_pages)
    meta = _extract_doc_meta(full_text, dept_hint, division_hint)
    if meta.hearing_date is None:
        return []

    # Build offsets so we can map case-number occurrences back to page numbers.
    joined_parts: list[str] = []
    page_offsets: list[int] = []
    cursor = 0
    SEP = "\n\n"
    for p in raw_pages:
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

    # Each unique case-number occurrence is a ruling.
    matches = list(CASE_NUMBER_RE.finditer(plain))
    if not matches:
        return []

    # De-dupe by normalised case-number, first occurrence wins. Filter out
    # 8-digit ZIP-code lookalikes; probate IDs start with 0.
    seen: set[str] = set()
    deduped: list[re.Match[str]] = []
    for m in matches:
        num = m.group("num")
        # Skip pure 8-digit numbers that aren't probate-style (don't start with 0).
        if re.fullmatch(r"\d{8}", num) and not num.startswith("0"):
            continue
        if num in seen:
            continue
        seen.add(num)
        deduped.append(m)
    if not deduped:
        return []

    rulings: list[Ruling] = []
    for i, cm in enumerate(deduped):
        case_number = re.sub(r"\s+", "-", cm.group("num").strip()).rstrip("-")
        # Collapse double dashes that result from "-\nCU-PO-CJC" -> "-CU-PO-CJC".
        case_number = re.sub(r"-+", "-", case_number)
        case_start = cm.start()
        case_end = cm.end()

        # Block runs to the next case-number.
        block_end = deduped[i + 1].start() if i + 1 < len(deduped) else len(plain)
        block = plain[case_end:block_end].strip()

        # Title: take up to the first all-caps motion-type line or 2 lines.
        # Strip leading separators.
        block_lines = block.splitlines()
        title_lines: list[str] = []
        body_idx = 0
        motion_type = ""
        for j, line in enumerate(block_lines):
            s = line.strip()
            if not s:
                if title_lines:
                    body_idx = j + 1
                    break
                continue
            # All-caps motion-type line.
            if (
                re.match(r"^[A-Z0-9 ,/&'.\-:()]{6,150}$", s)
                and not s.endswith(".")
                and "vs" not in s.lower()
                and " v. " not in s.lower()
            ):
                motion_type = s
                body_idx = j + 1
                break
            title_lines.append(s)
            if len(title_lines) >= 3:
                body_idx = j + 1
                break

        case_title = " ".join(" ".join(title_lines).split())
        body = "\n".join(block_lines[body_idx:]).strip()

        outcome, conditional, continued_to = _classify(body or motion_type)

        page_start = page_for_offset(case_start)
        content_end = case_end + len(plain[case_end:block_end].rstrip())
        page_end = max(page_start, page_for_offset(max(case_start, content_end - 1)))

        ruling_id = hashlib.sha256(
            f"{source_sha256}:{i + 1}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=meta.division,
                dept=meta.dept,
                hearing_date=meta.hearing_date,
                ruling_index=i + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text=meta.judge or "",
                full_text=plain[case_start:block_end].strip(),
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
