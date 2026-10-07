from counties.san_francisco.scraper import discover_live


def test_discovers_san_francisco_family_pdf_links():
    html = """
    <a href="https://webapps.sftc.org/ufctr/files/Dept%20403/Tentative%20Rulings/Tuesday/403%20Tentative%20Rulings%205.19.2026.pdf">
      403 Tentative Rulings 5.19.2026.pdf
    </a>
    <a href="https://webapps.sftc.org/site/files/other.pdf">Other PDF</a>
    """
    refs = discover_live(html)
    assert len(refs) == 1
    assert refs[0].dept_hint == "403"
    assert refs[0].division_hint == "Family Law"
