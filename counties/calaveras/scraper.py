"""Calaveras County tentative-rulings scraper.

Calaveras keeps long static lists for case-management and civil law-and-motion
PDFs. Filenames vary by year and by upload location, so discovery keys off the
link text and the fact that the link target is a court-hosted PDF.

Parsing supports the two observed current layouts:

* Case-management calendars: date and time headers, followed by bare case
  number rows with wrapped party titles and disposition text.
* Law-and-motion calendars: title line, case number line, motion title, then a
  ruling body. These PDFs often rely on the source filename for the hearing
  date.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import pypdf

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION

BASE = "https://www.calaveras.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings/tentative-rulings-case-management",
    f"{BASE}/online-services/tentative-rulings/tentative-rulings-civil-law-and-motion-calendar",
]


def _division_from_page(page_url: str, text: str) -> str | None:
    haystack = f"{page_url} {text}".lower()
    if "case-management" in haystack or "cmc" in haystack:
        return "Case Management"
    if "civil-law" in haystack or "civil tentative" in haystack:
        return "Civil Law and Motion"
    return None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if not link.url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        text = link.text
        if "tentative" not in text.lower() and "cmc" not in text.lower():
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.calaveras.courts.ca.gov", "calaveras.courts.ca.gov"}:
            continue
        if not parsed.path.lower().startswith("/system/files/"):
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                division_hint=_division_from_page(source_page, text),
                link_text=text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)


# ============================================================ PARSE


CASE_NUMBER_LINE_RE = re.compile(
    r"^\s*(?:Case\s+No\.?\s*)?(?P<num>\d{2}[A-Z]{2,4}\d{4,6}|[A-Z]{1,4}\d{4,6})\b(?:[ \t]+(?P<rest>.*?))?\s*$",
    re.MULTILINE,
)
CASE_NUMBER_TOKEN_RE = re.compile(
    r"(?:\d{2}[A-Z]{2,4}\d{4,6}|[A-Z]{1,4}\d{4,6})\b",
    re.IGNORECASE,
)
LEGACY_TIME_CASE_RE = re.compile(
    r"^\s*(?P<time>\d{1,2}:\d{2}(?:\s*[AP]\.?\s*M\.?)?)\s+"
    r"(?P<num>\d{2}[A-Z]{2,4}\d{4,6}|[A-Z]{1,4}\d{4,6})\s+"
    r"(?P<motion>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
LEGACY_TENTATIVE_RE = re.compile(r"\bTENTATIVE\s+RULING:?", re.IGNORECASE)
LEGACY_PARTY_RE = re.compile(
    r"(?P<label>Ptff/Pet|Def/Res):\s*(?P<name>.*?)(?:\s+Atty:|$)",
    re.IGNORECASE,
)
LONG_DATE_RE = re.compile(
    r"\b(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
URL_DASH_DATE_RE = re.compile(r"(?<!\d)(?P<m>\d{1,2})[-_](?P<d>\d{1,2})[-_](?P<y>\d{2,4})(?!\d)")
URL_SINGLE_DIGIT_MDY_RE = re.compile(r"(?<!\d)(?P<m>[1-9])(?P<d>[1-9])(?P<y>20\d{2})(?!\d)")
URL_COMPACT_DATE_RE = re.compile(r"(?<!\d)(?P<m>\d{2})(?P<d>\d{2})(?P<y>20\d{2})(?!\d)")
URL_SHORT_COMPACT_DATE_RE = re.compile(r"(?<!\d)(?P<m>\d{1,2})(?P<d>\d{2})(?P<y>\d{2})(?!\d)")
URL_MONTH_NAME_DATE_RE = re.compile(
    r"(?P<month>january|february|march|april|may|june|july|august|september|october|november|december)"
    r"[-_](?P<d>\d{1,2})[-_](?P<y>\d{2,4})",
    re.IGNORECASE,
)
SECTION_RE = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}\s*[AP]\.?\s*M\.?\s*)?"
    r"(?P<section>(?:Civil|Family\s+Law)\s+Case\s+Management|Civil\s+Law\s+and\s+Motion)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")
CONTINUED_TO_RE = re.compile(
    r"(?:continued|set|scheduled)\s+(?:for|to|on)\s+"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
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

_BODY_START_RE = re.compile(
    r"\b(?:There\s+is|The\s+case|The\s+matter|All\s+Defendants|Plaintiff\s+|"
    r"Defendant\s+|Petitioner\s+|Respondent\s+|Appearances?\s+|Judgment\s+|"
    r"This\s+is|Now\s+before)\b",
    re.IGNORECASE,
)
_CMC_BODY_START_RE = re.compile(
    r"\b(?:The\s+next\s+Case\s+Management|This\s+matter|Filings\s+from|"
    r"Parties\s+(?:are|shall|must|have|request)|DROPPED\s+from|CONTINUED\s+to)\b",
    re.IGNORECASE,
)

TRAILING_CALENDAR_HEADER_RE = re.compile(
    r"(?im)^\s*\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*"
    r"(?:a\.?m\.?|p\.?m\.?)\s+Department\s+\d+\s*$"
)


def _parse_long_date(text: str) -> date | None:
    m = LONG_DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group("month").upper())
    if not month:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


def _parse_url_date(source_url: str) -> date | None:
    month_name = URL_MONTH_NAME_DATE_RE.search(source_url)
    if month_name:
        month = _MONTHS.get(month_name.group("month").upper())
        year = int(month_name.group("y"))
        if year < 100:
            year += 2000
        if month:
            try:
                return date(year, month, int(month_name.group("d")))
            except ValueError:
                pass
    single_digit = URL_SINGLE_DIGIT_MDY_RE.search(source_url)
    if single_digit:
        try:
            return date(
                int(single_digit.group("y")),
                int(single_digit.group("m")),
                int(single_digit.group("d")),
            )
        except ValueError:
            pass
    for pattern in (URL_DASH_DATE_RE, URL_COMPACT_DATE_RE, URL_SHORT_COMPACT_DATE_RE):
        m = pattern.search(source_url)
        if not m:
            continue
        year = int(m.group("y"))
        if year < 100:
            year += 2000
        try:
            return date(year, int(m.group("m")), int(m.group("d")))
        except ValueError:
            continue
    return None


def _section_name(raw: str) -> str:
    upper = raw.upper()
    if "FAMILY" in upper:
        return "Family Law Case Management"
    if "CASE MANAGEMENT" in upper:
        return "Civil Case Management"
    return "Civil Law and Motion"


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b", upper))
    has_granted = bool(re.search(r"\bGRANT(?:ED|S)?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(r"\bCONTINUED\s+TO\b|\bCONTINUED\s+OSC\b|\bIS\s+CONTINUED\b", upper))
    has_off_calendar = bool(re.search(r"\bOFF\s+CALENDAR\b|\bDROPPED\s+FROM\b|\bVACATED\b", upper))
    has_appearance = bool(re.search(r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:REQUIRED|NECESSARY)\b", upper))

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


def _is_title_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    if re.search(
        r"^(?:In\s+(?:The\s+)?Matter\s+of|In\s+re|Estate\s+of|Conservatorship\s+of|Guardianship\s+of)\b",
        s,
        re.IGNORECASE,
    ):
        return True
    upper = sum(1 for c in letters if c.isupper())
    if upper / len(letters) >= 0.70:
        return True
    if _BODY_START_RE.search(s):
        return False
    return bool(re.search(r"\bv(?:\.|s\.?)?\b", s, re.IGNORECASE))


def _plausible_inline_caption(title: str) -> bool:
    s = title.strip()
    if not s or len(s) > 220:
        return False
    return _is_title_line(s)


def _split_inline_title(rest: str, *, is_case_management: bool = False) -> tuple[str, str]:
    if not rest:
        return "", ""
    m = _BODY_START_RE.search(rest)
    if is_case_management:
        cmc_match = _CMC_BODY_START_RE.search(rest)
        if cmc_match and (m is None or cmc_match.start() < m.start()):
            m = cmc_match
    if not m:
        return rest.strip(), ""
    title = rest[: m.start()].strip()
    if not title:
        return "", rest[m.start():].strip()
    if not _plausible_inline_caption(title):
        return rest.strip(), ""
    return title, rest[m.start():].strip()


def _title_above(plain: str, anchor_start: int) -> str:
    lines: list[str] = []
    for line in reversed(plain[:anchor_start].splitlines()):
        s = line.strip()
        if not s:
            if lines:
                break
            continue
        if CASE_NUMBER_LINE_RE.match(s) or SECTION_RE.match(s):
            break
        if _is_title_line(s):
            lines.append(s)
            continue
        if lines:
            break
    lines.reverse()
    return " ".join(" ".join(lines).split())


def _split_block(
    anchor: re.Match[str],
    block: str,
    plain: str,
    *,
    is_case_management: bool = False,
) -> tuple[str, str, str, str]:
    rest = (anchor.group("rest") or "").strip()
    case_title = ""
    motion_type = ""
    body_lines: list[str] = []

    if not rest:
        case_title = _title_above(plain, anchor.start())
        lines = [line.strip() for line in block.splitlines()]
        idx = 0
        leading_title_lines: list[str] = []
        while idx < len(lines):
            s = lines[idx]
            if not s:
                idx += 1
                continue
            title_start, body_start = _split_inline_title(s, is_case_management=is_case_management)
            if is_case_management and title_start and body_start and _is_title_line(title_start):
                leading_title_lines.append(title_start)
                body_lines = [body_start, *[line for line in lines[idx + 1:] if line]]
                if case_title:
                    motion_type = " ".join(leading_title_lines)
                else:
                    case_title = " ".join(leading_title_lines)
                    motion_type = "Case Management Conference" if case_title else ""
                return case_title, motion_type, "\n".join(body_lines).strip(), "calaveras-lawmotion"
            if not _is_title_line(s):
                break
            leading_title_lines.append(s)
            idx += 1
        if case_title:
            motion_type = " ".join(leading_title_lines)
        else:
            case_title = " ".join(leading_title_lines)
            motion_type = "Case Management Conference" if case_title else ""
        body_lines = [line for line in lines[idx:] if line]
        return case_title, motion_type, "\n".join(body_lines).strip(), "calaveras-lawmotion"

    title_start, body_start = _split_inline_title(rest, is_case_management=is_case_management)
    title_lines = [title_start] if title_start else []
    title_above = _title_above(plain, anchor.start())
    if title_above and re.fullmatch(r"\([^)]{1,60}\)", title_start or ""):
        title_lines = [title_above]
        body_start = body_start or ""
    if body_start:
        body_lines.append(body_start)
    for line in block.splitlines():
        s = line.strip()
        if not s:
            continue
        if not body_lines and _is_title_line(s):
            title_lines.append(s)
            continue
        body_lines.append(s)
    case_title = " ".join(" ".join(title_lines).split())
    body = "\n".join(body_lines).strip()
    if is_case_management and not body:
        title_start, body_start = _split_inline_title(case_title, is_case_management=True)
        if body_start and title_start:
            case_title = title_start
            body = body_start
    return case_title, "Case Management Conference", body, "calaveras-cmc"


def _is_bare_companion_prefix(anchor: re.Match[str], plain: str) -> bool:
    """Skip the first number in a bare 'CASE and CASE' consolidated caption."""
    if (anchor.group("rest") or "").strip():
        return False
    after = plain[anchor.end(): anchor.end() + 120]
    return bool(re.match(rf"\s*(?:and|&)\s*\n\s*(?:Case\s+No\.?\s*)?{CASE_NUMBER_TOKEN_RE.pattern}", after, re.IGNORECASE))


def _companion_case_number(plain: str, anchor_start: int) -> str | None:
    prefix = plain[max(0, anchor_start - 160):anchor_start]
    m = re.search(
        rf"(?im)(?P<num>{CASE_NUMBER_TOKEN_RE.pattern})\s*\n\s*(?:and|&)\s*$",
        prefix,
    )
    return m.group("num").upper() if m else None


def _is_policy_number_anchor(anchor: re.Match[str], plain: str) -> bool:
    """Insurance policy IDs can look like legacy case numbers in CMC captions."""
    num = anchor.group("num").upper()
    if re.match(r"^(?:LMHO|LSI|ATRD)\d", num):
        return True
    prefix = plain[max(0, anchor.start() - 80):anchor.start()].upper()
    return "POLICY NUMBER" in prefix and "\n\n" not in prefix.split("POLICY NUMBER", 1)[-1]


def _trim_trailing_next_calendar_header(plain: str, start: int, end: int) -> int:
    """Remove a next page's date/dept caption that precedes the next case number."""
    segment = plain[start:end]
    trimmed = end
    for match in TRAILING_CALENDAR_HEADER_RE.finditer(segment):
        if match.start() > 40:
            trimmed = start + match.start()
    return trimmed


def _ruling_id(source_sha256: str, index: int, case_number: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{index}:{case_number}".encode("utf-8")).hexdigest()[:32]


def _legacy_party_title(block: str) -> str:
    parties: dict[str, str] = {}
    for match in LEGACY_PARTY_RE.finditer(block):
        label = match.group("label").lower()
        name = " ".join(match.group("name").replace(";", ",").split()).strip(" ,")
        if name:
            parties[label] = name
    plaintiff = parties.get("ptff/pet")
    defendant = parties.get("def/res")
    if plaintiff and defendant:
        return f"{plaintiff} v. {defendant}"
    return plaintiff or defendant or ""


def _legacy_motion_text(match: re.Match[str], block: str) -> str:
    lines = [" ".join(match.group("motion").split())]
    after_first_line = block.splitlines()[1:]
    for line in after_first_line:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^\d{1,2}/\d{1,2}/\d{4}\b", s):
            break
        if re.match(r"^(?:Ptff/Pet|Def/Res):", s, re.IGNORECASE):
            break
        if LEGACY_TENTATIVE_RE.search(s):
            break
        lines.append(s)
    return " ".join(" ".join(lines).split())


def _detect_legacy_division(header_text: str, hint: str | None) -> str:
    upper = header_text.upper()
    if "PROBATE" in upper:
        return "Probate Law and Motion"
    return hint or "Civil Law and Motion"


def _parse_legacy_time_rows(
    plain: str,
    offsets: list[int],
    hearing_date: date,
    source_sha256: str,
    source_url: str,
    dept_hint: str | None,
    division_hint: str | None,
) -> list[Ruling]:
    matches = list(LEGACY_TIME_CASE_RE.finditer(plain))
    if not matches:
        return []

    rulings: list[Ruling] = []
    for i, match in enumerate(matches):
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(plain)
        block = plain[match.start():block_end]
        tentative = LEGACY_TENTATIVE_RE.search(block)
        if not tentative:
            continue
        body = block[tentative.end():].strip()
        if not body:
            continue
        case_number = match.group("num").upper()
        motion_type = _legacy_motion_text(match, block)
        case_title = _legacy_party_title(block)
        outcome, conditional, continued_to = _classify(body)
        page_start = _page_for_offset(offsets, match.start())
        page_end = max(page_start, _page_for_offset(offsets, max(match.start(), block_end - 1)))
        division = _detect_legacy_division(plain[:match.start()], division_hint)

        rulings.append(
            Ruling(
                ruling_id=_ruling_id(source_sha256, len(rulings) + 1, case_number),
                county=COUNTY_SLUG,
                division=division,
                dept=dept_hint,
                hearing_date=hearing_date,
                ruling_index=len(rulings) + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text="",
                full_text=block.strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style="calaveras-legacy-time-row",
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

    pages = _strip_pages(raw_pages)
    plain, offsets = _join_pages(pages)
    hearing_date = _parse_url_date(source_url) or _parse_long_date(plain[:1000])
    if hearing_date is None:
        return []

    anchors = [
        anchor for anchor in CASE_NUMBER_LINE_RE.finditer(plain)
        if (anchor.group("rest") or "").strip().lower() not in {"and", "&"}
        and not _is_bare_companion_prefix(anchor, plain)
        and not _is_policy_number_anchor(anchor, plain)
    ]
    if not anchors:
        return _parse_legacy_time_rows(
            plain,
            offsets,
            hearing_date,
            source_sha256,
            source_url,
            dept_hint,
            division_hint,
        )

    rulings: list[Ruling] = []
    current_division = division_hint or "Civil Law and Motion"
    for i, anchor in enumerate(anchors):
        region_start = anchors[i - 1].end() if i > 0 else 0
        region = plain[region_start:anchor.start()]
        for sm in SECTION_RE.finditer(region):
            current_division = _section_name(sm.group("section"))

        raw_block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block_end = _trim_trailing_next_calendar_header(plain, anchor.start(), raw_block_end)
        is_case_management = (
            "case management" in (current_division or "").lower()
            or "cmc" in source_url.lower()
        )
        case_title, motion_type, body, style = _split_block(
            anchor,
            plain[anchor.end():block_end],
            plain,
            is_case_management=is_case_management,
        )
        if not body and not motion_type:
            continue
        outcome, conditional, continued_to = _classify(body or motion_type)
        page_start = _page_for_offset(offsets, anchor.start())
        page_end = max(page_start, _page_for_offset(offsets, max(anchor.start(), block_end - 1)))
        case_number = anchor.group("num").upper()
        companion_number = _companion_case_number(plain, anchor.start())
        if companion_number:
            case_number = f"{companion_number} / {case_number}"

        rulings.append(
            Ruling(
                ruling_id=_ruling_id(source_sha256, len(rulings) + 1, case_number),
                county=COUNTY_SLUG,
                division=current_division,
                dept=dept_hint,
                hearing_date=hearing_date,
                ruling_index=len(rulings) + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=body,
                conditional=conditional,
                continued_to=continued_to,
                body_text=body,
                full_text=plain[anchor.start():block_end].strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=style,
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
