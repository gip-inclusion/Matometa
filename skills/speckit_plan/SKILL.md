# speckit_plan — Create technical plan

## When to use

Use this skill after the spec is finalized. The plan turns requirements into
a technical architecture — HOW to build what the spec describes.

## Usage

```bash
python -m skills.speckit_plan.scripts.save_plan \
    --workdir <project-workdir> \
    --file /tmp/plan.md \
    [--version v1]
```

## Plan Template

```markdown
# Technical Plan

## Architecture
- Backend: [framework, language]
- Frontend: [approach]
- Database: [type, schema overview]

## Data Model
- [Table/collection descriptions]

## API / Pages
- [Endpoint or page list with methods]

## Dependencies
- [Python packages, JS libraries, external services]

## Deployment
- Docker setup
- Environment variables needed
- Port mappings
```

## Guidelines

- Reference the spec: every architectural choice should trace back to a requirement
- Be concrete: name specific libraries, frameworks, file paths
- Include the Dockerfile approach
- Keep it actionable — someone should be able to start coding from this
