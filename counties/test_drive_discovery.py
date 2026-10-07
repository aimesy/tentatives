from counties.drive import DriveFolderSpec, discover_drive_folder_refs


def test_drive_folder_discovery_decodes_ivd_and_filters_pdfs():
    payload = (
        "[[[\"file1\",[\"folder\"],\"06-24-26 Tentative Rulings.pdf\",\"application/pdf\"],"
        "[\"file2\",[\"folder\"],\"Attorney Civility Guidelines.pdf\",\"application/pdf\"]]]"
    )
    html = "window['_DRIVE_ivd'] = '" + "".join(f"\\x{ord(c):02x}" for c in payload) + "';"

    class _Response:
        text = html

        def raise_for_status(self):
            pass

    class _Session:
        def get(self, url, timeout=60):
            return _Response()

    refs = discover_drive_folder_refs(
        _Session(),
        [DriveFolderSpec("folder", "Tentative Rulings", "Civil")],
    )

    assert [ref.filename for ref in refs] == ["06-24-26 Tentative Rulings.pdf"]
    assert refs[0].url == "https://drive.google.com/uc?export=download&id=file1"
