# speckit_specify — Write or update the project spec

## When to use

Use this skill to save or update the project specification. The spec defines
WHAT to build and WHY — not HOW (that's the plan).

## Usage

```bash
python -m skills.speckit_specify.scripts.save_spec \
    --workdir <project-workdir> \
    --file /tmp/spec.md \
    [--version v1] \
    [--project-id <uuid>]
```

Write the spec content to a temp file first, then pass it via `--file`.
If `--project-id` is given, also syncs to the `project.spec` database field.

## Spec Template

A good spec includes:

```markdown
# <Feature/App Name>

## User Stories
- As a [user type], I want [goal] so that [reason]

## Functional Requirements
- FR1: [requirement]
- FR2: [requirement]

## Non-Functional Requirements
- NFR1: [performance, security, etc.]

## Acceptance Checklist
- [ ] criterion 1
- [ ] criterion 2
```

## Guidelines

- Focus on WHAT and WHY, not HOW
- Be specific: "users can filter by date range" not "filtering support"
- Include acceptance criteria that can be objectively verified
- Write in the user's language (French for French projects)
