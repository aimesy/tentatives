"""Helpers for counties whose public pages expose direct PDF links."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import ParseResult, urlparse

from counties.common import PdfRef, absolute_url, extract_links, filename_from_url, unique_refs

LinkPredicate = Callable[[ParseResult, str], bool]
HintFunc = Callable[[ParseResult, str, str], str | None]


def discover_static_pdfs(
    html: str,
    *,
    page_url: str,
    allowed_hosts: set[str],
    path_test: LinkPredicate | None = None,
    text_test: Callable[[str], bool] | None = None,
    default_division: str | None = None,
    dept_hint: HintFunc | None = None,
    division_hint: HintFunc | None = None,
) -> list[PdfRef]:
    refs: list[PdfRef] = []
    for link in extract_links(html):
        if ".pdf" not in link.url.lower():
            continue
        url = absolute_url(link.url, page_url)
        parsed = urlparse(url)
        if parsed.netloc.lower() not in allowed_hosts:
            continue
        link_text = link.text
        if path_test and not path_test(parsed, link_text):
            continue
        if text_test and not text_test(link_text):
            continue
        refs.append(
            PdfRef(
                url=url,
                filename=filename_from_url(url),
                dept_hint=dept_hint(parsed, link_text, page_url) if dept_hint else None,
                division_hint=(
                    division_hint(parsed, link_text, page_url)
                    if division_hint
                    else default_division
                ),
                link_text=link_text,
                source_page_url=page_url,
            )
        )
    return unique_refs(refs)
