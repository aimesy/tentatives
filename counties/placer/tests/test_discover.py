"""Tests for Placer's discover_live."""
from __future__ import annotations

from pathlib import Path

from counties.placer.scraper import discover_live

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def test_discover_live_finds_law_and_motion_pdfs():
    html = (FIXTURE_DIR / "law-motion-page.html").read_text(encoding="utf-8")
    refs = discover_live(html)
    assert refs, "expected at least one PDF link"
    urls = [r.url for r in refs]
    # All should be the canonical /sites/default/files/<YYYY-MM>/...pdf shape.
    for url in urls:
        assert "placer.courts.ca.gov/sites/default/files/" in url
        assert url.endswith(".pdf")
    # Deduplicated.
    assert len(urls) == len(set(urls))
    # Filename is unquoted so %20 round-trips back to a space.
    spaces_present = any(" " in r.filename for r in refs)
    assert spaces_present, "expected '<MDDYY> Web.pdf' style filenames to keep their space"


def test_discover_live_ignores_unrelated_pdfs():
    """A stray link to an off-domain PDF should not be picked up."""
    html = '<a href="https://example.com/sites/default/files/2026-05/something.pdf">noise</a>'
    refs = discover_live(html)
    assert refs == []
