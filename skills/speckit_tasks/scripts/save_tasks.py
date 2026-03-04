"""Save task breakdown to .specify/specs/<version>/tasks.md."""

import argparse
from pathlib import Path


def save_tasks(workdir: str, content: str, version: str = "v1"):
    """Save tasks content to file."""
    tasks_path = Path(workdir) / ".specify" / "specs" / version / "tasks.md"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(content)
    print(f"Saved tasks to {tasks_path}")


def main():
    parser = argparse.ArgumentParser(description="Save task breakdown")
    parser.add_argument("--workdir", required=True, help="Project working directory")
    parser.add_argument("--file", required=True, help="Path to tasks content file")
    parser.add_argument("--version", default="v1", help="Spec version (default: v1)")
    args = parser.parse_args()

    content = Path(args.file).read_text()
    save_tasks(args.workdir, content, args.version)


if __name__ == "__main__":
    main()
