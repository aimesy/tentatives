"""Los Angeles County public WebForms tentative-ruling discovery."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote

from counties.common import PageRef, clean_text
from counties.new_county_parsers import parse_los_angeles_page as parse_page_capture

BASE = "https://www.lacourt.ca.gov/tentativeRulingNet/ui/main.aspx?casetype=civil"
LANDING_PAGES = [BASE]

HIDDEN_RE = re.compile(
    r'<input\s+type="hidden"\s+name="(?P<name>__VIEWSTATE|__VIEWSTATEGENERATOR|__EVENTVALIDATION)"'
    r'[^>]*\svalue="(?P<value>[^"]*)"',
    re.IGNORECASE,
)
OPTION_RE = re.compile(
    r'<option\s+value="(?P<value>[^"]+)">(?P<label>.*?)</option>',
    re.IGNORECASE | re.DOTALL,
)
SELECT_NAME = "ctl00$ctl00$siteMasterHolder$basicBodyHolder$List2DeptDate"


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def _hidden_fields(html: str) -> dict[str, str]:
    return {m.group("name"): unescape(m.group("value")) for m in HIDDEN_RE.finditer(html)}


def discover_live_page_extra(session, errors=None):
    response = session.get(BASE, timeout=60)
    response.raise_for_status()
    hidden = _hidden_fields(response.text)
    if not {"__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"}.issubset(hidden):
        return []

    refs: list[PageRef] = []
    for match in OPTION_RE.finditer(response.text):
        value = unescape(match.group("value"))
        label = clean_text(re.sub(r"<[^>]+>", " ", unescape(match.group("label"))))
        data = dict(hidden)
        data[SELECT_NAME] = value
        refs.append(
            PageRef(
                url=BASE,
                source_url=f"{BASE}&dept_date={quote(value, safe='')}",
                title=f"Los Angeles {label or value}",
                page_kind="tentative_ruling_result",
                method="POST",
                data=data,
            )
        )
    return refs
