"""Napa County public Drive-folder tentative-ruling source discovery."""

from __future__ import annotations

from counties.drive import DRIVE_ALLOWED_SOURCE_HOSTS, DriveFolderSpec, discover_drive_folder_refs
from counties.new_county_parsers import parse_napa as parse

BASE = "https://www.napa.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]
ALLOWED_SOURCE_HOSTS = DRIVE_ALLOWED_SOURCE_HOSTS
DRIVE_FOLDERS = [
    DriveFolderSpec(
        folder_id="1vSASGAyk4T89vX0ZBUkSx3Q1TTmOWUgw",
        label="Tentative Rulings",
        division_hint="Civil Law and Motion",
    )
]


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def discover_live_extra(session, errors=None):
    return discover_drive_folder_refs(session, DRIVE_FOLDERS)
