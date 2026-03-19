"""Tool call taxonomy classification.

Classifies agent tool calls into categories for observability.
Used by the web UI to filter and display tool activity in a sidebar.

## Taxonomy

Categories follow the pattern "Group: subtype". Groups are:

### API (external data sources - high observability value)
- API: Matomo           - Analytics queries via MatomoAPI client
- API: Metabase         - SQL queries via MetabaseAPI client
- API: Matomo + Metabase - Comparison scripts using both
- API: Matomo (curl)    - Direct curl to Matomo API
- API: GitHub           - Fetching code from GitHub
- API: GitHub (clone)   - Cloning repos for code search
- API: curl             - Other curl requests

### Read (file access)
- Read: knowledge       - Site docs, methodology (/knowledge/)
- Read: skill definition - skill.md files
- Read: skill code      - Python code in /skills/
- Read: code            - Application code (.py, .js, .html)
- Read: docs            - CLAUDE.md, README
- Read: temp            - Temporary output files
- Read: other           - Everything else

### Write (file creation)
- Write: temp           - Intermediate files in /tmp/
- Write: interactive    - User-facing dashboards (/interactive/)
- Write: script         - One-off Python scripts
- Write: knowledge      - Updating knowledge base
- Write: other          - Everything else

### Edit (file modification)
- Edit: knowledge       - Knowledge base updates
- Edit: skill           - Skill file changes
- Edit: code            - Code modifications
- Edit: other           - Everything else

### Execute
- Execute: script       - Running Python scripts

### Query
- Query: SQLite         - Local database queries

### Search
- Search: codebase      - Glob/Grep operations

### Shell (low-level operations - usually hidden)
- Shell: git            - Git operations (not clone)
- Shell: explore        - ls, cat, head, tail, grep, find
- Shell: setup          - pip, npm, mkdir, cp, which, node
- Shell: other          - Uncategorized shell commands

### Skill
- Skill: {name}         - Skill invocations (matomo_query, save_report, etc.)

### System (internal - hidden by default)
- Thinking: todo        - TodoWrite for internal task tracking
- System: task          - Task/TaskOutput/KillShell
- Web: fetch            - WebFetch/WebSearch
- Interaction: ask user - AskUserQuestion

### Other
- Other: {tool}         - Unknown tools

## Visibility

Categories are grouped by visibility level for the sidebar:
- PUBLIC: Shown to all users (API calls, knowledge reads)
- ADMIN: Only shown to admin users (most shell operations, system tasks)
"""

# Categories visible to all users (high observability value)
PUBLIC_CATEGORIES = {
    # API calls - most important for observability
    "API: Matomo",
    "API: Metabase",
    "API: Matomo + Metabase",
    "API: Matomo (curl)",
    "API: GitHub",
    "API: GitHub (clone)",
    # Knowledge access
    "Read: knowledge",
    "Read: skill definition",
    "Read: docs",
    # User-facing outputs
    "Write: interactive",
    # Skills
    "Skill: matomo_query",
    "Skill: metabase_query",
    "Skill: save_report",
}

# Categories only visible to admins
ADMIN_CATEGORIES = {
    # Everything else - shell operations, temp files, system tasks, etc.
}


def is_public_category(category: str) -> bool:
    """Check if a category should be visible to non-admin users."""
    # Exact match
    if category in PUBLIC_CATEGORIES:
        return True
    # Skill: * pattern (all skills are public)
    if category.startswith("Skill: "):
        return True
    return False


def classify_tool(tool_name: str, tool_input: dict) -> str:
    """Classify a tool call into a taxonomy category.

    Args:
        tool_name: The tool being called (Bash, Read, Write, Edit, etc.)
        tool_input: The input parameters for the tool

    Returns:
        Category string like "API: Matomo", "Read: knowledge", etc.
    """
    if tool_name == "Bash":
        return _classify_bash(tool_input.get("command", ""))

    elif tool_name == "Read":
        return _classify_read(tool_input.get("file_path", ""))

    elif tool_name == "Write":
        return _classify_write(tool_input.get("file_path", ""))

    elif tool_name == "Edit":
        return _classify_edit(tool_input.get("file_path", ""))

    elif tool_name == "Skill":
        skill = tool_input.get("skill", "unknown")
        return f"Skill: {skill}"

    elif tool_name in ("Glob", "Grep"):
        return "Search: codebase"

    elif tool_name == "TodoWrite":
        return "Thinking: todo"

    elif tool_name in ("WebFetch", "WebSearch"):
        return "Web: fetch"

    elif tool_name in ("Task", "TaskOutput", "KillShell"):
        return "System: task"

    elif tool_name == "AskUserQuestion":
        return "Interaction: ask user"

    return f"Other: {tool_name}"


def _classify_bash(cmd: str) -> str:
    """Classify a Bash command."""
    # API calls - check these first (most important for observability)
    has_matomo = "MatomoAPI" in cmd or "matomo_api" in cmd or "execute_matomo_query" in cmd
    has_metabase = (
        "MetabaseAPI" in cmd or "metabase_api" in cmd or "execute_sql" in cmd or "execute_metabase_query" in cmd
    )

    if has_matomo and has_metabase:
        return "API: Matomo + Metabase"
    if has_matomo:
        return "API: Matomo"
    if has_metabase:
        return "API: Metabase"

    # Curl-based API calls
    if "curl" in cmd:
        if "matomo" in cmd.lower() or "inclusion" in cmd:
            return "API: Matomo (curl)"
        if "github" in cmd.lower():
            return "API: GitHub"
        return "API: curl"

    # Git operations
    if "git clone" in cmd:
        return "API: GitHub (clone)"
    if "git " in cmd:
        return "Shell: git"

    # Script execution
    if "python" in cmd or ".py" in cmd:
        return "Execute: script"

    # Database
    if "sqlite3" in cmd:
        return "Query: SQLite"

    # File system exploration
    if any(x in cmd for x in ["ls ", "cat ", "head ", "tail ", "grep ", "find "]):
        return "Shell: explore"

    # Setup/diagnostic
    if any(x in cmd for x in ["pip ", "npm ", "mkdir ", "cp ", "which ", "node "]):
        return "Shell: setup"

    return "Shell: other"


def _classify_read(path: str) -> str:
    """Classify a Read operation by file path."""
    if "/knowledge/" in path:
        return "Read: knowledge"
    if "/skills/" in path and "skill.md" in path:
        return "Read: skill definition"
    if "/skills/" in path:
        return "Read: skill code"
    if ".py" in path or ".js" in path or ".html" in path:
        return "Read: code"
    if "/tmp/" in path:
        return "Read: temp"
    if "AGENTS" in path or "CLAUDE" in path or "README" in path:
        return "Read: docs"
    return "Read: other"


def _classify_write(path: str) -> str:
    """Classify a Write operation by file path."""
    if "/tmp/" in path:
        return "Write: temp"
    if "/interactive/" in path:
        return "Write: interactive"
    if "/scripts/" in path or ".py" in path:
        return "Write: script"
    if "/knowledge/" in path:
        return "Write: knowledge"
    return "Write: other"


def _classify_edit(path: str) -> str:
    """Classify an Edit operation by file path."""
    if "/knowledge/" in path:
        return "Edit: knowledge"
    if "/skills/" in path:
        return "Edit: skill"
    if ".py" in path or ".js" in path:
        return "Edit: code"
    return "Edit: other"
