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
    r"(?<![\d-])30\s*-\s*20\d{2}\s*-\s*\d{6,9}(?:\s*-\s*[A-Z]{2,4}){0,4}"  # modern with suffix
    r"|\b\d{2}[A-Z]\d{6}\b"                                          # family law
    r"|\b20\d{2}\s*[-–]\s*\d{7,8}\b"                                  # reduced year-prefixed
    r"|\b\d{2}\s*[-–]\s*\d{7,8}\b"                                    # reduced two-digit-year
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
    r"|Date:?\s*(?P<m5>[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})"
    r"|Hearing\s+Date:?\s*(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?"
    r"(?P<m6>\d{1,2}/\d{1,2}/\d{2,4})"
    r"|TENTATIVE\s+RULINGS\s*(?:FOR\s+DEPARTMENT\s+[A-Z]{1,3}\d{1,3})?\s*\n+\s*"
    r"(?P<m2>[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})"
    r"|TENTATIVE\s+RULINGS\s*(?:FOR\s+DEPARTMENT\s+[A-Z]{1,3}\d{1,3})?\s*\n+\s*"
    r"(?P<m4>\d{1,2}/\d{1,2}/\d{2,4})"
    r"|(?P<m3>[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})",
    re.IGNORECASE,
)
SECTION_DATE_RE = re.compile(
    r"TENTATIVE\s+RULINGS(?:\s+FOR\s+DEPARTMENT\s+[A-Z]{1,3}\d{1,3})?\s*"
    r"(?:\n+\s*)?(?P<date>[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})",
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
    mm = re.match(r"([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})", d_str)
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
        explicit = m.group("m1") or m.group("m5") or m.group("m6") or m.group("m2") or m.group("m4")
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


def _date_for_offset(plain: str, offset: int, fallback: date | None) -> date | None:
    hearing_date = fallback
    for match in SECTION_DATE_RE.finditer(plain, 0, offset):
        parsed = _coerce_header_date(match.group("date"))
        if parsed is not None:
            hearing_date = parsed
    return hearing_date


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


def _normalize_case_number(num: str) -> str:
    num = num.strip().replace("–", "-")
    num = re.sub(r"\s*-\s*", "-", num)
    num = re.sub(r"\s+", "", num)
    return re.sub(r"-+", "-", num).rstrip("-")


def _is_header_or_boilerplate_line(line: str) -> bool:
    return bool(re.search(
        r"^(?:#\s*Case\s+Name\s+Tentative|Court\s+Room|Date:|Superior\s+Court|"
        r"County\s+of\s+Orange|TENTATIVE\s+RULINGS|HON\.?|Judge\b|Commissioner\b|"
        r"Temporary\s+Judge\b|DEPARTMENT\b)",
        line,
        re.IGNORECASE,
    ))


def _title_before_case_span(plain: str, case_start: int) -> tuple[str, int]:
    """Extract Orange table case names that appear before the case number."""
    title_lines: list[str] = []
    title_start = case_start
    pos = len(plain[:case_start])
    for raw in reversed(plain[:case_start].splitlines(keepends=True)):
        pos -= len(raw)
        line = raw.rstrip("\r\n")
        s = line.strip()
        if not s:
            if title_lines:
                break
            continue
        if _is_header_or_boilerplate_line(s):
            if title_lines:
                break
            continue
        if CASE_NUMBER_RE.search(s):
            break
        has_row_prefix = bool(re.match(r"^\d{1,3}\.?\s+", s))
        if title_lines and not has_row_prefix and re.match(
            r"^(?:Accordingly|Attorney|Clerk|Counsel|Defendant|If|IT\s+IS|"
            r"LWDA|On|Plaintiff|Petitioner|Respondent|Supplemental|The\s+Court)\b",
            s,
            re.IGNORECASE,
        ):
            break
        s = re.sub(r"^\d{1,3}\.?\s+", "", s).strip()
        s = re.sub(r"[\(;]?\s*20\d{2}\s*[-–]?\s*$", "", s).strip(" ;,(")
        if not s or re.fullmatch(r"[\W_]+", s):
            continue
        title_lines.append(s)
        title_start = pos
        if has_row_prefix:
            break
        if len(title_lines) >= 4:
            break
    title_lines.reverse()
    return " ".join(" ".join(title_lines).split()), title_start


def _title_before_case(plain: str, case_start: int) -> str:
    return _title_before_case_span(plain, case_start)[0]


def _is_useful_before_case_title(title: str) -> bool:
    """Reject row indexes/body fragments that sit before a table case number."""
    s = " ".join(title.split()).strip(" ;,")
    if not s:
        return False
    if re.fullmatch(r"\d{1,3}\.?", s):
        return False
    if len(s) > 220:
        return False
    if _is_header_or_boilerplate_line(s):
        return False
    if TITLE_ONLY_DISPOSITION_RE.search(s):
        return False
    if re.match(
        r"^(?:Accordingly|All|As|Based|Code|For|Here|If|On|Thus)\b"
        r"|^(?:The\s+Court|This\s+(?:matter|case|action))\b"
        r"|^(?:Plaintiff|Defendant|Petitioner|Respondent)\s+"
        r"(?:moves?|contends?|argues?|requests?|seeks?|filed|is|are|shall|must)\b",
        s,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"\b(?:Probate|Elder\s+Abuse)\b", s, re.IGNORECASE):
        return True
    return bool(re.search(r"[A-Za-z]", s))


def _row_start_for_case_match(plain: str, match: re.Match[str]) -> int:
    """Include a same-line row index in the next row, not the prior body."""
    line_start = plain.rfind("\n", 0, match.start()) + 1
    prefix = plain[line_start:match.start()]
    if re.fullmatch(r"\s*\d{1,3}\.?\s*", prefix):
        return line_start
    before_title, before_title_start = _title_before_case_span(plain, match.start())
    if before_title and _is_useful_before_case_title(before_title):
        return before_title_start
    return match.start()


def _clean_block_lines(block: str) -> list[str]:
    lines = block.splitlines()
    out: list[str] = []
    for j, line in enumerate(lines):
        s = line.strip()
        if j == 0:
            s = s.lstrip(");, ")
        out.append(s)
    return out


def _looks_like_motion_line(line: str) -> bool:
    if not line or len(line) > 180:
        return False
    if line.endswith("."):
        return False
    upper = line.upper()
    if re.match(r"^[A-Z0-9 ,/&'.\-:()]{6,180}$", line) and " V. " not in upper and " VS " not in upper:
        return True
    return bool(re.search(
        r"\b(?:Motion|Demurrer|Petition|OSC|Order\s+to\s+Show\s+Cause|Application|Request|"
        r"Final\s+Accounting|Case\s+Management\s+Conference|CMC)\b",
        line,
        re.IGNORECASE,
    ))


def _looks_like_title_only_row(rest: str) -> bool:
    s = rest.strip()
    if not s or len(s) > 160:
        return False
    if re.match(r"^(?:The|Plaintiff|Defendant|Petitioner|Respondent|This|Motion)\b", s):
        return False
    return bool(re.search(
        r"(?:\bv\.|\bvs\.?|\bversus\b|\bEstate\s+of\b|\bTrust\b|\bConservatorship\b|\bGuardianship\b|\bIn\s+re\b|\bMatter\s+of\b)",
        s,
        re.IGNORECASE,
    ))


def _looks_like_title_continuation(line: str, title_parts: list[str]) -> bool:
    s = line.strip()
    if not s or len(s) > 120:
        return False
    if CASE_NUMBER_RE.search(s):
        return False
    if re.match(
        r"^(?:The|Plaintiff|Defendant|Petitioner|Respondent|Applicant|Counsel|Court|This|Motion|Demurrer|Application)\b",
        s,
        re.IGNORECASE,
    ):
        return False
    joined_title = " ".join(title_parts)
    needs_opponent = bool(re.search(r"(?:\bv\.|\bvs\.?|\bversus)\s*$", joined_title, re.IGNORECASE))
    if s.endswith(".") and title_parts and not needs_opponent:
        return False
    return True


def _split_inline_title_body(rest: str) -> tuple[str, str]:
    m = re.match(
        r"(?P<title>.+?\b(?:v\.|vs\.?|versus)\s+[\w&',.\- ]+?)\s+"
        r"(?P<body>(?:The|Plaintiff|Defendant|Petitioner|Respondent|Applicant|Motion|Demurrer|Application)\b.+)",
        rest,
        re.IGNORECASE,
    )
    if not m:
        return rest.strip(), ""
    return m.group("title").strip(" ;,"), m.group("body").strip()


TITLE_ONLY_ROW_RE = re.compile(r"^\s*(?P<idx>\d{1,3})\s+(?P<rest>[^\n]+?)\s*$", re.MULTILINE)
TITLE_ONLY_DISPOSITION_RE = re.compile(
    r"\b(?:GRANTED|DENIED|SUSTAINED|OVERRULED|CONTINUED|CONT\.|"
    r"OFF[- ]CALENDAR|VACATED|NO\s+TENTATIVE|TENTATIVE\s+RULING|"
    r"ORDERED|APPROVED|DISMISSED)\b",
    re.IGNORECASE,
)


def _parse_title_only_rows(
    plain: str,
    meta: _DocMeta,
    page_for_offset,
    source_url: str,
    source_sha256: str,
) -> list[Ruling]:
    matches = [
        m for m in TITLE_ONLY_ROW_RE.finditer(plain)
        if m.group("rest").strip()
    ]
    if not matches:
        return []

    rulings: list[Ruling] = []
    for pos, match in enumerate(matches):
        row_index = int(match.group("idx"))
        row_start = match.start()
        row_end = matches[pos + 1].start() if pos + 1 < len(matches) else len(plain)
        row_text = plain[row_start:row_end].strip()
        lines = [line.strip() for line in row_text.splitlines()]
        if not lines:
            continue
        first_line = re.sub(r"^\d{1,3}\s+", "", lines[0]).strip()
        title, inline_body = _split_inline_title_body(first_line)
        title_parts = [title] if title else []
        body_lines: list[str] = [inline_body] if inline_body else []
        body_started = bool(inline_body)

        for line in lines[1:]:
            if not line:
                if body_started:
                    body_lines.append(line)
                continue
            if not body_started and _looks_like_title_continuation(line, title_parts):
                title_parts.append(line)
                continue
            body_started = True
            body_lines.append(line)

        case_title = " ".join(" ".join(title_parts).split()).strip(" ;,")
        body = "\n".join(body_lines).strip()
        if not case_title or not body or not _looks_like_title_only_row(case_title):
            continue

        hearing_date = _date_for_offset(plain, row_start, meta.hearing_date)
        if hearing_date is None:
            continue
        outcome, conditional, continued_to = _classify(body)
        page_start = page_for_offset(row_start)
        content_end = row_start + len(plain[row_start:row_end].rstrip())
        page_end = max(page_start, page_for_offset(max(row_start, content_end - 1)))
        ruling_id = hashlib.sha256(
            f"{source_sha256}:title-only:{row_index}:{case_title}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=meta.division,
                dept=meta.dept,
                hearing_date=hearing_date,
                ruling_index=row_index,
                case_number="",
                case_title=case_title,
                motion_type="",
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text=meta.judge or "",
                judge=meta.judge,
                full_text=row_text,
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=f"{meta.style}-title-only",
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.now(UTC),
            )
        )

    if not any(
        TITLE_ONLY_DISPOSITION_RE.search(f"{r.outcome_text}\n{r.full_text}")
        for r in rulings
    ):
        return []

    return rulings


def _split_motion_and_body_after_title(lines: list[str]) -> tuple[str, str]:
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return "", ""
    first = lines[i].strip()
    if _looks_like_motion_line(first):
        j = i + 1
        while j < len(lines) and lines[j].strip() and _looks_like_motion_line(lines[j].strip()):
            first = f"{first} {lines[j].strip()}"
            j += 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        return " ".join(first.split()), "\n".join(lines[j:]).strip()
    return "", "\n".join(lines[i:]).strip()


def _nonblank_before(text: str, offset: int, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for line in reversed(text[:offset].splitlines()):
        s = line.strip()
        if not s:
            if lines:
                break
            continue
        lines.append(s)
        if len(lines) >= limit:
            break
    lines.reverse()
    return lines


def _nonblank_after(text: str, offset: int, limit: int = 4) -> list[str]:
    lines: list[str] = []
    for line in text[offset:].splitlines():
        s = line.strip()
        if not s:
            if lines:
                break
            continue
        lines.append(s)
        if len(lines) >= limit:
            break
    return lines


def _is_probable_case_anchor(plain: str, match: re.Match[str]) -> bool:
    line_start = plain.rfind("\n", 0, match.start()) + 1
    line_end = plain.find("\n", match.end())
    if line_end == -1:
        line_end = len(plain)
    line = plain[line_start:line_end]
    prefix = plain[line_start:match.start()]
    suffix = plain[match.end():line_end]
    line_without_case = f"{prefix}{suffix}".strip(" ;,.-")

    score = 0
    if not line_without_case:
        score += 12
    if re.match(r"^\s*\d{1,3}\.?\s+", prefix):
        score += 8
    prev_lines = _nonblank_before(plain, line_start)
    if any(re.match(r"^\d{1,3}\.?\s+\S", line) for line in prev_lines[-4:]):
        score += 8
    if any(_looks_like_motion_line(line) for line in _nonblank_after(plain, line_end)[:2]):
        score += 3
    if re.search(r"\bCase\s+No\.?\s*$", prefix[-40:], re.IGNORECASE):
        score -= 8
    if len(line.strip()) > 140 and not re.match(r"^\s*\d{1,3}\.?\s+", line):
        score -= 5
    return score >= 8


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

    # Each row-anchor case-number occurrence is a ruling. Body text often
    # cites related case numbers, so prefer standalone/table-row occurrences
    # when the packet exposes them.
    matches = list(CASE_NUMBER_RE.finditer(plain))
    if not matches:
        return _parse_title_only_rows(
            plain,
            meta=meta,
            page_for_offset=page_for_offset,
            source_url=source_url,
            source_sha256=source_sha256,
        )

    anchor_matches = [m for m in matches if _is_probable_case_anchor(plain, m)]
    if anchor_matches:
        matches = anchor_matches

    # Filter out 8-digit ZIP-code lookalikes; probate IDs start with 0.
    deduped: list[re.Match[str]] = []
    for m in matches:
        num = m.group("num")
        # Skip pure 8-digit numbers that aren't probate-style (don't start with 0).
        if re.fullmatch(r"\d{8}", num) and not num.startswith("0"):
            continue
        deduped.append(m)
    if not deduped:
        return _parse_title_only_rows(
            plain,
            meta=meta,
            page_for_offset=page_for_offset,
            source_url=source_url,
            source_sha256=source_sha256,
        )

    rulings: list[Ruling] = []
    for i, cm in enumerate(deduped):
        case_number = _normalize_case_number(cm.group("num"))
        case_start = cm.start()
        case_end = cm.end()

        # Block runs to the next case-number.
        block_end = _row_start_for_case_match(plain, deduped[i + 1]) if i + 1 < len(deduped) else len(plain)
        block = plain[case_end:block_end].strip()
        block_lines = _clean_block_lines(block)
        before_title, before_title_start = _title_before_case_span(plain, case_start)
        if not _is_useful_before_case_title(before_title):
            before_title = ""
            row_start = case_start
        else:
            row_start = before_title_start

        title_lines: list[str] = []
        body_idx = 0
        motion_type = ""
        if before_title:
            case_title = before_title
            motion_type, body = _split_motion_and_body_after_title(block_lines)
        else:
            for j, s in enumerate(block_lines):
                s = s.strip()
                if not s:
                    if title_lines:
                        body_idx = j + 1
                        break
                    continue
                if _looks_like_motion_line(s) and title_lines:
                    motion_type = s
                    body_idx = j + 1
                    break
                title_lines.append(s)
                if len(title_lines) >= 3:
                    body_idx = j + 1
                    break

            case_title = " ".join(" ".join(title_lines).split()).strip(" ;,")
            body = "\n".join(block_lines[body_idx:]).strip()

        outcome, conditional, continued_to = _classify(body or motion_type)
        hearing_date = _date_for_offset(plain, case_start, meta.hearing_date)
        if hearing_date is None:
            continue

        page_start = page_for_offset(row_start)
        content_end = case_end + len(plain[case_end:block_end].rstrip())
        page_end = max(page_start, page_for_offset(max(row_start, content_end - 1)))

        ruling_id = hashlib.sha256(
            f"{source_sha256}:{i + 1}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=meta.division,
                dept=meta.dept,
                hearing_date=hearing_date,
                ruling_index=i + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text=meta.judge or "",
                judge=meta.judge,
                full_text=plain[row_start:block_end].strip(),
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
