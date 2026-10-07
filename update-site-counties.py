#!/usr/bin/env python3
"""Refresh the viewer county manifest from published Parquet databases."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
MANIFEST = HERE / "site" / "counties.json"

COUNTY_META = {
    "amador": ("Amador", "AMA"),
    "butte": ("Butte", "BUT"),
    "calaveras": ("Calaveras", "CAL"),
    "contra-costa": ("Contra Costa", "CC"),
    "el-dorado": ("El Dorado", "ELD"),
    "fresno": ("Fresno", "FRE"),
    "imperial": ("Imperial", "IMP"),
    "los-angeles": ("Los Angeles", "LA"),
    "marin": ("Marin", "MRN"),
    "merced": ("Merced", "MER"),
    "monterey": ("Monterey", "MON"),
    "napa": ("Napa", "NAP"),
    "nevada": ("Nevada", "NEV"),
    "orange": ("Orange", "ORA"),
    "placer": ("Placer", "PLA"),
    "plumas": ("Plumas", "PLU"),
    "riverside": ("Riverside", "RIV"),
    "san-benito": ("San Benito", "SBT"),
    "san-bernardino": ("San Bernardino", "SBD"),
    "san-francisco": ("San Francisco UFC", "SF"),
    "san-luis-obispo": ("San Luis Obispo", "SLO"),
    "san-mateo": ("San Mateo", "SMT"),
    "santa-barbara": ("Santa Barbara", "SB"),
    "santa-clara": ("Santa Clara", "SCL"),
    "santa-cruz": ("Santa Cruz", "SCZ"),
    "shasta": ("Shasta", "SHA"),
    "sierra": ("Sierra", "SIE"),
    "solano": ("Solano", "SOL"),
    "sonoma": ("Sonoma", "SON"),
    "stanislaus": ("Stanislaus", "STA"),
    "tulare": ("Tulare", "TUL"),
    "tuolumne": ("Tuolumne", "TUO"),
    "ventura": ("Ventura", "VEN"),
    "yolo": ("Yolo", "YOL"),
}


def fallback_label(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-"))


def fallback_code(slug: str, used: set[str]) -> str:
    compact = "".join(part[0] for part in slug.split("-")).upper()
    if len(compact) >= 2 and compact not in used:
        return compact
    letters = "".join(ch for ch in slug.upper() if ch.isalpha())
    for width in range(3, min(len(letters), 6) + 1):
        candidate = letters[:width]
        if candidate not in used:
            return candidate
    suffix = 2
    base = letters[:3] or "CTY"
    candidate = base
    while candidate in used:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def county_databases() -> list[dict[str, str]]:
    used_codes: set[str] = set()
    entries: list[dict[str, str]] = []
    for parquet in sorted(DATA_DIR.glob("*/rulings.parquet")):
        slug = parquet.parent.name
        label, code = COUNTY_META.get(slug, (fallback_label(slug), ""))
        code = code or fallback_code(slug, used_codes)
        used_codes.add(code)
        entries.append({"slug": slug, "label": label, "code": code})
    return sorted(entries, key=lambda item: (item["label"], item["slug"]))


def main() -> None:
    entries = county_databases()
    MANIFEST.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {MANIFEST.relative_to(HERE)} with {len(entries)} counties")


if __name__ == "__main__":
    main()
