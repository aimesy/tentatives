"""Contra Costa County tentative-rulings scraper.

CCC's tentative-rulings PDFs follow a very consistent format across departments:

  Page 1 header (5 lines):
    SUPERIOR COURT OF CALIFORNIA, CONTRA COSTA COUNTY
    MARTINEZ, CA  (or another locale)
    DEPARTMENT NN
    JUDICIAL OFFICER: <name>
    HEARING DATE:  MM/DD/YYYY

  Each ruling block looks like:
    N. HH:MM AM  CASE NUMBER: <CASE_NUM>            # N omitted for "Add On" entries
    CASE NAME: <case title>
    *HEARING ON MOTION IN RE: <description>        # bullet-marked
    FILED BY: <party>
    *TENTATIVE RULING:*
    <disposition body>

Anchor for splitting rulings: `*TENTATIVE RULING:*` (without index).
The case header is the line containing `CASE NUMBER:` just before each anchor.

Case-number formats seen:
    C22-01552, C25-01624     (modern: 1-letter + YY + dash + 5 digits)
    MSC21-02266              (legacy: 2-3 letters + YY + dash + 5 digits)
    N23-0180                 (1-letter + YY + dash + 4 digits)

Discovery for CCC uses the direct URL loaded by the official Contra Costa
public-page iframe. The parent court page is still the best browser entry point,
but the iframe URL itself is public and works for CLI capture.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import pypdf

from counties.common import PdfRef, absolute_url, clean_text, extract_links, filename_from_url, unique_refs
from schema import Ruling
from . import COUNTY_SLUG, PARSER_VERSION


# ============================================================ DISCOVERY

LANDING_PAGES = [
    # Official parent page embeds this retired.cc-courts.org ASP.NET page.
    # Fetching the retired host directly avoids cross-origin iframe execution
    # while preserving the court-published PDF list.
    "https://retired.cc-courts.org/civil/motions-hearings-tentative.aspx",
]

WAYBACK_PDF_PATTERNS = [
    "https://retired.cc-courts.org/civil/TR/*/*.pdf",
    "https://www.cc-courts.org/civil/TR/*/*.pdf",
]

CCC_HOST_RE = re.compile(r"(^|\.)((retired|www)\.)?cc-courts\.org$|(^|\.)contracosta\.courts\.ca\.gov$", re.I)
CCC_TR_PDF_PATH_RE = re.compile(r"^/civil/TR/.+\.pdf$", re.I)
CCC_SYSTEM_RULING_PATH_RE = re.compile(r"^/system/files/tentative-rulings?/[^/]+\.pdf$", re.I)
NON_RULING_NAME_RE = re.compile(
    r"\b(judicial[-_ ]directory|department[-_ ]phone|directory[-_ ]of[-_ ]judicial|"
    r"phone[-_ ]numbers?|instructions?[-_ ]for[-_ ]contesting)\b",
    re.I,
)
DEPT_HINT_RE = re.compile(r"(?:^|/)Department\s+(\d{1,3})\b|/(\d{1,3})_\d{6}\.pdf$", re.I)


def _canonical_url(raw_url: str, page_url: str | None) -> str:
    raw = raw_url.replace("\\", "/")
    url = absolute_url(raw, page_url or LANDING_PAGES[0])
    parts = urlsplit(url)
    path = quote(unquote(parts.path), safe="/%")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _is_ruling_pdf(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = unquote(parts.path)
    if not parts.scheme.startswith("http") or not host or not path.lower().endswith(".pdf"):
        return False
    if not CCC_HOST_RE.search(host):
        return False
    if NON_RULING_NAME_RE.search(unquote(path)):
        return False
    return bool(CCC_TR_PDF_PATH_RE.search(path) or CCC_SYSTEM_RULING_PATH_RE.search(path))


def _dept_hint(url: str) -> str | None:
    match = DEPT_HINT_RE.search(unquote(urlsplit(url).path))
    if not match:
        return None
    dept = match.group(1) or match.group(2)
    return str(int(dept)) if dept else None


def discover_live(html: str, page_url: str | None = None) -> list[PdfRef]:
    refs: list[PdfRef] = []
    for link in extract_links(html):
        url = _canonical_url(link.url, page_url)
        if not _is_ruling_pdf(url):
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                dept_hint=_dept_hint(url),
                division_hint="Civil",
                link_text=clean_text(link.text),
                source_page_url=page_url,
            )
        )
    return unique_refs(refs)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def _html_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return "\n".join(parser.parts)


def parse_page_capture(html: str, capture: dict) -> list[Ruling]:
    """Normalize one captured Contra Costa HTML page.

    These are not PDF rulings. They are changed-hash page captures for
    perishable pages such as probate calendar notes.
    """
    source_sha256 = capture.get("source_sha256") or hashlib.sha256(html.encode("utf-8")).hexdigest()
    source_url = capture.get("source_url") or ""
    page_kind = capture.get("page_kind") or "page_capture"
    title = capture.get("title") or "Contra Costa page capture"
    captured_at_raw = capture.get("captured_at") or capture.get("fetched_at")
    try:
        captured_at = datetime.fromisoformat(str(captured_at_raw).replace("Z", "+00:00"))
    except Exception:
        raise ValueError(f"malformed captured_at for page capture: {captured_at_raw!r}") from None
    text = _html_text(html).strip()
    if not text:
        return []

    division = {
        "probate_calendar_notes": "Probate Calendar Notes",
        "tentative_rulings_archive": "Tentative Rulings Archive",
        "tentative_rulings_page": "Tentative Rulings Page",
    }.get(page_kind, "Court Page")

    ruling_id = hashlib.sha256(
        f"{source_sha256}:{source_url}:{page_kind}".encode("utf-8")
    ).hexdigest()[:32]
    return [
        Ruling(
            ruling_id=ruling_id,
            county=COUNTY_SLUG,
            division=division,
            dept=None,
            hearing_date=captured_at.date(),
            ruling_index=1,
            case_number="",
            case_title=title,
            motion_type="Calendar note" if page_kind == "probate_calendar_notes" else "Page capture",
            outcome="other",
            outcome_text="",
            conditional=False,
            continued_to=None,
            body_text=text,
            full_text=text,
            page_start=0,
            page_end=0,
            source_sha256=source_sha256,
            source_url=source_url,
            style=f"html-{page_kind}",
            parser_version=PARSER_VERSION,
            ingest_ts=datetime.now(UTC),
        )
    ]


# ============================================================ PARSE


# Header signals.
HEADER_FIRST_RE = re.compile(r"SUPERIOR\s+COURT\s+OF\s+CALIFORNIA,?\s+CONTRA\s+COSTA", re.IGNORECASE)
HEADER_DEPT_RE = re.compile(r"^DEPARTMENT\s+(\d+)(?:,\s+[A-Z][A-Z\s]+)?\s*$", re.MULTILINE)
HEADER_DATE_RE = re.compile(r"HEARING\s+DATE:?\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.IGNORECASE)
HEADER_JUDGE_RE = re.compile(r"JUDICIAL\s+OFFICER:?\s+(.+?)\s*$", re.MULTILINE | re.IGNORECASE)

# Disposition anchor.
TENTATIVE_RULING_ANCHOR_RE = re.compile(
    r"\*?\s*TENTATIVE\s+RULING\s*:?\s*\*?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Case-number line: ruling block always contains "CASE NUMBER: <num>".
CASE_NUMBER_LINE_RE = re.compile(
    r"^\s*(?P<idx>\d{1,3}\.)?\s*"
    r"(?P<time>\d{1,2}:\d{2}\s*[AP]M)?\s*"
    r"CASE\s+NUMBER:\s+(?P<case_number>[A-Z]{1,4}\d{2,4}-?\d{2,8})\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Other ruling-header attribute lines (in any order, all optional).
CASE_NAME_RE = re.compile(r"^\s*CASE\s+NAME:\s*(?P<title>.+?)\s*$", re.MULTILINE | re.IGNORECASE)

# Hearing description. Patterns observed in CCC PDFs:
#   "HEARING ON DEMURRER TO: <X>"
#   "HEARING ON MOTION IN RE: <X>"
#   "HEARING ON MOTION FOR ... RE: <X>"
#   "HEARING ON MINOR'S COMPROMISE RE: <X>"
#   "HEARING ON SUMMARY MOTION" (no colon — the FILED BY line follows)
# We capture <action> (before the colon, with the optional "IN RE"/"RE"
# separator stripped) and <target> (after the colon). The two are joined
# downstream into the motion_type — "MOTION + TO STRIKE ..." → "MOTION TO
# STRIKE ...". `[^:\n]+?` (rather than the old `[^:]*`) keeps the match
# bounded to a single line so "HEARING ON SUMMARY MOTION\nFILED BY: <PARTY>"
# stops capturing before the FILED BY line — previously the party name leaked
# into motion_type.
HEARING_DESCRIPTION_RE = re.compile(
    r"^\s*\*?\s*HEARING\s+ON\s+(?P<action>[^:\n]+?)"
    r"(?:\s+IN\s+RE|\s+RE)?"
    r"(?:\s*:\s*(?P<target>[^\n]+?))?\s*$",
    re.MULTILINE | re.IGNORECASE,
)
FILED_BY_RE = re.compile(r"^\s*FILED\s+BY:\s*(?P<party>.*)$", re.MULTILINE | re.IGNORECASE)


def _motion_from_hearing(hearing_m: "re.Match[str] | None") -> str:
    """Combine the action and target groups into a single motion_type string.

    Handles two stitching artifacts:
      - "DEMURRER TO" + "TO 2ND AMENDED CROSS-COMPLAINT" → drop the duplicate
        "TO" so the result reads "DEMURRER TO 2ND AMENDED CROSS-COMPLAINT".
      - Trailing dangling prepositions ("TO", "FOR", "IN") on the target are
        artifacts of mid-phrase line wraps and add no information; strip them.
    """
    if not hearing_m:
        return ""
    action = (hearing_m.group("action") or "").strip()
    target = (hearing_m.group("target") or "").strip()
    if action and target:
        action_words = action.split()
        target_words = target.split()
        if action_words and target_words and action_words[-1].upper() == target_words[0].upper():
            target_words = target_words[1:]
        while target_words and target_words[-1].upper() in {"TO", "FOR", "IN", "OF", "RE"}:
            target_words.pop()
        target = " ".join(target_words)
        return f"{action} {target}".strip()
    return action or target

# Section markers - "Law & Motion", "Law & Motion Add On", "Probate", etc.
SECTION_HEADER_RE = re.compile(
    r"^\s*(?P<section>Law\s+&\s+Motion(?:\s+Add\s+On(?:\s+\d+)?)?|Probate|Civil|Family\s+Law|Discovery)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _classify(disposition_text: str) -> tuple[str, bool, date | None]:
    """Return (primary_outcome, conditional, continued_to)."""
    text = disposition_text.upper()
    conditional = "ABSENT OBJECTION" in text
    # CCC vocabulary
    has_denied = bool(re.search(r"\bDENIED\b|\bDENIES\b|\bDISMISSES?\b", text))
    has_granted = bool(re.search(r"\bGRANTED?\b|\bSUSTAINED\b", text))
    has_continued = bool(re.search(r"\bCONTINUED TO\b|\bHEARING (?:IS )?CONTINUED\b", text))
    has_appearance = bool(re.search(r"\bAPPEARANCE\s+REQUIRED\b|\bHEARING\s+REQUIRED\b", text))
    has_vacated = bool(re.search(r"^\s*VACATED\b|\bVACATED\.", text, re.MULTILINE))
    has_off_cal = bool(re.search(r"\bOFF\s+CALENDAR\b|\bDROPPED\s+FROM\b", text))

    if has_denied:
        outcome = "denied"
    elif has_granted:
        outcome = "granted"
    elif has_continued:
        outcome = "continued"
    elif has_vacated or has_off_cal:
        outcome = "off_calendar"
    elif has_appearance:
        outcome = "appearance_required"
    else:
        outcome = "other"

    continued_to: date | None = None
    if has_continued:
        m = re.search(
            r"CONTINUED\s+TO\s+(?:[\w:.]+\s+(?:a\.m\.|p\.m\.)\s+on\s+)?"
            r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
            disposition_text,
            re.IGNORECASE,
        )
        if m:
            month = m.group("month").capitalize()
            month_idx = {
                "January": 1, "February": 2, "March": 3, "April": 4,
                "May": 5, "June": 6, "July": 7, "August": 8,
                "September": 9, "October": 10, "November": 11, "December": 12,
            }.get(month)
            if month_idx:
                try:
                    continued_to = date(int(m.group("year")), month_idx, int(m.group("day")))
                except ValueError:
                    pass

    return outcome, conditional, continued_to


@dataclass(frozen=True)
class _DocMeta:
    hearing_date: date | None
    dept: str | None
    judge: str | None


def _extract_doc_meta(page1_text: str, dept_hint: str | None) -> _DocMeta:
    head = "\n".join(page1_text.splitlines()[:10])
    if not HEADER_FIRST_RE.search(head):
        # Not a CCC tentative-ruling header.
        return _DocMeta(None, dept_hint, None)
    dept_m = HEADER_DEPT_RE.search(head)
    date_m = HEADER_DATE_RE.search(head)
    judge_m = HEADER_JUDGE_RE.search(head)
    hearing_date = None
    if date_m:
        try:
            hearing_date = date(int(date_m.group(3)), int(date_m.group(1)), int(date_m.group(2)))
        except ValueError:
            pass
    return _DocMeta(
        hearing_date=hearing_date,
        dept=(dept_m.group(1) if dept_m else dept_hint),
        judge=(judge_m.group(1).strip() if judge_m else None),
    )


def _strip_page_artifacts(page_texts: list[str]) -> list[str]:
    """Strip the multi-line header from page 1 and the page-number footer from every page."""
    out: list[str] = []
    for i, t in enumerate(page_texts):
        lines = t.splitlines()
        if i == 0:
            # Drop the first ~5 header lines + leading blank/single-char lines.
            stripped: list[str] = []
            in_header = True
            header_lines_seen = 0
            for line in lines:
                if in_header:
                    if HEADER_FIRST_RE.search(line):
                        header_lines_seen = 1
                        continue
                    if 0 < header_lines_seen < 5:
                        header_lines_seen += 1
                        continue
                    if header_lines_seen >= 5:
                        in_header = False
                stripped.append(line)
            lines = stripped
        # Drop numeric page-number footers only at the bottom; standalone
        # numerals inside the body can be statute sections or ruling text.
        while lines and re.match(r"^\s*\d{1,4}\s*$", lines[-1]):
            lines.pop()
        out.append("\n".join(lines))
    return out


def parse(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
) -> list[Ruling]:
    """Extract all rulings from one CCC tentative-rulings PDF."""
    if source_sha256 is None:
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    raw_pages = [page.extract_text() or "" for page in reader.pages]
    if not raw_pages:
        return []

    meta = _extract_doc_meta(raw_pages[0], dept_hint)
    if meta.hearing_date is None or meta.dept is None:
        return []

    pages = _strip_page_artifacts(raw_pages)
    joined_parts: list[str] = []
    page_offsets: list[int] = []
    cursor = 0
    SEP = "\n\n"
    for page in pages:
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

    # Find all anchors. Each one is the *TENTATIVE RULING:* line.
    anchors = [m for m in TENTATIVE_RULING_ANCHOR_RE.finditer(plain)]
    if not anchors:
        return []

    rulings: list[Ruling] = []
    current_section: str | None = None
    for i, anchor in enumerate(anchors):
        # Region for this ruling's header: from previous anchor's end (or doc start) to anchor's start.
        region_start = anchors[i - 1].end() if i > 0 else 0
        region_end = anchor.start()
        region = plain[region_start:region_end]

        # Pick up any section header in this region (most recent wins for current).
        for sm in SECTION_HEADER_RE.finditer(region):
            current_section = sm.group("section").strip()

        case_match = None
        # Use the LAST CASE NUMBER match in the region (closest to the anchor).
        for m in CASE_NUMBER_LINE_RE.finditer(region):
            case_match = m
        if case_match is None:
            continue

        case_number = case_match.group("case_number")
        idx_raw = case_match.group("idx")
        ruling_index = int(idx_raw.rstrip(".")) if idx_raw else 0

        # Within the same region, after the CASE NUMBER line, look for CASE NAME / HEARING / FILED BY.
        post_case = region[case_match.end():]
        title_m = CASE_NAME_RE.search(post_case)
        hearing_m = HEARING_DESCRIPTION_RE.search(post_case)
        filed_m = FILED_BY_RE.search(post_case)

        case_title = title_m.group("title").strip() if title_m else ""
        motion_type = _motion_from_hearing(hearing_m)
        filed_by = filed_m.group("party").strip() if filed_m else ""

        # Disposition runs from after this anchor's line-end to the next anchor's CASE NUMBER line.
        disposition_start = anchor.end()
        if i + 1 < len(anchors):
            next_region = plain[anchors[i].end():anchors[i + 1].start()]
            next_case_iter = list(CASE_NUMBER_LINE_RE.finditer(next_region))
            if next_case_iter:
                # End disposition just before the next case-number block.
                first_in_next = next_case_iter[0]
                disposition_end = anchors[i].end() + first_in_next.start()
            else:
                disposition_end = anchors[i + 1].start()
        else:
            disposition_end = len(plain)

        disposition_text = plain[disposition_start:disposition_end].strip()
        # Strip trailing section header lines if any.
        disposition_text = SECTION_HEADER_RE.sub("", disposition_text).strip()
        outcome, conditional, continued_to = _classify(disposition_text)

        case_header_start = region_start + case_match.start()
        page_start = page_for_offset(case_header_start)
        trimmed_end = disposition_start + len(plain[disposition_start:disposition_end].rstrip())
        page_end = max(page_start, page_for_offset(max(case_header_start, trimmed_end - 1)))

        full_text = plain[case_header_start:disposition_end].strip()
        ruling_id = hashlib.sha256(
            f"{source_sha256}:{case_number}:{i}".encode("utf-8")
        ).hexdigest()[:32]

        rulings.append(
            Ruling(
                ruling_id=ruling_id,
                county=COUNTY_SLUG,
                division=current_section,  # e.g. "Law & Motion", "Probate"
                dept=meta.dept,
                hearing_date=meta.hearing_date,
                ruling_index=ruling_index if ruling_index > 0 else i + 1,
                case_number=case_number,
                case_title=case_title,
                motion_type=motion_type,
                outcome=outcome,
                outcome_text=disposition_text,
                conditional=conditional,
                continued_to=continued_to,
                body_text=filed_by,  # CCC doesn't have a narrative body before disposition
                full_text=full_text,
                page_start=page_start,
                page_end=page_end,
                source_sha256=source_sha256,
                source_url=source_url,
                style=f"cc-{meta.dept}",
                parser_version=PARSER_VERSION,
                ingest_ts=datetime.now(UTC),
            )
        )

    return rulings


def parse_file(path: str, source_url: str | None = None, dept_hint: str | None = None) -> list[Ruling]:
    with open(path, "rb") as f:
        data = f.read()
    if source_url is None:
        source_url = f"file://{path}"
    return parse(data, source_url=source_url, dept_hint=dept_hint)
