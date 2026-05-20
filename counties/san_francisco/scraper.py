"""San Francisco Unified Family Court tentative-ruling discovery.

The attached UFC page at webapps.sftc.org lists current and previous family
law tentative-ruling PDFs for departments 403, 404, and 414. This module
discovers those PDFs for capture. The main San Francisco civil archive remains
in `aimesy/sfsc-tentatives`.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs

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
