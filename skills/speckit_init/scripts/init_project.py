"""Initialize .specify/ directory structure for a project."""

import argparse
from pathlib import Path

CONSTITUTION_TEMPLATE = """\
# Project Constitution

<!-- Define the core principles and constraints for this project. -->
<!-- Examples: target audience, tech constraints, design philosophy -->
"""

SPEC_TEMPLATE = """\
# Specification

## User Stories

## Functional Requirements

## Non-Functional Requirements

## Acceptance Checklist
- [ ] (to be defined)
"""

PLAN_TEMPLATE = """\
# Technical Plan

## Architecture

## Data Model

## API / Pages

## Dependencies

## Deployment
"""

TASKS_TEMPLATE = """\
# Tasks

## Phase 1: Foundation
- [ ] (to be defined)

## Phase 2: Core Features
- [ ] (to be defined)

## Phase 3: Polish
- [ ] (to be defined)
"""

CHECKLIST_TEMPLATE = """\
# Quality Checklist

## Functional
- [ ] (to be defined)

## Technical
- [ ] Dockerfile builds successfully
- [ ] App starts and responds on configured port

## Deployment
- [ ] Staging deploy succeeds
- [ ] No hardcoded secrets in code
"""


def init_specify(workdir: str) -> list[str]:
    """Create .specify/ structure. Returns list of created files."""
    root = Path(workdir) / ".specify"
    created = []

    files = {
        root / "memory" / "constitution.md": CONSTITUTION_TEMPLATE,
        root / "specs" / "v1" / "spec.md": SPEC_TEMPLATE,
        root / "specs" / "v1" / "plan.md": PLAN_TEMPLATE,
        root / "specs" / "v1" / "tasks.md": TASKS_TEMPLATE,
        root / "specs" / "v1" / "checklist.md": CHECKLIST_TEMPLATE,
        root / "templates" / "spec-template.md": SPEC_TEMPLATE,
        root / "templates" / "plan-template.md": PLAN_TEMPLATE,
        root / "templates" / "tasks-template.md": TASKS_TEMPLATE,
    }

    for path, content in files.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            created.append(str(path.relative_to(Path(workdir))))

    return created


def main():
    parser = argparse.ArgumentParser(description="Initialize .specify/ structure")
    parser.add_argument("--workdir", required=True, help="Project working directory")
    args = parser.parse_args()

    created = init_specify(args.workdir)
    if created:
        print(f"Created {len(created)} files:")
        for f in created:
            print(f"  {f}")
    else:
        print(".specify/ structure already exists.")


if __name__ == "__main__":
    main()
