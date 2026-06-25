"""Parser implementations for newly captured county sources."""

from __future__ import annotations

import re
from datetime import date

from schema import Ruling

from .simple_parser import (
    clean_lines,
    extract_pdf_pages,
    find_date,
    html_to_text,
    inline,
    join_pages,
    make_ruling,
    page_for_offset,
    parse_date_value,
    source_sha,
)


def _pdf_text(pdf_bytes: bytes):
    pages = extract_pdf_pages(pdf_bytes)
    plain, offsets = join_pages(pages)
    return pages, plain, offsets


def _page_span(offsets: list[int], start: int, end: int) -> tuple[int, int]:
    page_start = page_for_offset(offsets, start)
    page_end = max(page_start, page_for_offset(offsets, max(start, end - 1)))
    return page_start, page_end


def _normalize_butte_probate_page(text: str) -> str:
    text = re.sub(r"(\d{2}PR)\s+(\d{5})", r"\1\2", text)
    text = re.sub(r"(?m)^9:\s*\n\s*00\s+", "9:00 ", text)
    return re.sub(
        r"(?m)^(\s*\d{1,2}:\d{2})\s*\n\s+(?=(?:\d{2}(?:PR|MH)\d{5}|PR-\d{5})\b)",
        r"\1 ",
        text,
    )


def _normalize_slo_probate_page(text: str) -> str:
    return re.sub(
        r"(?m)^(\s*\d+)\s*\n\s+(?=\d{2}(?:PR|CVP|LCP)-\d{4}\b)",
        r"\1 ",
        text,
    )


def _case_division(case_number: str, default: str | None = None) -> str | None:
    upper = case_number.upper()
    if "PR" in upper:
        return "Probate"
    if upper.startswith("FL") or "FL" in upper:
        return "Family Law"
    if "CV" in upper or "CU" in upper or "CLJ" in upper or "CIV" in upper:
        return "Civil Law and Motion"
    return default


def _first_body_line(lines: list[str]) -> int:
    body_re = re.compile(
        r"^(?:The Court|At the request|Pursuant|This matter|The petition|The Petition|"
        r"The First|Parties|Plaintiff|Defendant|Petitioner|Respondent|Based upon|"
        r"Good cause|No appearance|Appearance|Documents|All in order|Previous issues)",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        if body_re.search(line):
            return i
    return min(2, len(lines))


def _line_window(lines: list[str], start: int, end: int | None = None) -> str:
    return clean_lines("\n".join(lines[start:end]))


SLO_PROBATE_BOILERPLATE_RE = re.compile(
    r"(?is)\n\s*(?:The\s+Probate\s+notes?\s+for\s+the\s+above|"
    r"Please\s+email\s+the\s+Probate\s+Department|"
    r"Probate\s+Department\s+Email|"
    r"Probate\s+Research\s+Department|"
    r"Probate\s+Research\s+Attorney|"
    r"If\s+you\s+wish\s+to\s+appear\s+remotely).*$"
)
SLO_PROBATE_TABLE_HEADER_RE = re.compile(
    r"(?im)^\s*(?:No\.\s+)?Case Number Case Name Type of Matter Probate Notes\s*$"
)
SLO_PROBATE_EMAIL_RULES_RE = re.compile(
    r"(?is)\n\s*Subject\s+to\s+the\s+rules\s+below,\s+attorneys\s+and\s+parties\s+to\s+a\s+case\s+may\s+now\s+contact\s+the\s+Probate\s+Research\s+Department\s+using\s+the\s+following\s+email:.*?"
    r"The\s+Probate\s+Research\s+Department\s+will\s+make\s+every\s+effort\s+to\s+respond\s+within\s+two\s+Court\s+days\s+of\s+receipt\s+of\s+the\s+email\.?",
)
SAN_BENITO_END_RE = re.compile(r"(?im)^\s*END\s+OF\s+TENTATIVE\s+DECISIONS\s*$")
SONOMA_END_RE = re.compile(r"(?im)^\s*\*+\s*END\s+OF\s+TENTATIVE\s+RULINGS\s*\*+\s*$")
SIERRA_MULTI_SECTION_SOURCE_SHAS = {
    # Nightingale v. Durrett, a one-page packet with two separately headed rulings.
    "e32d1d6945d3cd8af284aae36c331ad1377e94ef0357c4dd329f77942224977c",
}
SIERRA_MULTI_SECTION_URL_MARKERS = {
    "17RJ4PEhce-1OvPpZY8yRs01k-wAULiTN",
}
SIERRA_GUARDIANSHIP_RE = re.compile(
    r"(?is)\bIn\s+the\s+matter\s+of\b.*?\bCASE\s+NO\.?:\s*PR\s*\d+.*?"
    r"\bTENTATIVE\s+GUARDIANSHIP\s+RULING\b.*?"
    r"\bhearing\s+currently\s+set\s+on\s+"
    r"(?:[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})"
)


TULARE_PROBATE_TYPES = (
    "Final Distribution Hearing",
    "Letters of Administration",
    "Appoint Temporary Conservator",
    "Appoint Conservator",
    "Determine Succession to Primary Residence",
    "Probate Will/Issue Letters",
    "Spousal Property Hearing",
    "OSC Hearing",
)
TULARE_PROBATE_STATUS_RE = re.compile(
    r"\b(?:Appearance\s+Required|Recommended\s+for\s+Approval|Approval\s+Conditional(?:\s+Upon)?)\b",
    re.IGNORECASE,
)


def _sierra_guardianship_title(plain: str, case_match: re.Match[str]) -> str:
    pre_case = plain[: case_match.start()]
    title_match = re.search(
        r"(?is)\bIn\s+the\s+matter\s+of\s+(?P<title>.*?)(?:\bIN\s+AND\s+FOR\b|$)",
        pre_case,
    )
    title = inline(title_match.group("title")) if title_match else ""
    title = re.sub(r"\bCASE\s+NO\.?:?\s*$", "", title, flags=re.IGNORECASE).strip()

    heading_match = re.search(r"(?i)\bTENTATIVE\s+GUARDIANSHIP\s+RULING\b", plain)
    tail = plain[case_match.end() : heading_match.start() if heading_match else case_match.end()]
    tail_lines = []
    for raw_line in tail.splitlines():
        line = inline(raw_line)
        if not line:
            continue
        if re.search(r"\b(?:CLERK|DEPUTY|COURT|COUNTY|SIERRA)\b", line, re.IGNORECASE):
            continue
        if re.search(r"\d", line):
            continue
        if line.isupper():
            continue
        tail_lines.append(line)
    if tail_lines:
        title = inline(f"{title} {' '.join(tail_lines)}")
    return title or "Guardianship"


def _parse_sierra_guardianship(
    pages: list[str],
    plain: str,
    sha: str,
    source_url: str,
    dept_hint: str | None,
) -> list[Ruling]:
    if not SIERRA_GUARDIANSHIP_RE.search(plain):
        return []
    case_match = re.search(r"(?i)\bCASE\s+NO\.?:\s*(PR\s*\d+)\b", plain)
    hearing_match = re.search(
        r"(?i)\bhearing\s+currently\s+set\s+on\s+"
        r"([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})",
        plain,
    )
    heading_match = re.search(r"(?i)\bTENTATIVE\s+GUARDIANSHIP\s+RULING\b", plain)
    if not case_match or not hearing_match or not heading_match:
        return []
    hearing_date = parse_date_value(hearing_match.group(1))
    if not hearing_date:
        return []

    footer_match = re.search(
        r"(?im)^\s*(?:Dated:|(?:\S+\s+)?Dated:|Charles\s+H\.?\s+Ervin\b)",
        plain[heading_match.end() :],
    )
    body_start = heading_match.end()
    body_end = body_start + footer_match.start() if footer_match else len(plain)
    body = clean_lines(plain[body_start:body_end])
    if not body:
        return []
    outcome_text = re.sub(
        r"(?is)^NO\s+APPEARANCE\s+REQUIRED\b.*?(?=\bThe\s+court\b)",
        "",
        body,
    ).strip()

    full_start = plain.lower().rfind("in the matter of", 0, heading_match.start())
    if full_start < 0:
        full_start = 0

    return [
        make_ruling(
            county="sierra",
            source_sha256=sha,
            source_url=source_url,
            parser_version="sierra-v2",
            style="sierra-guardianship",
            index=1,
            case_number=case_match.group(1).replace(" ", ""),
            case_title=_sierra_guardianship_title(plain, case_match),
            hearing_date=hearing_date,
            full_text=clean_lines(plain[full_start:body_end]),
            body_text=body,
            motion_type="Tentative Guardianship Ruling",
            division="Guardianships",
            dept=dept_hint,
            page_start=1,
            page_end=max(1, len(pages)),
            outcome_text=outcome_text or body,
        )
    ]


def _split_tulare_probate_row(case_number: str, block: str) -> tuple[str, str, str]:
    row = inline(block)
    row = re.sub(rf"^{re.escape(case_number)}\s*", "", row).strip()
    status_match = TULARE_PROBATE_STATUS_RE.search(row)
    before_status = row[: status_match.start()].strip() if status_match else row
    body = row[status_match.start():].strip() if status_match else ""

    motion = ""
    case_title = before_status
    for type_name in sorted(TULARE_PROBATE_TYPES, key=len, reverse=True):
        m = re.search(rf"\b{re.escape(type_name)}\s*$", before_status, re.IGNORECASE)
        if m:
            case_title = before_status[: m.start()].strip()
            motion = type_name
            break
    return case_title or case_number, motion, body


def _trim_or_drop_table_header(block_text: str, header_match: re.Match[str] | None) -> tuple[str, int | None]:
    if not header_match:
        return block_text, None
    tail = inline(block_text[header_match.end():])
    if not tail:
        return block_text[: header_match.start()], header_match.start()
    return f"{block_text[:header_match.start()]}\n{block_text[header_match.end():]}", None


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> tuple[str, int]:
    if not spans:
        return text, len(text.rstrip())
    spans = sorted(spans)
    pieces: list[str] = []
    cursor = 0
    kept_end = 0
    for start, end in spans:
        if start > cursor:
            piece = text[cursor:start]
            pieces.append(piece)
            if piece.strip():
                kept_end = start
        cursor = max(cursor, end)
    if cursor < len(text):
        piece = text[cursor:]
        pieces.append(piece)
        if piece.strip():
            kept_end = len(text.rstrip())
    return "\n".join(piece.strip("\n") for piece in pieces if piece.strip()), kept_end


def _clean_slo_probate_block_text(block_text: str) -> tuple[str, int]:
    email_matches = list(SLO_PROBATE_EMAIL_RULES_RE.finditer(block_text))
    email_spans = [(m.start(), m.end()) for m in email_matches]
    spans: list[tuple[int, int]] = list(email_spans)
    insertions: dict[int, tuple[str, int]] = {}

    for match in email_matches:
        segment = block_text[match.start():match.end()]
        embedded = re.search(
            r"(?is)No\.\s*Case\s*Number\s*Case\s*Name\s*Type\s*of\s*Matter\s*Probate\s*Notes\s*"
            r"(?P<tail>.*?)(?=^\s*d\.\s+Emails\s+may|^\s*4\.\s+This\s+email\s+procedure|\Z)",
            segment,
            re.MULTILINE,
        )
        if embedded:
            tail_lines = [
                line
                for line in clean_lines(embedded.group("tail")).splitlines()
                if line.strip() and not re.fullmatch(r"\d{1,3}", line.strip())
            ]
            tail = "\n".join(tail_lines).strip()
            if tail:
                insertions[match.start()] = (tail, match.start() + embedded.end("tail"))

    for header in SLO_PROBATE_TABLE_HEADER_RE.finditer(block_text):
        if not any(start <= header.start() < end for start, end in email_spans):
            spans.append((header.start(), header.end()))

    if not spans:
        return block_text, len(block_text.rstrip())

    pieces: list[str] = []
    cursor = 0
    kept_end = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        piece = block_text[cursor:start]
        if piece.strip():
            pieces.append(piece.strip("\n"))
            kept_end = max(kept_end, start)
        if start in insertions:
            tail, tail_end = insertions[start]
            pieces.append(tail)
            kept_end = max(kept_end, tail_end)
        cursor = end
    if cursor < len(block_text):
        piece = block_text[cursor:]
        if piece.strip():
            pieces.append(piece.strip("\n"))
            kept_end = max(kept_end, len(block_text.rstrip()))
    return "\n".join(pieces).strip(), kept_end


def parse_ventura(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, _offsets = _pdf_text(pdf_bytes)
    if not plain:
        return []
    header = re.search(r"(?m)^(?P<num>[A-Z0-9]{5,30}):\s*(?P<title>.+?)\s*$", plain)
    date_dept = re.search(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+in\s+Department\s+(?P<dept>[A-Z0-9]+)", plain)
    if not header or not date_dept:
        return []
    hearing_date = parse_date_value(date_dept.group("date"))
    if not hearing_date:
        return []
    after_date = plain[date_dept.end() :].splitlines()
    motion = ""
    for line in after_date:
        line = inline(line)
        if line and not line.isdigit():
            motion = line
            break
    body_match = re.search(r"Tentative Ruling:\s*(?P<body>.*)", plain, re.IGNORECASE | re.DOTALL)
    if body_match:
        body = body_match.group("body")
    elif motion:
        body = plain[plain.find(motion) + len(motion) :]
    else:
        body = plain[date_dept.end() :]
    division = "Probate Notes" if "Probate Notes" in plain[:300] or "PR" in header.group("num") else "Civil Law and Motion"
    return [
        make_ruling(
            county="ventura",
            source_sha256=sha,
            source_url=source_url,
            parser_version="ventura-v1",
            style="ventura-one-ruling",
            index=1,
            case_number=header.group("num"),
            case_title=header.group("title"),
            hearing_date=hearing_date,
            full_text=plain,
            body_text=body,
            motion_type=motion,
            division=division_hint or division,
            dept=dept_hint or date_dept.group("dept"),
            page_start=1,
            page_end=max(1, len(pages)),
        )
    ]


def parse_monterey(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, _offsets = _pdf_text(pdf_bytes)
    case = re.search(r"\b\d{2}CV\d{6}\b", plain)
    date_match = re.search(r"Hearing Date:\s*([A-Za-z]+ \d{1,2},? \d{4})", plain, re.IGNORECASE)
    if not case or not date_match:
        return []
    hearing_date = parse_date_value(date_match.group(1))
    if not hearing_date:
        return []
    title_start = re.search(r"TENTATIVE RULING", plain, re.IGNORECASE)
    title_region = plain[(title_start.end() if title_start else 0) : case.start()]
    title_lines = [line for line in title_region.splitlines() if inline(line) and not inline(line).isdigit()]
    motion_region = plain[case.end() : date_match.start()]
    motion_lines = [
        line
        for line in motion_region.splitlines()
        if inline(line) and not re.search(r"consolidated|related cross", line, re.IGNORECASE)
    ]
    body = plain[date_match.end() :]
    return [
        make_ruling(
            county="monterey",
            source_sha256=sha,
            source_url=source_url,
            parser_version="monterey-v1",
            style="monterey-one-ruling",
            index=1,
            case_number=case.group(0),
            case_title=" ".join(title_lines) or case.group(0),
            hearing_date=hearing_date,
            full_text=plain,
            body_text=body,
            motion_type=" ".join(motion_lines),
            division=division_hint or "Tentative Rulings",
            dept=dept_hint,
            page_start=1,
            page_end=max(1, len(pages)),
        )
    ]


def parse_tulare_pdf(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:1200])
    dept = dept_hint
    dept_match = re.search(r"DEPARTMENT\s+([A-Z0-9]+)", plain[:800], re.IGNORECASE)
    if dept_match:
        dept = dept_match.group(1)
    if not hearing_date:
        return []
    anchors = list(re.finditer(r"(?m)^\s*(?P<num>[VP]PR\d{6})\s+", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        raw_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        header_match = re.search(
            r"(?m)^\s*Case Number Case Name Type Status Comments\s*$",
            plain[anchor.start():raw_end],
        )
        raw_block = plain[anchor.start():raw_end]
        block_text, trim_at = _trim_or_drop_table_header(raw_block, header_match)
        end = anchor.start() + trim_at if trim_at is not None else raw_end
        block = clean_lines(block_text)
        lines = [inline(line) for line in block.splitlines() if inline(line)]
        if not lines:
            continue
        case_title, motion, body = _split_tulare_probate_row(anchor.group("num"), block)
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="tulare",
                source_sha256=sha,
                source_url=source_url,
                parser_version="tulare-probate-v1",
                style="tulare-probate-table",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=case_title,
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                outcome_text=body,
                division=division_hint or "Probate",
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_tulare_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha:
        return []
    text = html_to_text(html)
    start = text.find("Current Tentative Rulings")
    end = text.find("Probate Examiner Recommendations", start if start != -1 else 0)
    section = text[start : end if end != -1 else len(text)] if start != -1 else text
    hearing_date = find_date(section[:500])
    if not hearing_date:
        return []
    blocks = re.split(r"(?m)^\s*Re:\s*", section)
    rulings: list[Ruling] = []
    for block in blocks[1:]:
        next_case = re.search(
            r"(?is)(?P<title>.*?)\n\s*Case No\.:\s*(?P<num>[A-Za-z0-9-]+).*?"
            r"\n\s*Dept\.?\s*(?P<dept>[^\n]+).*?"
            r"\n\s*Motion:\s*(?P<motion>.*?)\n\s*Tentative Ruling:\s*(?P<body>.*)",
            block,
        )
        if not next_case:
            continue
        dept = inline(next_case.group("dept")).split("The Honorable", 1)[0].strip(" -")
        full = "Re: " + block
        rulings.append(
            make_ruling(
                county="tulare",
                source_sha256=sha,
                source_url=source_url,
                parser_version="tulare-civil-html-v1",
                style="tulare-civil-html",
                index=len(rulings) + 1,
                case_number=next_case.group("num"),
                case_title=next_case.group("title"),
                hearing_date=hearing_date,
                full_text=full,
                body_text=next_case.group("body"),
                motion_type=next_case.group("motion"),
                division="Civil Law and Motion",
                dept=dept or None,
            )
        )
    return rulings


def parse_santa_cruz(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:1000])
    if not hearing_date:
        return []
    anchors = list(re.finditer(r"(?m)^\s*Nos?\.\s+(?P<num>[0-9A-Z,\s]+)\s*$", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        lines = [inline(line) for line in block.splitlines() if inline(line)]
        if len(lines) < 3:
            continue
        case_title = lines[1]
        body_start = 2
        for j in range(2, min(len(lines), 8)):
            if lines[j].upper() != lines[j] or re.search(r"\b(is|are|shall|the|parties)\b", lines[j], re.IGNORECASE):
                body_start = j
                break
        motion = " ".join(lines[2:body_start])
        body = "\n".join(lines[body_start:])
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        case_number = inline(anchor.group("num")).replace(" ", "")
        rulings.append(
            make_ruling(
                county="santa-cruz",
                source_sha256=sha,
                source_url=source_url,
                parser_version="santa-cruz-v1",
                style="santa-cruz-law-motion",
                index=len(rulings) + 1,
                case_number=case_number,
                case_title=case_title,
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=division_hint or "Civil Law and Motion",
                dept=dept_hint,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_san_benito(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:1200])
    if not hearing_date:
        return []
    dept = dept_hint
    dept_match = re.search(r"Courtroom\s+#?(\d+)", plain, re.IGNORECASE)
    if dept_match:
        dept = dept_match.group(1)
    anchors = list(re.finditer(r"(?m)^(?P<num>(?:FL|CU|PR)-\d{2}-\d{5})\s+(?P<title>.+)$", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        raw_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        marker = SAN_BENITO_END_RE.search(plain[anchor.start():raw_end])
        end = anchor.start() + marker.start() if marker else raw_end
        block = clean_lines(plain[anchor.start() : end])
        body = block[block.find(anchor.group("title")) + len(anchor.group("title")) :]
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="san-benito",
                source_sha256=sha,
                source_url=source_url,
                parser_version="san-benito-v1",
                style="san-benito-list",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                division=division_hint or _case_division(anchor.group("num")),
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_butte(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = find_date(plain[:800])
    if not hearing_date:
        return []
    if "Current Probate Tentative Rulings" in plain:
        normalized_pages = [_normalize_butte_probate_page(page) for page in pages]
        normalized, normalized_offsets = join_pages(normalized_pages)
        butte_probate_num = r"(?:\d{2}(?:PR|MH)\d{5}|PR-\d{5})"
        anchors = list(re.finditer(rf"(?m)^\s*\d{{1,2}}:\d{{2}}[ \t]+(?P<num>{butte_probate_num})\b", normalized))
        rulings: list[Ruling] = []
        for i, anchor in enumerate(anchors):
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(normalized)
            block = clean_lines(normalized[anchor.start() : end])
            lines = [inline(line) for line in block.splitlines() if inline(line)]
            tail = re.sub(rf"^\d{{1,2}}:\d{{2}}[ \t]+{butte_probate_num}\b[ \t]*", "", lines[0]).strip() if lines else ""
            tail_lines = ([tail] if tail else []) + lines[1:]
            body_idx = _first_body_line(tail_lines)
            page_start, page_end = _page_span(normalized_offsets, anchor.start(), end)
            rulings.append(
                make_ruling(
                    county="butte",
                    source_sha256=sha,
                    source_url=source_url,
                    parser_version="butte-v1",
                    style="butte-probate-table",
                    index=len(rulings) + 1,
                    case_number=anchor.group("num"),
                    case_title=" ".join(tail_lines[:body_idx]) or anchor.group("num"),
                    hearing_date=hearing_date,
                    full_text=block,
                    body_text=_line_window(tail_lines, body_idx),
                    division=division_hint or "Probate",
                    dept=dept_hint,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
        return rulings

    anchors = list(re.finditer(r"(?m)^\s*\d+(?:-\d+)?\.\s+(?P<num>\d{2}CV\d{5})\s+(?P<title>.+)$", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        motion_match = re.search(r"EVENTS?:\s*(?P<motion>.*?)(?=\n[A-Z][a-z]|\nThe Court|\nAs an initial|\Z)", block, re.DOTALL)
        if motion_match:
            motion = motion_match.group("motion")
            body = block[motion_match.end() :]
        else:
            motion = ""
            body = block
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="butte",
                source_sha256=sha,
                source_url=source_url,
                parser_version="butte-v1",
                style="butte-civil-law-motion",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=division_hint or "Civil Law and Motion",
                dept=dept_hint,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_napa(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    date_match = re.search(r"FOR:\s*([A-Za-z]+ \d{1,2},? \d{4})", plain, re.IGNORECASE)
    hearing_date = parse_date_value(date_match.group(1)) if date_match else find_date(plain[:1000])
    if not hearing_date:
        return []
    case_re = re.compile(r"(?m)^(?P<title>.{3,160}?)\s+(?P<num>(?:\d{2}(?:PR|CV|FL)\d{6}|PR\d{5}))\s*$")
    anchors = list(case_re.finditer(plain))
    rulings: list[Ruling] = []
    current_division = division_hint or "Civil Law and Motion"
    current_dept = dept_hint
    for i, anchor in enumerate(anchors):
        prefix = plain[: anchor.start()]
        section_match = list(re.finditer(r"(?m)^([A-Z][A-Z &/]+CALENDAR).*?Dept\.\s*([A-Z0-9]+)", prefix))
        if section_match:
            section = section_match[-1]
            current_dept = section.group(2)
            current_division = "Probate" if "PROBATE" in section.group(1) else "Civil Law and Motion"
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        ruling_match = re.search(r"TENTATIVE RULING:\s*(?P<body>.*)", block, re.IGNORECASE | re.DOTALL)
        if not ruling_match:
            continue
        before = block[: ruling_match.start()]
        motion_lines = [line for line in before.splitlines()[1:] if inline(line)]
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="napa",
                source_sha256=sha,
                source_url=source_url,
                parser_version="napa-v1",
                style="napa-section-calendar",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=ruling_match.group("body"),
                motion_type=" ".join(motion_lines),
                division=current_division,
                dept=current_dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_san_luis_obispo(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, offsets = _pdf_text(pdf_bytes)
    if not plain or "no tentative rulings" in plain.lower():
        return []
    civil = re.search(r"(?m)^(?P<title>.+?),\s*(?P<num>\d{2}(?:CV|LC)-\d{4})\s*$", plain[:1000])
    if civil:
        date_match = re.search(r"Date:\s*([A-Za-z]+ \d{1,2},? \d{4})", plain, re.IGNORECASE)
        hearing_date = parse_date_value(date_match.group(1)) if date_match else find_date(plain[:1000])
        if not hearing_date:
            return []
        motion_match = re.search(r"Hearing:\s*(?P<motion>.*?)(?:\n\s*\n|Date:)", plain, re.IGNORECASE | re.DOTALL)
        return [
            make_ruling(
                county="san-luis-obispo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="slo-v1",
                style="slo-civil-one-ruling",
                index=1,
                case_number=civil.group("num"),
                case_title=civil.group("title"),
                hearing_date=hearing_date,
                full_text=plain,
                body_text=plain[(date_match.end() if date_match else civil.end()) :],
                motion_type=motion_match.group("motion") if motion_match else "",
                division=division_hint or "Civil Law and Motion",
                dept=dept_hint,
                page_start=1,
                page_end=max(1, len(pages)),
            )
        ]

    hearing_date = find_date(plain[:1200])
    if not hearing_date:
        return []
    dept = dept_hint
    dept_match = re.search(r"in\s+Department\s+([A-Za-z0-9 ]+),", plain[:800], re.IGNORECASE)
    if dept_match:
        dept = inline(dept_match.group(1))
    normalized_pages = [_normalize_slo_probate_page(page) for page in pages]
    plain, offsets = join_pages(normalized_pages)
    slo_probate_num = r"\d{2}(?:PR|CVP|LCP)-\d{4}"
    anchors = list(re.finditer(rf"(?m)^\s*(?:\d+[ \t]+)?(?P<num>{slo_probate_num})\b", plain))
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        raw_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block_text = plain[anchor.start():raw_end]
        block_text, kept_end = _clean_slo_probate_block_text(block_text)
        boilerplate = SLO_PROBATE_BOILERPLATE_RE.search(block_text)
        trim_points = [point for point in [boilerplate.start() if boilerplate else None] if point is not None]
        if trim_points:
            kept_end = min(kept_end, min(trim_points))
            block_text = block_text[: min(trim_points)]
        end = anchor.start() + kept_end if kept_end else raw_end
        block = clean_lines(block_text)
        lines = [inline(line) for line in block.splitlines() if inline(line)]
        tail = re.sub(rf"^(?:\d+[ \t]+)?{slo_probate_num}\b[ \t]*", "", lines[0]).strip() if lines else ""
        tail_lines = ([tail] if tail else []) + lines[1:]
        body_idx = _first_body_line(tail_lines)
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="san-luis-obispo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="slo-v1",
                style="slo-probate-table",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=" ".join(tail_lines[:body_idx]) or anchor.group("num"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=_line_window(tail_lines, body_idx),
                division="Probate",
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_sierra(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, _offsets = _pdf_text(pdf_bytes)
    if not plain or "do not have any tentative rulings" in plain.lower():
        return []
    guardianship_rows = _parse_sierra_guardianship(
        pages,
        plain,
        sha,
        source_url,
        dept_hint,
    )
    if guardianship_rows:
        return guardianship_rows
    match = re.search(
        r"Tentative rulings for (?P<date>[A-Za-z]+ \d{1,2},? \d{4}) in (?P<title>.*?)\s+(?P<num>\d{2}CU\d{4})",
        plain,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    hearing_date = parse_date_value(match.group("date"))
    if not hearing_date:
        return []
    rest = plain[match.end() :]
    lines = [line for line in rest.splitlines() if inline(line)]
    if not lines:
        return []

    allow_multi_section = (
        sha in SIERRA_MULTI_SECTION_SOURCE_SHAS
        or any(marker in source_url for marker in SIERRA_MULTI_SECTION_URL_MARKERS)
    )
    starts = []
    heading_re = re.compile(r"\b(?:Motion|Demurrer|Petition|Application|Order\s+to\s+Show\s+Cause)\b")
    disposition_re = re.compile(
        r"\b(?:is|are)\s+(?:granted|denied|sustained|overruled|off[- ]calendar|continued)\b",
        re.IGNORECASE,
    )
    if allow_multi_section:
        for idx, raw_line in enumerate(lines):
            line = inline(lines[idx])
            if len(line) > 220:
                continue
            if not re.match(r"^(?:Plaintiff|Defendant|Petitioner|Respondent|Applicant)\b", line):
                continue
            if heading_re.search(raw_line) and not disposition_re.search(line):
                starts.append(idx)
        if len(starts) < 2:
            starts = []
        else:
            validated_starts: list[int] = []
            for pos, start_idx in enumerate(starts):
                end_idx = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
                section_lines = lines[start_idx:end_idx]
                early_body = inline(" ".join(section_lines[1:4]))
                if disposition_re.search(early_body):
                    validated_starts.append(start_idx)
            starts = validated_starts if len(validated_starts) == len(starts) else []
    if not starts:
        starts = [0]

    rulings: list[Ruling] = []
    for pos, start_idx in enumerate(starts):
        end_idx = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        section_lines = lines[start_idx:end_idx]
        if not section_lines:
            continue
        body_start = 1
        for rel_idx in range(1, len(section_lines)):
            probe = inline(" ".join(section_lines[rel_idx : rel_idx + 2]))
            if disposition_re.search(probe):
                body_start = rel_idx
                break
        motion = inline(" ".join(section_lines[:body_start]))
        body = "\n".join(section_lines[body_start:]) if body_start < len(section_lines) else ""
        rulings.append(
            make_ruling(
                county="sierra",
                source_sha256=sha,
                source_url=source_url,
                parser_version="sierra-v1",
                style="sierra-law-motion",
                index=len(rulings) + 1,
                case_number=match.group("num"),
                case_title=match.group("title"),
                hearing_date=hearing_date,
                full_text="\n".join(section_lines),
                body_text=body,
                motion_type=motion,
                division=division_hint or "Law and Motion",
                dept=dept_hint,
                page_start=1,
                page_end=max(1, len(pages)),
                outcome_text=inline(" ".join(section_lines[body_start : body_start + 2])),
            )
        )
    return rulings


def _marin_party(text: str) -> str:
    lines = [inline(line) for line in clean_lines(text).splitlines() if inline(line)]
    return " ".join(lines[:2])


def parse_marin(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    pages, plain, offsets = _pdf_text(pdf_bytes)
    if not plain:
        return []
    rulings: list[Ruling] = []
    form_anchors = list(
        re.finditer(
            r"(?im)^DATE:\s*(?P<date>\d{1,2}/\d{1,2}/\d{2,4}).{0,80}?"
            r"DEPT:\s*(?P<dept>[A-Z0-9]+).{0,80}?C\s*ASE\s+NO:\s*(?P<num>[A-Z ]+\d+)",
            plain,
        )
    )
    for i, anchor in enumerate(form_anchors):
        end = form_anchors[i + 1].start() if i + 1 < len(form_anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        ruling_match = re.search(r"(?im)^RULING\s*(?P<body>.*)", block, re.DOTALL)
        if not ruling_match:
            continue
        hearing_date = parse_date_value(anchor.group("date"))
        if not hearing_date:
            continue
        case_number = inline(anchor.group("num")).replace(" ", "")
        motion_match = re.search(
            r"NATURE OF PROCEEDINGS:\s*(?P<motion>.*?)(?=\n\s*RULING\b)",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        plaintiff = re.search(
            r"PLAINTIFFS?:\s*(?P<party>.*?)(?=\n\s*vs\.)",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        defendant = re.search(
            r"DEFENDANTS?:\s*(?P<party>.*?)(?=\n\s*NATURE OF PROCEEDINGS:)",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        petitioner = re.search(
            r"PETITIONER:\s*(?P<party>.*?)(?=\n\s*and\b)",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        respondent = re.search(
            r"RESPONDENT:\s*(?P<party>.*?)(?=\n\s*NATURE OF PROCEEDINGS:)",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if plaintiff and defendant:
            case_title = f"{_marin_party(plaintiff.group('party'))} v. {_marin_party(defendant.group('party'))}"
        elif petitioner and respondent:
            case_title = f"{_marin_party(petitioner.group('party'))} and {_marin_party(respondent.group('party'))}"
        else:
            case_title = case_number
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="marin",
                source_sha256=sha,
                source_url=source_url,
                parser_version="marin-v1",
                style="marin-court-form",
                index=len(rulings) + 1,
                case_number=case_number,
                case_title=case_title,
                hearing_date=hearing_date,
                full_text=block,
                body_text=ruling_match.group("body"),
                motion_type=motion_match.group("motion") if motion_match else "",
                division=division_hint or _case_division(case_number, "Civil"),
                dept=dept_hint or anchor.group("dept"),
                page_start=page_start,
                page_end=page_end,
            )
        )

    probate_date = find_date(plain[:1200])
    probate_anchors = list(re.finditer(r"(?m)^(?P<num>(?:PR|PRO)\d{7})\s+(?P<title>.+)$", plain))
    if probate_date and probate_anchors:
        dept = dept_hint
        dept_match = re.search(r"Department\s+([A-Z0-9]+)", plain[:1200], re.IGNORECASE)
        if dept_match:
            dept = dept_match.group(1)
        for i, anchor in enumerate(probate_anchors):
            end = probate_anchors[i + 1].start() if i + 1 < len(probate_anchors) else len(plain)
            block = clean_lines(plain[anchor.start() : end])
            ruling_match = re.search(r"\bRuling\.\s*(?P<body>.*)", block, re.IGNORECASE | re.DOTALL)
            if not ruling_match:
                continue
            before = block[: ruling_match.start()]
            motion_lines = [inline(line) for line in before.splitlines()[1:] if inline(line)]
            page_start, page_end = _page_span(offsets, anchor.start(), end)
            rulings.append(
                make_ruling(
                    county="marin",
                    source_sha256=sha,
                    source_url=source_url,
                    parser_version="marin-v1",
                    style="marin-probate-calendar",
                    index=len(rulings) + 1,
                    case_number=anchor.group("num"),
                    case_title=anchor.group("title"),
                    hearing_date=probate_date,
                    full_text=block,
                    body_text=ruling_match.group("body"),
                    motion_type=" ".join(motion_lines),
                    division=division_hint or "Probate",
                    dept=dept,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
    return rulings


def parse_san_mateo(
    pdf_bytes: bytes,
    source_url: str,
    source_sha256: str | None = None,
    dept_hint: str | None = None,
    division_hint: str | None = None,
) -> list[Ruling]:
    sha = source_sha(pdf_bytes, source_sha256)
    _pages, plain, offsets = _pdf_text(pdf_bytes)
    hearing_date = None
    date_match = re.search(r"Hearing Date:\s*([0-9/]+)", plain, re.IGNORECASE)
    if date_match:
        hearing_date = parse_date_value(date_match.group(1))
    if not hearing_date:
        hearing_date = find_date(plain[:1500])
    if not hearing_date:
        return []
    dept = dept_hint
    dept_match = re.search(r"Department\s+(\d+)", plain[:1500], re.IGNORECASE)
    if dept_match:
        dept = dept_match.group(1)
    anchor_specs: list[tuple[int, re.Match[str], str | None]] = []
    seen_starts: set[int] = set()
    for anchor in re.finditer(r"(?m)^\s*(?P<num>\d{2}-(?:CIV|CLJ|PRO)-\d{5})\s*$", plain):
        anchor_specs.append((anchor.start(), anchor, None))
        seen_starts.add(anchor.start())
    for anchor in re.finditer(r"(?m)^\s*(?P<num>\d{2}-(?:CIV|CLJ|PRO)-\d{5})\s+(?P<title>.+)$", plain):
        if anchor.start() not in seen_starts:
            anchor_specs.append((anchor.start(), anchor, anchor.group("title")))
            seen_starts.add(anchor.start())
    anchors = [anchor for _start, anchor, title_hint in sorted(anchor_specs, key=lambda item: item[0])]
    title_hints = {anchor.start(): title_hint for _start, anchor, title_hint in anchor_specs}
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(plain)
        block = clean_lines(plain[anchor.start() : end])
        ruling_match = re.search(r"TENTATIVE RULING:\s*(?P<body>.*)", block, re.IGNORECASE | re.DOTALL)
        if not ruling_match:
            continue
        before_raw = block[: ruling_match.start()].splitlines()
        before = [inline(line) for line in before_raw if inline(line)]
        title = ""
        title_hint = title_hints.get(anchor.start())
        if title_hint:
            first_title = inline(title_hint)
            if "-PRO-" in anchor.group("num"):
                first_title = re.split(
                    r"\s+(?:NOTICE|FIRST|PETITION|MOTION|ORDER|ACCOUNT|REPORT)\b",
                    first_title,
                    maxsplit=1,
                )[0]
            title_parts = [first_title] if first_title else []
            case_line_seen = False
            for raw_line in before_raw:
                line = inline(raw_line)
                if not line:
                    if case_line_seen:
                        break
                    continue
                if not case_line_seen:
                    case_line_seen = anchor.group("num") in line
                    continue
                if "-PRO-" in anchor.group("num"):
                    break
                title_parts.append(line)
            title = " ".join(title_parts)
        if not title:
            for line in before[1:]:
                if re.match(r"^(LINE \d+|\d{1,2}:\d{2}\s*[AP]M?)$", line, re.IGNORECASE):
                    continue
                title = line
                break
        motion = ""
        before_text = block[: ruling_match.start()].rstrip()
        paragraphs = [inline(part) for part in re.split(r"\n\s*\n", before_text) if inline(part)]
        if paragraphs:
            motion = paragraphs[-1]
            if anchor.group("num") in motion and len(paragraphs) > 1:
                motion = paragraphs[-2]
        page_start, page_end = _page_span(offsets, anchor.start(), end)
        rulings.append(
            make_ruling(
                county="san-mateo",
                source_sha256=sha,
                source_url=source_url,
                parser_version="san-mateo-v1",
                style="san-mateo-calendar",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=title or anchor.group("num"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=ruling_match.group("body"),
                motion_type=motion,
                division=division_hint or _case_division(anchor.group("num"), "Civil Law and Motion"),
                dept=dept,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return rulings


def parse_los_angeles_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha:
        return []
    text = html_to_text(html)
    raw_parts = re.split(r"Case Number:\s*", text)
    parts: list[str] = []
    for part in raw_parts[1:]:
        header = re.match(
            r"(?P<num>[A-Z0-9]+)\s+Hearing Date:\s*(?P<date>[A-Za-z]+ \d{1,2},? \d{4})\s+Dept:\s*(?P<dept>[A-Z0-9]+)",
            inline(part[:250]),
            re.IGNORECASE,
        )
        if header:
            parts.append(part)
        elif parts:
            parts[-1] += "\nCase Number: " + part
    rulings: list[Ruling] = []
    for part in parts:
        header = re.match(
            r"(?P<num>[A-Z0-9]+)\s+Hearing Date:\s*(?P<date>[A-Za-z]+ \d{1,2},? \d{4})\s+Dept:\s*(?P<dept>[A-Z0-9]+)",
            inline(part[:250]),
            re.IGNORECASE,
        )
        if not header:
            continue
        hearing_date = parse_date_value(header.group("date"))
        if not hearing_date:
            continue
        block = "Case Number: " + part
        title = header.group("num")
        caption = re.search(
            r"(?is)\n\s*(?P<p>[^.\n]{2,120}?)\s*,?\s+Plaintiff\(s\).*?vs\.\s*(?P<d>[^.\n]{2,120}?)\s*,?\s+Defendant",
            block,
        )
        if caption:
            title = f"{inline(caption.group('p'))} v. {inline(caption.group('d'))}"
        motion = ""
        motion_match = re.search(r"ORDER RE:\s*(?P<motion>.*?)(?:\n\s*Dept\.|\n\s*Dept\s)", block, re.IGNORECASE | re.DOTALL)
        if motion_match:
            motion = motion_match.group("motion")
        body = block
        intro = re.search(r"\n\s*(?:I\.|INTRODUCTION|Introduction|Background|Discussion)\b", block, re.IGNORECASE)
        if intro:
            body = block[intro.start() :]
        rulings.append(
            make_ruling(
                county="los-angeles",
                source_sha256=sha,
                source_url=source_url,
                parser_version="los-angeles-html-v1",
                style="la-webforms-result",
                index=len(rulings) + 1,
                case_number=header.group("num"),
                case_title=title,
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division="Civil Law and Motion",
                dept=header.group("dept"),
            )
        )
    return rulings


def parse_stanislaus_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha:
        return []
    text = html_to_text(html)
    date_match = re.search(
        r"(?im)^\s*Date:\s*([A-Za-z]+ \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{2,4})\s*$",
        text,
    )
    hearing_date = parse_date_value(date_match.group(1)) if date_match else find_date(text)
    if not hearing_date:
        return []
    anchors = list(re.finditer(r"(?m)^(?P<num>(?:CV|FL|PR|UD)-\d{2}-\d{6})\s+[-–]\s+(?P<title>.+)$", text))
    rulings: list[Ruling] = []
    current_dept = None
    for i, anchor in enumerate(anchors):
        prefix = text[: anchor.start()]
        dept_matches = list(re.finditer(r"Department\s+#?\s*(\d+)|Department\s+(\d+)", prefix, re.IGNORECASE))
        if dept_matches:
            current_dept = next(g for g in dept_matches[-1].groups() if g)
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        block = clean_lines(text[anchor.start() : end])
        after_title = block[block.find(anchor.group("title")) + len(anchor.group("title")) :]
        motion, _, body = after_title.partition(" - ")
        if not body:
            body = after_title
        rulings.append(
            make_ruling(
                county="stanislaus",
                source_sha256=sha,
                source_url=source_url,
                parser_version="stanislaus-html-v1",
                style="stanislaus-html",
                index=len(rulings) + 1,
                case_number=anchor.group("num"),
                case_title=anchor.group("title"),
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=_case_division(anchor.group("num")),
                dept=current_dept,
            )
        )
    return rulings


def parse_sonoma_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha:
        return []
    text = html_to_text(html)
    stop = text.find("Was this helpful?")
    if stop != -1:
        text = text[:stop]
    hearing_date = find_date(text)
    if not hearing_date:
        return []
    case_num = r"(?:SCV|SPR|PR|FL|[0-9]{2}[A-Z]{2,3})[ -]?\d{4,}"
    anchor_specs: list[dict] = []
    seen: set[int] = set()
    for match in re.finditer(rf"(?m)^(?P<num>{case_num}),?[ \t]+(?P<title>.+)$", text):
        if match.start() in seen:
            continue
        seen.add(match.start())
        anchor_specs.append(
            {
                "start": match.start(),
                "match": match,
                "num": match.group("num"),
                "title": match.group("title"),
            }
        )
    for match in re.finditer(rf"(?m)^(?P<num>{case_num})\s*$", text):
        if match.start() in seen:
            continue
        prefix = text[: match.start()]
        prev_lines = [line for line in prefix.splitlines() if inline(line)]
        title = prev_lines[-1] if prev_lines else match.group("num")
        title_start = prefix.rfind(title) if title else match.start()
        start = title_start if title_start != -1 else match.start()
        seen.add(match.start())
        anchor_specs.append(
            {
                "start": start,
                "match": match,
                "num": match.group("num"),
                "title": title,
            }
        )
    anchors = sorted(anchor_specs, key=lambda item: item["start"])
    rulings: list[Ruling] = []
    for i, anchor in enumerate(anchors):
        raw_end = anchors[i + 1]["start"] if i + 1 < len(anchors) else len(text)
        marker = SONOMA_END_RE.search(text[anchor["start"] : raw_end])
        end = anchor["start"] + marker.start() if marker else raw_end
        block = clean_lines(text[anchor["start"] : end])
        if not block:
            continue
        ruling_match = re.search(r"TENTATIVE RULING:\s*(?P<body>.*)", block, re.IGNORECASE | re.DOTALL)
        if ruling_match:
            body = ruling_match.group("body")
            before = block[: ruling_match.start()]
            before_lines = [inline(line) for line in before.splitlines() if inline(line)]
            motion = ""
            for line in reversed(before_lines):
                if anchor["num"] in line or line == inline(anchor["title"]):
                    continue
                motion = line
                break
            style = "sonoma-html-ruling"
        else:
            body = block
            motion = ""
            style = "sonoma-html-list"
        division = "Civil"
        low_url = source_url.lower()
        if "probate" in low_url or anchor["num"].upper().startswith(("PR", "SPR")):
            division = "Probate"
        elif "family" in low_url or anchor["num"].upper().startswith("FL"):
            division = "Family Law"
        rulings.append(
            make_ruling(
                county="sonoma",
                source_sha256=sha,
                source_url=source_url,
                parser_version="sonoma-html-v1",
                style=style,
                index=len(rulings) + 1,
                case_number=anchor["num"].replace(" ", ""),
                case_title=anchor["title"],
                hearing_date=hearing_date,
                full_text=block,
                body_text=body,
                motion_type=motion,
                division=division,
            )
        )
    return rulings


def parse_santa_barbara_page(html: str, capture: dict) -> list[Ruling]:
    sha = capture.get("source_sha256")
    source_url = capture.get("source_url") or capture.get("url") or ""
    if not sha or "/tentative-ruling/" not in source_url:
        return []
    text = html_to_text(html)
    start = text.rfind("Tentative Ruling:")
    if start == -1:
        return []
    stop = text.find("Was this helpful?", start)
    section = clean_lines(text[start : stop if stop != -1 else len(text)])
    lines = [inline(line) for line in section.splitlines() if inline(line)]
    if not lines or not lines[0].startswith("Tentative Ruling:"):
        return []
    title = inline(lines[0].split(":", 1)[1])
    labels = {
        "Case Number",
        "Case Type",
        "Hearing Date / Time",
        "Nature of Proceedings",
        "Tentative Ruling",
        "Judges",
    }

    def field(label: str) -> str:
        try:
            idx = lines.index(label)
        except ValueError:
            return ""
        values: list[str] = []
        for line in lines[idx + 1 :]:
            if line in labels:
                break
            values.append(line)
        return "\n".join(values)

    case_number = field("Case Number")
    hearing_date = parse_date_value(field("Hearing Date / Time"))
    ruling_body = field("Tentative Ruling")
    if not case_number or not hearing_date or not ruling_body:
        return []
    case_type = field("Case Type")
    judges = field("Judges")
    dept = None
    dept_match = re.search(r"Dept\.\s*([^\n]+)", judges, re.IGNORECASE)
    if dept_match:
        dept = inline(dept_match.group(1))
    return [
        make_ruling(
            county="santa-barbara",
            source_sha256=sha,
            source_url=source_url,
            parser_version="santa-barbara-html-v1",
            style="santa-barbara-detail-page",
            index=1,
            case_number=case_number,
            case_title=title,
            hearing_date=hearing_date,
            full_text=section,
            body_text=ruling_body,
            motion_type=field("Nature of Proceedings"),
            division=case_type or None,
            dept=dept,
        )
    ]
