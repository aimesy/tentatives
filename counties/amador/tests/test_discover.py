from counties.amador.scraper import discover_live, ref_from_wayback_url


def test_discovers_dropdown_option_pdfs_with_divisions():
    html = """
    <select id="SelectID1">
      <option value="./tentativeRulings/CivilLawAndMotion/2022/062722.pdf">June 27, 2022</option>
    </select>
    <select id="SelectID2">
      <option value="./tentativeRulings/CivilCaseMgtConference/2022/020922.pdf">February 09, 2022</option>
    </select>
    <select id="SelectID3">
      <option value="./tentativeRulings/FamilyLawCaseMgt/2022/020922.pdf">February 09, 2022</option>
    </select>
    <select id="SelectID4">
      <option value="./tentativeRulings/ChildSupport/2022/02042022.pdf">February 04, 2022</option>
    </select>
    """
    refs = discover_live(html)
    assert len(refs) == 4
    assert refs[0].url == "https://www.amadorcourt.org/tentativeRulings/CivilLawAndMotion/2022/062722.pdf"
    assert {r.division_hint for r in refs} == {
        "Civil Law and Motion",
        "Civil Case Management Conference",
        "Family Law Case Management",
        "Child Support",
    }


def test_deduplicates_repeated_urls():
    html = """
    <select id="SelectID1">
      <option value="./tentativeRulings/CivilLawAndMotion/2022/062722.pdf">June 27, 2022</option>
      <option value="./tentativeRulings/CivilLawAndMotion/2022/062722.pdf">June 27, 2022 duplicate</option>
    </select>
    """
    assert len(discover_live(html)) == 1


def test_ref_from_wayback_url_infers_division_from_path():
    ref = ref_from_wayback_url(
        "https://www.amadorcourt.org/tentativeRulings/CivilLawAndMotion/2022/041122.pdf",
        wayback_ts="20230324203624",
    )
    assert ref.filename == "041122.pdf"
    assert ref.wayback_ts == "20230324203624"
    assert ref.division_hint == "Civil Law and Motion"
