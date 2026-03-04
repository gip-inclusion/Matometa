"""Save quality checklist to .specify/specs/<version>/checklist.md."""

import argparse
from pathlib import Path


def save_checklist(workdir: str, content: str, version: str = "v1"):
    """Save checklist content to file."""
    checklist_path = Path(workdir) / ".specify" / "specs" / version / "checklist.md"
    checklist_path.parent.mkdir(parents=True, exist_ok=True)
    checklist_path.write_text(content)
    print(f"Saved checklist to {checklist_path}")


def main():
    parser = argparse.ArgumentParser(description="Save quality checklist")
    parser.add_argument("--workdir", required=True, help="Project working directory")
    parser.add_argument("--file", required=True, help="Path to checklist content file")
    parser.add_argument("--version", default="v1", help="Spec version (default: v1)")
    args = parser.parse_args()

    content = Path(args.file).read_text()
    save_checklist(args.workdir, content, args.version)


if __name__ == "__main__":
    main()
