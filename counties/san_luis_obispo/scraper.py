"""San Luis Obispo County public Drive-folder tentative-ruling discovery."""

from __future__ import annotations

from counties.drive import DRIVE_ALLOWED_SOURCE_HOSTS, DriveFolderSpec, discover_drive_folder_refs
from counties.new_county_parsers import parse_san_luis_obispo as parse

BASE = "https://www.slo.courts.ca.gov/online-services/tentative-rulings"
LANDING_PAGES = [BASE]
ALLOWED_SOURCE_HOSTS = DRIVE_ALLOWED_SOURCE_HOSTS
DRIVE_FOLDERS = [
    DriveFolderSpec("105nBjUlY-Cb1AogxP5c-l-1CheZPZxPv", "Probate", "Probate"),
    DriveFolderSpec("1WRQz2iCZOTgHIJltXo6sWacWfHDQDwRc", "Department 4", "Department 4"),
    DriveFolderSpec("1vOJ9ekW7V0DQ4ilfLaG_SPA7nXwi-llm", "Department P2", "Department P2"),
    DriveFolderSpec("1KdWLYAhoOA1i7g2wh0-Aw_bnymc-amdl", "Department 2", "Department 2"),
    DriveFolderSpec("1Z0GY_vBMlOrQfjXc3XxVijPd6NzzIA_J", "Department 7", "Department 7"),
]


def discover_live(_html: str, page_url: str | None = None, base_url: str = BASE):
    return []


def discover_live_extra(session, errors=None):
    return discover_drive_folder_refs(session, DRIVE_FOLDERS)
