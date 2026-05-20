from counties.orange.scraper import discover_live


def test_discovers_orange_tentative_pdfs_from_index_page():
    html = """
    <a href="/sites/default/files/oc/default/tentative-rulings/wclasterrulings.pdf">
      CLASTER, William D. - Dept CX101
    </a>
    <a href="/sites/default/files/oc/default/forms/not-a-ruling.pdf">Form</a>
    """
    refs = discover_live(
        html,
        page_url="https://www.occourts.org/online-services/tentative-rulings/civil-tentative-rulings",
    )
    assert len(refs) == 1
    assert refs[0].filename == "wclasterrulings.pdf"
    assert refs[0].division_hint == "Civil"
