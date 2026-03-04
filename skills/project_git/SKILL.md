# project_git — Git operations for expert-mode projects

## When to use

Use this skill when you need to initialize a Gitea repository for a project, push code, create branches, or check status.

## Available commands

```bash
python -m skills.project_git.scripts.git_ops init --project-id <uuid>
python -m skills.project_git.scripts.git_ops push --project-id <uuid> -m "commit message"
python -m skills.project_git.scripts.git_ops status --project-id <uuid>
python -m skills.project_git.scripts.git_ops branch --project-id <uuid> --name <branch-name>
```

## Workflow

1. **init**: Creates a Gitea repo, clones it locally, initializes the `.specify/` structure for spec-driven development. Updates the project record with `gitea_url` and sets status to `active`.

2. **push**: Stages all changes in the project working directory, commits with the given message, and pushes to the remote.

3. **status**: Shows `git status` and recent commits for the project.

4. **branch**: Creates a new feature branch from `main`.

## Notes

- The working directory for each project is `data/projects/<project-id>/`
- The spec is stored in `.specify/` (spec-kit structure) for structured development
- CLAUDE.md in repo root is supported for backwards compatibility
- Always commit and push after making significant changes
