"""Santa Barbara County public HTML tentative-ruling discovery."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse

from counties.common import PageRef, absolute_url, clean_text, extract_links
from counties.new_county_parsers import parse_santa_barbara_page as parse_page_capture

BASE = "https://www.santabarbara.courts.ca.gov"
LANDING_PAGES = [
    f"{BASE}/online-services/tentative-rulings",
    f"{BASE}/tentative-rulings",
]
PAGE_CAPTURE_URLS = [
    PageRef(
        url=f"{BASE}/tentative-rulings",
        title="Santa Barbara Tentative Rulings",
        page_kind="tentative_rulings_index",
    )
]


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def discover_live_pages(html: str, page_url: str | None = None):
    source_page = page_url or f"{BASE}/tentative-rulings"
    refs: list[PageRef] = []
    for link in extract_links(html):
        url = absolute_url(link.url, source_page)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.santabarbara.courts.ca.gov", "santabarbara.courts.ca.gov"}:
            continue
        if "/tentative-ruling" not in parsed.path.lower():
            continue
        refs.append(
            PageRef(
                url=url,
                title=clean_text(link.text) or "Santa Barbara tentative ruling",
                page_kind="tentative_ruling_detail" if "/tentative-ruling/" in parsed.path.lower() else "tentative_rulings_index",
            )
        )
    return refs


def _judge_ids(html: str) -> list[str]:
    ids = set()
    for match in re.finditer(r'name="field_judge_target_id"[\s\S]*?</select>', html, re.IGNORECASE):
        for option in re.finditer(r'<option[^>]+value="(?P<id>\d+)"', match.group(0), re.IGNORECASE):
            ids.add(option.group("id"))
    for link in extract_links(html):
        parsed = urlparse(link.url)
        query = parse_qs(parsed.query)
        for value in query.get("field_judge_target_id", []):
            if value.isdigit():
                ids.add(value)
    return sorted(ids, key=int)


def _detail_page_refs(html: str, page_url: str) -> list[PageRef]:
    refs: list[PageRef] = []
    for link in extract_links(html):
        url = absolute_url(link.url, page_url)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"www.santabarbara.courts.ca.gov", "santabarbara.courts.ca.gov"}:
            continue
        if not parsed.path.lower().startswith("/tentative-ruling/"):
            continue
        refs.append(
            PageRef(
                url=url,
                title=clean_text(link.text) or "Santa Barbara tentative ruling",
                page_kind="tentative_ruling_detail",
            )
        )
    return refs


def _last_page_number(html: str) -> int:
    pages = [0]
    for match in re.finditer(r'[?&]page=(\d+)', html):
        pages.append(int(match.group(1)))
    return min(max(pages), 25)


def discover_live_page_extra(session, errors=None):
    refs: list[PageRef] = []
    landing = session.get(f"{BASE}/tentative-rulings", timeout=60)
    landing.raise_for_status()
    for judge_id in _judge_ids(landing.text):
        first_url = f"{BASE}/tentative-rulings?{urlencode({'case_number': '', 'field_judge_target_id': judge_id})}"
        first = session.get(first_url, timeout=60)
        first.raise_for_status()
        refs.append(
            PageRef(
                url=first_url,
                title=f"Santa Barbara judge {judge_id} tentative rulings",
                page_kind="tentative_rulings_index",
            )
        )
        refs.extend(_detail_page_refs(first.text, first_url))
        for page in range(1, _last_page_number(first.text) + 1):
            page_url = f"{first_url}&page={page}"
            response = session.get(page_url, timeout=60)
            response.raise_for_status()
            refs.append(
                PageRef(
                    url=page_url,
                    title=f"Santa Barbara judge {judge_id} tentative rulings page {page + 1}",
                    page_kind="tentative_rulings_index",
                )
            )
            refs.extend(_detail_page_refs(response.text, page_url))
    return refs
