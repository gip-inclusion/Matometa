"""Save spec content to .specify/specs/<version>/spec.md and optionally sync to DB."""

import argparse
import sys
from pathlib import Path


def save_spec(workdir: str, content: str, version: str = "v1", project_id: str | None = None):
    """Save spec content to file and optionally sync to database."""
    spec_path = Path(workdir) / ".specify" / "specs" / version / "spec.md"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(content)
    print(f"Saved spec to {spec_path}")

    if project_id:
        _sync_to_db(project_id, content)


def _sync_to_db(project_id: str, content: str):
    """Sync spec content to project.spec in database."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
        from web.storage import store
        store.update_project(project_id, spec=content)
        print(f"Synced spec to database for project {project_id}")
    except Exception as e:
        print(f"Warning: could not sync to database: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Save project spec")
    parser.add_argument("--workdir", required=True, help="Project working directory")
    parser.add_argument("--file", required=True, help="Path to spec content file")
    parser.add_argument("--version", default="v1", help="Spec version (default: v1)")
    parser.add_argument("--project-id", help="Project ID for DB sync")
    args = parser.parse_args()

    content = Path(args.file).read_text()
    save_spec(args.workdir, content, args.version, args.project_id)


if __name__ == "__main__":
    main()
