from counties.riverside.scraper import BASE, discover_live


def test_discover_reader_markdown_links_and_no_tentatives():
    html = """
    * [Department 260](https://www.riverside.courts.ca.gov/system/files/2023-10/2%20-%20No%20Tentatives%20Dept.%20260.pdf "2 - No Tentatives Dept. 260")
    * [Department 02 - Honorable Steven G. Counelis](https://www.riverside.courts.ca.gov/system/files/2023-10/Riv02ruling102323.pdf "Riv02ruling")
    * [Department PS1 - Honorable Arthur Hester III](https://www.riverside.courts.ca.gov/system/files/2026-06/PS1ruling060526.pdf "PS1ruling")
    """

    refs = discover_live(html, page_url=BASE)

    assert [ref.filename for ref in refs] == [
        "2 - No Tentatives Dept. 260.pdf",
        "Riv02ruling102323.pdf",
        "PS1ruling060526.pdf",
    ]
    assert [ref.dept_hint for ref in refs] == ["260", "02", "PS1"]
