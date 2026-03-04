# speckit_tasks — Generate task breakdown

## When to use

Use this skill after the plan is finalized. Tasks decompose the plan into
ordered, actionable work items.

## Usage

```bash
python -m skills.speckit_tasks.scripts.save_tasks \
    --workdir <project-workdir> \
    --file /tmp/tasks.md \
    [--version v1]
```

## Tasks Template

```markdown
# Tasks

## Phase 1: Foundation
- [ ] Task 1: description
- [ ] Task 2: description [P] (can run in parallel with Task 1)

## Phase 2: Core Features
- [ ] Task 3: description (depends on Phase 1)
- [ ] Task 4: description

## Phase 3: Polish
- [ ] Task 5: description
- [ ] Task 6: description
```

## Guidelines

- Order matters: earlier tasks should not depend on later ones
- Mark parallel tasks with [P]
- Each task should be completable in one agent turn
- Include setup tasks (Dockerfile, project skeleton) in Phase 1
- Include testing/validation tasks in the final phase
