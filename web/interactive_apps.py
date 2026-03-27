"""Scan and cache interactive apps under data/interactive (S3 or local)."""

from datetime import datetime

from . import config, s3

apps_cache: list[dict] | None = None


def parse_app_md(content: str, folder_name: str) -> dict | None:
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    fm = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            fm[key.strip().lower()] = value.strip()

    if "title" not in fm:
        return None

    updated = None
    if "updated" in fm:
        try:
            updated = datetime.strptime(fm["updated"], "%Y-%m-%d")
        except ValueError:
            pass

    tags = []
    if "tags" in fm:
        raw_tags = fm["tags"]
        if raw_tags.startswith("[") and raw_tags.endswith("]"):
            tags = [t.strip() for t in raw_tags[1:-1].split(",") if t.strip()]
        else:
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

    authors = []
    if "authors" in fm:
        authors = [a.strip() for a in fm["authors"].split(",") if a.strip()]

    return {
        "slug": folder_name,
        "title": fm.get("title"),
        "description": fm.get("description", ""),
        "website": fm.get("website"),
        "category": fm.get("category"),
        "tags": tags,
        "authors": authors,
        "conversation_id": fm.get("conversation_id"),
        "updated": updated,
        "url": f"/interactive/{folder_name}/",
        "is_interactive": True,
    }


def invalidate_apps_cache():
    global apps_cache
    apps_cache = None


def scan_interactive_apps():
    """
    Scan /data/interactive/ for valid apps (S3 or local filesystem).

    An app is valid if it has an APP.md file with YAML front-matter.
    Returns list of dicts matching report structure where possible.

    Results are cached and invalidated on write (when sync_to_s3 uploads
    an APP.md file).
    """
    global apps_cache

    if apps_cache is not None:
        return apps_cache

    apps = scan_interactive_apps_uncached()
    apps_cache = apps
    return apps


def scan_interactive_apps_uncached():
    apps = []

    if config.USE_S3:
        directories = s3.list_directories()
        for folder_name in directories:
            app_md_content = s3.download_file(f"{folder_name}/APP.md")
            if app_md_content:
                try:
                    content = app_md_content.decode("utf-8")
                    app = parse_app_md(content, folder_name)
                    if app:
                        apps.append(app)
                except UnicodeDecodeError:
                    continue
    else:
        if not config.INTERACTIVE_DIR.exists():
            return []

        for folder in config.INTERACTIVE_DIR.iterdir():
            if not folder.is_dir():
                continue

            app_md = folder / "APP.md"
            if not app_md.exists():
                continue

            content = app_md.read_text()
            app = parse_app_md(content, folder.name)
            if app:
                apps.append(app)

    apps.sort(key=lambda a: (a["updated"] or datetime.min, a["title"]), reverse=True)
    return apps
