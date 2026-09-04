"""Public Google Drive discovery helpers for court-linked ruling folders."""

from __future__ import annotations

import codecs
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

import requests

from counties.common import PdfRef, unique_refs

FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"
DRIVE_ALLOWED_SOURCE_HOSTS = {
    "drive.google.com",
    "drive.usercontent.google.com",
    "googleusercontent.com",
}


@dataclass(frozen=True)
class DriveFolderSpec:
    folder_id: str
    label: str
    division_hint: str | None = None


def drive_file_download_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def drive_file_ref(
    file_id: str,
    filename: str,
    *,
    source_page_url: str | None = None,
    division_hint: str | None = None,
    link_text: str = "",
) -> PdfRef:
    return PdfRef(
        url=drive_file_download_url(file_id),
        filename=filename,
        division_hint=division_hint,
        link_text=link_text or filename,
        source_page_url=source_page_url,
    )


def _decode_drive_ivd(html: str) -> list:
    match = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'(?P<data>(?:\\.|[^'])*)'", html)
    if not match:
        return []
    # Google emits a JS string full of \xNN escapes. It decodes to JSON arrays.
    decoded = match.group("data").encode("utf-8").decode("unicode_escape")
    try:
        data = json.loads(decoded)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _drive_items(data: object) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []

    def walk(value: object) -> None:
        if not isinstance(value, list):
            return
        if (
            len(value) >= 4
            and isinstance(value[0], str)
            and isinstance(value[2], str)
            and isinstance(value[3], str)
        ):
            out.append((value[0], value[2], value[3]))
        for item in value:
            walk(item)

    walk(data)
    seen: set[tuple[str, str, str]] = set()
    deduped: list[tuple[str, str, str]] = []
    for row in out:
        if row in seen:
            continue
        seen.add(row)
        deduped.append(row)
    return deduped


def _folder_html(session: requests.Session, folder_id: str) -> str:
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def _looks_like_ruling_pdf(filename: str, path_parts: Iterable[str]) -> bool:
    haystack = " ".join([filename, *path_parts]).lower()
    if not filename.lower().endswith(".pdf"):
        return False
    if re.search(r"\b(civility|guidelines|pre[-_ ]?trial|checklist|standing case management)\b", haystack):
        return False
    return bool(
        re.search(
            r"\b(tentative|ruling|rulings|probate|notes?|law\s*(?:&|and)\s*motion|guardianship|cmc)\b",
            haystack,
        )
    )


def discover_drive_folder_refs(
    session: requests.Session,
    specs: Iterable[DriveFolderSpec],
    *,
    max_depth: int = 4,
) -> list[PdfRef]:
    refs: list[PdfRef] = []
    visited: set[str] = set()

    def visit(folder_id: str, path_parts: list[str], division_hint: str | None, depth: int) -> None:
        if folder_id in visited or depth > max_depth:
            return
        visited.add(folder_id)
        source_page_url = f"https://drive.google.com/drive/folders/{folder_id}"
        for item_id, name, mime in _drive_items(_decode_drive_ivd(_folder_html(session, folder_id))):
            if mime == FOLDER_MIME:
                visit(item_id, [*path_parts, name], division_hint, depth + 1)
            elif mime == PDF_MIME and _looks_like_ruling_pdf(name, path_parts):
                refs.append(
                    drive_file_ref(
                        item_id,
                        name,
                        source_page_url=source_page_url,
                        division_hint=division_hint or " / ".join(path_parts) or None,
                        link_text=" / ".join([*path_parts, name]),
                    )
                )

    for spec in specs:
        visit(spec.folder_id, [spec.label], spec.division_hint, 0)
    return unique_refs(refs)
