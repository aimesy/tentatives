from counties.calaveras.scraper import discover_live


def test_discovers_calaveras_static_pdf_links():
    html = """
    <a href="/system/files/general/05202026-cmc.pdf">05/20/2026 CMC Tentative Rulings</a>
    <a href="/system/files/general/local-rules.pdf">Local Rules</a>
    """
    refs = discover_live(
        html,
        page_url="https://www.calaveras.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-case-management",
    )
    assert len(refs) == 1
    assert refs[0].url == "https://www.calaveras.courts.ca.gov/system/files/general/05202026-cmc.pdf"
    assert refs[0].division_hint == "Case Management"
