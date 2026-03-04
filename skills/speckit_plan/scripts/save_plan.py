"""Save technical plan to .specify/specs/<version>/plan.md."""

import argparse
from pathlib import Path


def save_plan(workdir: str, content: str, version: str = "v1"):
    """Save plan content to file."""
    plan_path = Path(workdir) / ".specify" / "specs" / version / "plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(content)
    print(f"Saved plan to {plan_path}")


def main():
    parser = argparse.ArgumentParser(description="Save technical plan")
    parser.add_argument("--workdir", required=True, help="Project working directory")
    parser.add_argument("--file", required=True, help="Path to plan content file")
    parser.add_argument("--version", default="v1", help="Spec version (default: v1)")
    args = parser.parse_args()

    content = Path(args.file).read_text()
    save_plan(args.workdir, content, args.version)


if __name__ == "__main__":
    main()
