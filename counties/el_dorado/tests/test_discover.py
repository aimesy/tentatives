from pathlib import Path

from counties.el_dorado.scraper import discover_live, discover_dept_pages

FIXTURE = Path(__file__).parent.parent / "fixtures" / "dept-9-index.html"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8", errors="replace")


def test_discover_live_finds_all_tentative_pdfs():
    refs = discover_live(_html())
    urls = [r.url for r in refs]
    # 19 dated PDFs under /tentative-rulings/. There is also a "public-notice" PDF
    # under /general/ — that one is not a tentative ruling so we don't pick it up.
    assert len(refs) == 19, f"expected 19, got {len(refs)}: {urls}"
    assert all("/system/files/tentative-rulings/" in u for u in urls)


def test_discover_live_recognises_filename_variants():
    refs = {r.filename for r in discover_live(_html())}
    # Canonical
    assert "tr-d-09-2026-05-18.pdf" in refs
    # Drupal-style collision suffix
    assert "tr-d-09-2026-03-27_0.pdf" in refs
    # Numeric-suffix collision
    assert "tr-d-09-2026-04-031.pdf" in refs
    # Date-range form
    assert "tr-d-09-2026-03-23-26.pdf" in refs


def test_discover_dept_pages_lists_all_twelve():
    urls = discover_dept_pages(_html())
    # The page links to depts 1..12 in its nav.
    assert len(urls) == 12, urls
    assert urls[0].endswith("tentative-rulings-dept-1")
