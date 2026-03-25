"""Shared helper functions for the web application."""

import re
import uuid
from pathlib import Path

from . import config

# Knowledge path constants
KNOWLEDGE_ROOT = (config.BASE_DIR / "knowledge").resolve()
KNOWLEDGE_DRAFTS_ROOT = config.BASE_DIR / "data" / "knowledge-drafts"
ALLOWED_EXTENSIONS = {".md"}


def validate_knowledge_path(file_param: str) -> Path | None:
    """
    Validate and resolve a knowledge file path.
    Returns None if invalid/unsafe.
    """
    if not file_param:
        return None

    # Reject obvious attacks early
    if ".." in file_param or file_param.startswith("/"):
        return None

    # Only allow simple alphanumeric + hyphen/underscore/dot + slash
    if not re.match(r"^[a-zA-Z0-9_\-./]+\.md$", file_param):
        return None

    # No double slashes, no hidden files
    if "//" in file_param or "/." in file_param:
        return None

    # Resolve full path
    candidate = (KNOWLEDGE_ROOT / file_param).resolve()

    # CRITICAL: ensure it's inside knowledge/
    try:
        candidate.relative_to(KNOWLEDGE_ROOT)
    except ValueError:
        return None  # Path escapes knowledge/

    # Must exist and be a file
    if not candidate.is_file():
        return None

    # Extension check (belt + suspenders)
    if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
        return None

    return candidate


def _validate_conv_id(conv_id: str) -> bool:
    try:
        uuid.UUID(conv_id)
        return True
    except (ValueError, AttributeError):
        return False


def get_staging_dir(conv_id: str) -> Path:
    if not _validate_conv_id(conv_id):
        raise ValueError("Invalid conversation ID")
    return KNOWLEDGE_DRAFTS_ROOT / conv_id


def list_staged_files(conv_id: str) -> list[str]:
    if not _validate_conv_id(conv_id):
        return []
    staging_dir = get_staging_dir(conv_id)
    if not staging_dir.exists():
        return []

    files = []
    for f in staging_dir.rglob("*.md"):
        try:
            rel_path = f.relative_to(staging_dir)
            files.append(str(rel_path))
        except ValueError:
            pass
    return sorted(files)


def list_knowledge_files() -> dict[str, list[dict]]:
    sections = {}

    for f in sorted(KNOWLEDGE_ROOT.rglob("*.md")):
        if any(part.startswith(".") for part in f.parts):
            continue

        rel_path = f.relative_to(KNOWLEDGE_ROOT)
        # Section is the parent directory path (e.g., "stats", "stats/cards")
        # Use "." for root-level files
        section = str(rel_path.parent) if rel_path.parent != Path(".") else "."

        # Humanize the name
        name = f.stem
        name = re.sub(r"^\d{4}-\d{2}(-\d{2})?[-_]?", "", name)
        name = re.sub(r"[-_]+", " ", name)
        if name:
            name = name[0].upper() + name[1:]

        if section not in sections:
            sections[section] = []

        sections[section].append(
            {
                "path": str(rel_path),
                "name": name,
                "modified": f.stat().st_mtime,
            }
        )

    # Sort sections by name, with top-level folders first
    return dict(sorted(sections.items(), key=lambda x: (x[0].count("/"), x[0])))


def list_knowledge_sections() -> dict[str, list[dict]]:
    mb_icon = "ri-pie-chart-2-line"
    meta = {
        "README": {"label": "README", "icon": "ri-file-text-line", "group": "Généralités"},
        "methodology": {"label": "Méthodologie", "icon": "ri-file-text-line", "group": "Généralités"},
        "webinaires": {"label": "Webinaires", "icon": "ri-live-line", "group": "Généralités"},
        "metabase": {"label": "Metabase API", "icon": "ri-book-open-line", "group": "Metabase", "order": 0},
        "stats": {"label": "Stats", "icon": mb_icon, "group": "Metabase"},
        "datalake": {"label": "Datalake", "icon": mb_icon, "group": "Metabase"},
        "dora": {"label": "Dora", "icon": mb_icon, "group": "Metabase"},
        "rdvi": {"label": "RDVI", "icon": mb_icon, "group": "Metabase"},
        "matomo": {"label": "Matomo API", "icon": "ri-line-chart-line", "group": "Matomo et sites"},
        "sites": {"label": "Sites", "icon": "ri-global-line", "group": "Matomo et sites"},
        "notion": {"label": "Notion API", "icon": "ri-booklet-line", "group": "Notion"},
    }
    skip: set[str] = set()

    groups: dict[str, list[dict]] = {}

    for f in sorted(KNOWLEDGE_ROOT.iterdir()):
        if f.name.startswith("."):
            continue
        key = f.stem if f.is_file() else f.name

        if key in skip:
            continue

        info = meta.get(key, {})
        group = info.get("group", "Autres")

        entry: dict = {
            "name": info.get("label", key.capitalize()),
            "icon": info.get("icon", "ri-folder-line"),
            "_order": info.get("order", 1),
        }

        if f.is_file() and f.suffix == ".md":
            entry["url"] = f"/connaissances/{f.name}"
        elif f.is_dir():
            md_files = list(f.rglob("*.md"))
            if len(md_files) == 1:
                rel = md_files[0].relative_to(KNOWLEDGE_ROOT)
                entry["url"] = f"/connaissances/{rel}"
            else:
                entry["url"] = f"/connaissances?section={f.name}"
                entry["count"] = len(md_files)
        else:
            continue

        groups.setdefault(group, []).append(entry)

    for items in groups.values():
        items.sort(key=lambda e: e.pop("_order"))

    return groups
