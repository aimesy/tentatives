from counties.contra_costa.scraper import discover_live


def test_discover_live_reads_retired_iframe_pdf_links():
    html = """
    <html><body>
      <a href="TR\\Department 09 - Judge Devine\\09_122225.pdf">Dec 22, 2025</a>
      <a href="/civil/docs/Tentative_Ruling_Instructions_for_Dept_9.pdf">Instructions</a>
      <a href="https://example.com/not-a-ruling.pdf">Other PDF</a>
      <a href="TR\\Department 10 - Judge Campins\\10_052826.pdf">May 28, 2026</a>
    </body></html>
    """

    refs = discover_live(
        html,
        page_url="https://retired.cc-courts.org/civil/motions-hearings-tentative.aspx",
    )

    assert [r.dept_hint for r in refs] == ["9", "10"]
    assert refs[0].url == (
        "https://retired.cc-courts.org/civil/TR/"
        "Department%2009%20-%20Judge%20Devine/09_122225.pdf"
    )
    assert refs[0].filename == "09_122225.pdf"
    assert refs[0].link_text == "Dec 22, 2025"
    assert all("Instructions" not in r.link_text for r in refs)
