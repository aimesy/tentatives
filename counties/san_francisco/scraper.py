"""San Francisco Unified Family Court tentative-rulings scraper.

Discovery
---------
The attached UFC page at webapps.sftc.org lists current and previous family
law tentative-ruling PDFs for departments 403, 404, and 414. This module
discovers those PDFs for capture. The main San Francisco civil archive remains
in `aimesy/sfsc`.

Parsing
-------
San Francisco UFC PDFs are pleading-paper documents with line numbers (1-29)
running down the left of every page. Each PDF contains the day's calendar for
one department; rulings are stacked one per ruling block:

  SUPERIOR COURT OF CALIFORNIA
  COUNTY OF SAN FRANCISCO
  UNIFIED FAMILY COURT
  <PETITIONER>,        )
   Petitioner          )
   VS.                 )   Case Number: FDI-22-797259
  <RESPONDENT>,        )   Hearing Date: May 12, 2026
   Respondent          )   Hearing Time: 9:00 AM
                       )   Department: 404
                       )   Presiding: <JUDGE>

  <MOTION TYPE>                       (all caps, one line)
  TENTATIVE RULING
  <body...>

Case-number formats: FDI-22-797259, FDV-25-818547 (FDI = dissolution,
FDV = domestic violence; sometimes other FXX prefixes).
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

BASE = "https://webapps.sftc.org/ufctr/ufctr.dll"
LANDING_PAGES = [BASE]

_DEPT_RE = re.compile(r"(?:Dept(?:artment)?\s*|/Dept%20|/Dept\s*)(\d{3})", re.IGNORECASE)


def _dept_from(url: str, text: str) -> str | None:
    decoded = f"{url} {text}"
    m = _DEPT_RE.search(decoded)
    return m.group(1) if m else None


def discover_live(html: str, page_url: str | None = None, base_url: str = BASE) -> list[PdfRef]:
    source_page = page_url or base_url
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if not link.url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() != "webapps.sftc.org":
            continue
        path = parsed.path.lower()
        if "/ufctr/files/" not in path or "tentative" not in path:
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                dept_hint=_dept_from(url, link.text),
                division_hint="Family Law",
                link_text=link.text,
                source_page_url=source_page,
            )
        )
    return unique_refs(refs)


# ============================================================ PARSE


# Case-number anchor.
CASE_NUMBER_ANCHOR_RE = re.compile(
    r"Case\s+Number:?\s+(?P<num>F[A-Z]{1,3}-?\d{2,4}-\d{4,8})",
    re.IGNORECASE,
)

# Per-block metadata regexes.
HEARING_DATE_RE = re.compile(
    r"Hearing\s+Date:?\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
DEPARTMENT_RE = re.compile(r"Department:?\s+(?P<dept>\d{2,4})", re.IGNORECASE)
PRESIDING_RE = re.compile(r"Presiding:?\s+(?P<judge>[A-Z][A-Za-z .\-]+?)(?:\n|$)", re.IGNORECASE)
HEARING_TIME_RE = re.compile(r"Hearing\s+Time:?\s+(?P<time>\d{1,2}:\d{2}\s*[APMapm]+)", re.IGNORECASE)

# Tentative ruling marker — at the start of the disposition.
TENTATIVE_RULING_ANCHOR_RE = re.compile(
    r"^\s*TENTATIVE\s+RULING\s*$", re.MULTILINE | re.IGNORECASE
)

# Pleading-paper line-number lines: "1\n2\n3..." or with trailing spaces.
LINE_NUMBER_ONLY_RE = re.compile(r"^\s*\d{1,2}\s*$")

_MONTHS = {
    m.upper(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"],
        start=1,
    )
}

CONTINUED_TO_RE = re.compile(
    r"continued\s+to\s+"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE | re.DOTALL,
)


def _parse_date(s: str) -> date | None:
    m = re.match(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", s)
    if m:
        mo = m.group(1).upper()
        if mo in _MONTHS:
            try:
                return date(int(m.group(3)), _MONTHS[mo], int(m.group(2)))
            except ValueError:
                pass
    return None


def _strip_pleading_lines(text: str) -> str:
    """Drop pure 1-2 digit pleading-paper line numbers."""
    return "\n".join(l for l in text.splitlines() if not LINE_NUMBER_ONLY_RE.match(l))


def _classify(text: str) -> tuple[str, bool, date | None]:
    upper = text.upper()
    conditional = "ABSENT OBJECTION" in upper
    has_denied = bool(re.search(
        r"\bDEN(?:IED|IES|Y)\b|\bDISMISS(?:ED|ES)?\b|\bDISALLOWED\b",
        upper,
    ))
    has_granted = bool(re.search(r"\bGRANTED?\b|\bSUSTAINED\b|\bAPPROVED\b", upper))
    has_continued = bool(re.search(
        r"\bCONTINUED\s+TO\b|\bMATTER\s+IS\s+CONTINUED\b|\bCONTINUES\s+THE\b"
        r"|\bHEARING\s+(?:IS\s+)?CONTINUED\b",
        upper,
    ))
    has_appearance = bool(re.search(
        r"\bAPPEARANCES?\s+(?:ARE\s+)?(?:NECESSARY|REQUIRED)\b"
        r"|\bAPPEAR(?:ANCE)?\s+IS\s+REQUIRED\b"
        r"|\bPARTIES\s+ARE\s+ORDERED\s+TO\s+APPEAR\b",
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


def _extract_parties(block_before_anchor: str) -> tuple[str, str]:
    """From the caption block before 'Case Number:', pull petitioner and respondent.

    The block reads, after pleading-line stripping, something like:
        SUPERIOR COURT OF CALIFORNIA
        COUNTY OF SAN FRANCISCO
        UNIFIED FAMILY COURT
        ALLISON SIU,
         Petitioner
         VS.
        ANDREW O'CONNOR,
         Respondent
        ) ) ) ) ) ) ) ) ) ) ) )
    """
    petitioner = ""
    respondent = ""
    state = "before_petitioner"
    for line in block_before_anchor.splitlines():
        s = line.strip(" \t,)(")
        if not s:
            continue
        upper = s.upper()
        if upper in {"PETITIONER", "PETITIONER,", ")", "VS.", "VS"} or upper.startswith("VS."):
            if "VS" in upper:
                state = "before_respondent"
            continue
        if upper in {"RESPONDENT", "RESPONDENT,"}:
            continue
        if "SUPERIOR COURT" in upper or "COUNTY OF" in upper or "UNIFIED FAMILY" in upper:
            continue
        # Skip lines of "))))" pleading separators.
        if all(c in ") (" for c in s):
            continue
        if state == "before_petitioner" and s and s[0].isalpha():
            petitioner = s.strip(", ")
            state = "before_respondent"
            continue
        if state == "before_respondent" and s and s[0].isalpha():
            respondent = s.strip(", ")
            state = "done"
            break
    return petitioner, respondent


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

    # Strip pleading-paper line numbers from each page.
    pages = [_strip_pleading_lines(p) for p in raw_pages]
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

    anchors = list(CASE_NUMBER_ANCHOR_RE.finditer(plain))
    if not anchors:
        return []

    rulings: list[Ruling] = []
    for i, cn_match in enumerate(anchors):
        case_number = cn_match.group("num")

        # Block runs from the caption block (start of preceding header text)
        # to the next Case Number anchor (or end of doc).
        # Start: previous anchor's block end (or 0).
        block_start = anchors[i - 1].end() if i > 0 else 0
        block_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        # Find the caption "SUPERIOR COURT" within this block — that marks the
        # actual start of the ruling section.
        sc_match = re.search(r"SUPERIOR\s+COURT\s+OF\s+CALIFORNIA", plain[block_start:block_end])
        section_start = block_start + sc_match.start() if sc_match else block_start

        # The block runs to the next ruling's caption (the next SUPERIOR COURT
        # block) rather than the next Case Number — the next ruling's caption
        # precedes its own case-number anchor.
        rest = plain[cn_match.end():block_end]
        next_caption = re.search(r"SUPERIOR\s+COURT\s+OF\s+CALIFORNIA", rest)
        if next_caption:
            block_end = cn_match.end() + next_caption.start()
        section_text = plain[section_start:block_end]

        # Extract per-block metadata.
        hearing_date = None
        hd_match = HEARING_DATE_RE.search(section_text)
        if hd_match:
            hearing_date = _parse_date(hd_match.group("date"))

        dept = None
        dept_match = DEPARTMENT_RE.search(section_text)
        if dept_match:
            dept = dept_match.group("dept")

        judge = None
        j_match = PRESIDING_RE.search(section_text)
        if j_match:
            judge = " ".join(j_match.group("judge").split())

        # Parties from the caption block (text before Case Number).
        caption_end = cn_match.start() - section_start
        caption_block = section_text[:caption_end]
        petitioner, respondent = _extract_parties(caption_block)
        if petitioner and respondent:
            case_title = f"{petitioner} vs {respondent}"
        else:
            case_title = petitioner or respondent

        # Motion type: text between metadata block end and TENTATIVE RULING marker.
        # Find the TENTATIVE RULING anchor within this section.
        tr_match = TENTATIVE_RULING_ANCHOR_RE.search(section_text)
        if tr_match is None:
            # No anchor — treat the rest as body.
            disposition = section_text[cn_match.end() - section_start:].strip()
            motion_type = ""
        else:
            # Motion type sits between the last metadata field and the
            # TENTATIVE RULING marker. All hd/j/dept matches are in
            # section_text coordinates already.
            after_meta = max(
                hd_match.end() if hd_match else 0,
                j_match.end() if j_match else 0,
                dept_match.end() if dept_match else 0,
            )
            between = section_text[after_meta:tr_match.start()].strip()
            # Motion type lines look like all-caps statements.
            motion_lines = []
            for line in between.splitlines():
                s = line.strip()
                if not s:
                    if motion_lines:
                        break
                    continue
                if re.match(r"^[A-Z0-9 ,/&'.\-:()]{4,200}$", s):
                    motion_lines.append(s)
                else:
                    if motion_lines:
                        break
            motion_type = " ".join(motion_lines)
            disposition = section_text[tr_match.end():].strip()

        outcome, conditional, continued_to = _classify(disposition)

        page_start = page_for_offset(section_start)
        section_text_rstrip = section_text.rstrip()
        page_end = max(page_start, page_for_offset(section_start + len(section_text_rstrip) - 1))

        ruling_id = hashlib.sha256(
            f"{source_sha256}:{i + 1}:{case_number}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division="Family Law" if division_hint is None else division_hint,
                dept=dept or dept_hint,
                hearing_date=hearing_date or date(1970, 1, 1),
                ruling_index=i + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=disposition,
                conditional=conditional,
                continued_to=continued_to,
                body_text=judge or "",
                full_text=section_text.strip(),
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=f"sf-ufc-dept-{dept}" if dept else "sf-ufc",
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.now(UTC),
            )
        )

    # Drop rulings with an unset hearing date (couldn't parse one).
    rulings = [r for r in rulings if r.hearing_date != date(1970, 1, 1)]
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
