# speckit_init — Initialize project spec structure

## When to use

Use this skill when creating a new expert-mode project. It sets up the `.specify/`
directory structure with templates for all spec-kit artifacts.

## Usage

```bash
python -m skills.speckit_init.scripts.init_project --workdir <project-workdir>
```

## What it creates

```
.specify/
├── memory/
│   └── constitution.md     # Project principles (empty template)
├── specs/
│   └── v1/
│       ├── spec.md          # Requirements (template)
│       ├── plan.md          # Technical plan (template)
│       ├── tasks.md         # Task breakdown (template)
│       └── checklist.md     # Quality checklist (template)
└── templates/
    ├── spec-template.md
    ├── plan-template.md
    └── tasks-template.md
```

## Notes

- Safe to run multiple times (skips existing files)
- Called automatically when a new project is created via the web UI
