# speckit_checklist — Quality validation criteria

## When to use

Use this skill to create or update the quality checklist. The checklist contains
"unit tests for English" — objective validation criteria that can be checked
against the implementation.

## Usage

```bash
python -m skills.speckit_checklist.scripts.save_checklist \
    --workdir <project-workdir> \
    --file /tmp/checklist.md \
    [--version v1]
```

## Checklist Template

```markdown
# Quality Checklist

## Functional
- [ ] User can [action from spec]
- [ ] [Feature] handles [edge case]

## Technical
- [ ] Dockerfile builds successfully
- [ ] App starts and responds on configured port
- [ ] Environment variables documented in README
- [ ] Error responses return appropriate HTTP status codes

## Deployment
- [ ] Staging deploy succeeds
- [ ] App accessible via deploy URL
- [ ] No hardcoded secrets in code
```

## Guidelines

- Each item should be objectively verifiable (yes/no)
- Derive items from the spec's acceptance criteria
- Include deployment-related checks
- Keep it concise — 10-20 items max
