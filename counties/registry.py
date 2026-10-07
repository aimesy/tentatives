"""County scraper discovery helpers.

The repo has two county capabilities: discovery/backfill modules that publish
landing pages, and parser modules that can turn archived captures into rows.
This registry derives both from the scraper modules so ingest entry points do
not maintain drifting county lists.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

COUNTIES_DIR = Path(__file__).parent


def slug_from_package(package_name: str) -> str:
    return package_name.replace("_", "-")


def _scraper_module_paths() -> dict[str, str]:
    modules: dict[str, str] = {}
    for child in COUNTIES_DIR.iterdir():
        if not child.is_dir() or child.name.startswith("__"):
            continue
        if not (child / "scraper.py").exists():
            continue
        modules[slug_from_package(child.name)] = f"counties.{child.name}.scraper"
    return dict(sorted(modules.items()))


def _import_module(module_path: str) -> ModuleType:
    return importlib.import_module(module_path)


def scraper_modules() -> dict[str, ModuleType]:
    return {slug: _import_module(path) for slug, path in _scraper_module_paths().items()}


def discovery_module_paths() -> dict[str, str]:
    modules: dict[str, str] = {}
    for slug, module_path in _scraper_module_paths().items():
        module = _import_module(module_path)
        if getattr(module, "LANDING_PAGES", None) or getattr(module, "WAYBACK_PDF_PATTERNS", None):
            modules[slug] = module_path
    return modules


def discovery_modules() -> dict[str, ModuleType]:
    return {slug: _import_module(path) for slug, path in discovery_module_paths().items()}


def parser_functions() -> dict[str, Callable]:
    parsers: dict[str, Callable] = {}
    for slug, module in scraper_modules().items():
        parse = getattr(module, "parse", None)
        if callable(parse):
            parsers[slug] = parse
    return parsers


def parser_source_extensions() -> dict[str, set[str]]:
    extensions: dict[str, set[str]] = {}
    for slug, module in scraper_modules().items():
        parse = getattr(module, "parse", None)
        if not callable(parse):
            continue
        raw = getattr(module, "PARSE_EXTENSIONS", {".pdf"})
        normalized = {str(ext).lower() if str(ext).startswith(".") else f".{str(ext).lower()}" for ext in raw}
        extensions[slug] = normalized or {".pdf"}
    return extensions


def page_parser_functions() -> dict[str, Callable]:
    parsers: dict[str, Callable] = {}
    for slug, module in scraper_modules().items():
        parse = getattr(module, "parse_page_capture", None)
        if callable(parse):
            parsers[slug] = parse
    return parsers
