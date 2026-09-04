"""Small shared helpers for county-specific discovery.

Parsing tentative-ruling source files stays county-specific. Link discovery is
less specialized: most court pages expose anchors or dropdown options that
point at files. These helpers keep that plumbing out of each scraper without
imposing a generic parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse


@dataclass(frozen=True)
class PdfRef:
    """A ruling source document discovered from a court page or Wayback CDX."""

    url: str
    filename: str
    wayback_ts: str | None = None
    dept_hint: str | None = None
    division_hint: str | None = None
    link_text: str = ""
    source_page_url: str | None = None


@dataclass(frozen=True)
class PageRef:
    """A ruling source page to preserve as raw HTML.

    Most counties expose PDFs, but some current tentative-ruling surfaces are
    HTML pages or form results. `source_url` is the logical URL recorded in
    provenance; for POST-backed pages it can include the selected department or
    date even when the fetch URL is a shared endpoint.
    """

    url: str
    title: str
    page_kind: str = "tentative_rulings_page"
    source_url: str | None = None
    method: str = "GET"
    data: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HtmlLink:
    """A link-like item from HTML.

    `tag` is usually "a" or "option". Dropdown pages, including Amador, put
    the PDF URL in an option value rather than an anchor href.
    """

    tag: str
    url: str
    text: str
    attrs: dict[str, str]
    parent_attrs: dict[str, str] | None = None


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[HtmlLink] = []
        self._select_stack: list[dict[str, str]] = []
        self._current: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag == "select":
            self._select_stack.append(attr_map)
            return
        if tag == "a" and attr_map.get("href"):
            self._current = {
                "tag": "a",
                "url": attr_map["href"],
                "attrs": attr_map,
                "parent_attrs": None,
                "text": [],
            }
            return
        if tag == "option" and attr_map.get("value"):
            parent = self._select_stack[-1] if self._select_stack else None
            self._current = {
                "tag": "option",
                "url": attr_map["value"],
                "attrs": attr_map,
                "parent_attrs": parent,
                "text": [],
            }

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "select" and self._select_stack:
            self._select_stack.pop()
            return
        if self._current is not None and tag == self._current["tag"]:
            text = clean_text("".join(self._current["text"]))
            self.links.append(
                HtmlLink(
                    tag=self._current["tag"],
                    url=self._current["url"],
                    text=text,
                    attrs=dict(self._current["attrs"]),
                    parent_attrs=(
                        dict(self._current["parent_attrs"])
                        if self._current["parent_attrs"]
                        else None
                    ),
                )
            )
            self._current = None


def clean_text(value: str) -> str:
    return " ".join(value.split())


MARKDOWN_SOURCE_LINK_RE = re.compile(
    r"\[(?P<text>[^\]]*)\]\("
    r"(?P<url>[^)\s]+?\.(?:pdf|docx)(?:\?[^)\s]*)?)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|[^)]*))?"
    r"\)",
    re.IGNORECASE,
)


def extract_links(html: str) -> list[HtmlLink]:
    parser = _LinkParser()
    parser.feed(html)
    links = list(parser.links)
    seen = {(link.tag, link.url, link.text) for link in links}
    for match in MARKDOWN_SOURCE_LINK_RE.finditer(html):
        link = HtmlLink(
            tag="markdown-a",
            url=match.group("url"),
            text=clean_text(match.group("text")),
            attrs={},
            parent_attrs=None,
        )
        key = (link.tag, link.url, link.text)
        if key in seen:
            continue
        seen.add(key)
        links.append(link)
    return links


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = unquote(path.rsplit("/", 1)[-1])
    return name or "tentative-ruling.pdf"


def absolute_url(raw_url: str, page_url: str) -> str:
    return urljoin(page_url, raw_url)


def unique_refs(refs: list[PdfRef]) -> list[PdfRef]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    out: list[PdfRef] = []
    for ref in refs:
        key = (ref.url, ref.wayback_ts, ref.dept_hint, ref.division_hint)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out
