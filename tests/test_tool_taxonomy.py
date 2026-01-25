"""
Tests for lib/tool_taxonomy.py - tool call classification.

Run with: pytest tests/test_tool_taxonomy.py -v
"""

import pytest

from lib.tool_taxonomy import classify_tool, is_public_category, PUBLIC_CATEGORIES


class TestClassifyTool:
    """Tests for classify_tool function."""

    # --- Bash: API calls ---

    def test_bash_matomo_api(self):
        result = classify_tool("Bash", {"command": "python -c 'from lib._matomo import MatomoAPI'"})
        assert result == "API: Matomo"

    def test_bash_matomo_api_instance(self):
        result = classify_tool("Bash", {"command": "matomo_api.request('VisitsSummary.get')"})
        assert result == "API: Matomo"

    def test_bash_metabase_api(self):
        result = classify_tool("Bash", {"command": "python -c 'from lib._metabase import MetabaseAPI'"})
        assert result == "API: Metabase"

    def test_bash_metabase_execute_sql(self):
        result = classify_tool("Bash", {"command": "api.execute_sql('SELECT 1')"})
        assert result == "API: Metabase"

    def test_bash_both_apis(self):
        result = classify_tool("Bash", {
            "command": "from lib._matomo import MatomoAPI; from lib._metabase import MetabaseAPI"
        })
        assert result == "API: Matomo + Metabase"

    def test_bash_curl_matomo(self):
        result = classify_tool("Bash", {"command": "curl https://matomo.inclusion.gouv.fr/..."})
        assert result == "API: Matomo (curl)"

    def test_bash_curl_github(self):
        result = classify_tool("Bash", {"command": "curl https://api.github.com/repos/..."})
        assert result == "API: GitHub"

    def test_bash_curl_other(self):
        result = classify_tool("Bash", {"command": "curl https://example.com/api"})
        assert result == "API: curl"

    def test_bash_git_clone(self):
        result = classify_tool("Bash", {"command": "git clone https://github.com/gip-inclusion/les-emplois"})
        assert result == "API: GitHub (clone)"

    def test_bash_git_other(self):
        result = classify_tool("Bash", {"command": "git status"})
        assert result == "Shell: git"

    # --- Bash: Script execution ---

    def test_bash_python_inline(self):
        result = classify_tool("Bash", {"command": "python -c 'print(1)'"})
        assert result == "Execute: script"

    def test_bash_python_file(self):
        result = classify_tool("Bash", {"command": ".venv/bin/python script.py"})
        assert result == "Execute: script"

    def test_bash_sqlite(self):
        result = classify_tool("Bash", {"command": "sqlite3 ./data/matometa.db 'SELECT 1'"})
        assert result == "Query: SQLite"

    # --- Bash: Shell operations ---

    def test_bash_explore_ls(self):
        result = classify_tool("Bash", {"command": "ls -la /app"})
        assert result == "Shell: explore"

    def test_bash_explore_cat(self):
        result = classify_tool("Bash", {"command": "cat /tmp/output.txt"})
        assert result == "Shell: explore"

    def test_bash_setup_pip(self):
        result = classify_tool("Bash", {"command": "pip install pandas"})
        assert result == "Shell: setup"

    def test_bash_setup_mkdir(self):
        result = classify_tool("Bash", {"command": "mkdir -p /tmp/test"})
        assert result == "Shell: setup"

    def test_bash_other(self):
        result = classify_tool("Bash", {"command": "echo hello"})
        assert result == "Shell: other"

    # --- Read operations ---

    def test_read_knowledge(self):
        result = classify_tool("Read", {"file_path": "/app/knowledge/sites/emplois.md"})
        assert result == "Read: knowledge"

    def test_read_skill_definition(self):
        result = classify_tool("Read", {"file_path": "/app/skills/matomo_query/skill.md"})
        assert result == "Read: skill definition"

    def test_read_skill_code(self):
        result = classify_tool("Read", {"file_path": "/app/skills/matomo_query/scripts/matomo.py"})
        assert result == "Read: skill code"

    def test_read_code(self):
        result = classify_tool("Read", {"file_path": "/app/web/routes/conversations.py"})
        assert result == "Read: code"

    def test_read_docs(self):
        result = classify_tool("Read", {"file_path": "/app/AGENTS.md"})
        assert result == "Read: docs"

    def test_read_temp(self):
        result = classify_tool("Read", {"file_path": "/tmp/output.txt"})
        assert result == "Read: temp"

    def test_read_other(self):
        result = classify_tool("Read", {"file_path": "/app/config/sources.yaml"})
        assert result == "Read: other"

    # --- Write operations ---

    def test_write_temp(self):
        result = classify_tool("Write", {"file_path": "/tmp/analysis.py"})
        assert result == "Write: temp"

    def test_write_interactive(self):
        result = classify_tool("Write", {"file_path": "/app/data/interactive/dashboard.html"})
        assert result == "Write: interactive"

    def test_write_script(self):
        result = classify_tool("Write", {"file_path": "/app/data/scripts/query.py"})
        assert result == "Write: script"

    def test_write_knowledge(self):
        result = classify_tool("Write", {"file_path": "/app/knowledge/sites/new-site.md"})
        assert result == "Write: knowledge"

    def test_write_other(self):
        result = classify_tool("Write", {"file_path": "/app/config.txt"})
        assert result == "Write: other"

    # --- Edit operations ---

    def test_edit_knowledge(self):
        result = classify_tool("Edit", {"file_path": "/app/knowledge/sites/emplois.md"})
        assert result == "Edit: knowledge"

    def test_edit_skill(self):
        result = classify_tool("Edit", {"file_path": "/app/skills/matomo_query/skill.md"})
        assert result == "Edit: skill"

    def test_edit_code(self):
        result = classify_tool("Edit", {"file_path": "/app/web/app.py"})
        assert result == "Edit: code"

    def test_edit_other(self):
        result = classify_tool("Edit", {"file_path": "/app/config.yaml"})
        assert result == "Edit: other"

    # --- Other tools ---

    def test_skill_invocation(self):
        result = classify_tool("Skill", {"skill": "matomo_query"})
        assert result == "Skill: matomo_query"

    def test_glob(self):
        result = classify_tool("Glob", {"pattern": "**/*.py"})
        assert result == "Search: codebase"

    def test_grep(self):
        result = classify_tool("Grep", {"pattern": "MatomoAPI"})
        assert result == "Search: codebase"

    def test_todowrite(self):
        result = classify_tool("TodoWrite", {"todos": []})
        assert result == "Thinking: todo"

    def test_webfetch(self):
        result = classify_tool("WebFetch", {"url": "https://example.com"})
        assert result == "Web: fetch"

    def test_task(self):
        result = classify_tool("Task", {"prompt": "do something"})
        assert result == "System: task"

    def test_ask_user(self):
        result = classify_tool("AskUserQuestion", {"question": "Which option?"})
        assert result == "Interaction: ask user"

    def test_unknown_tool(self):
        result = classify_tool("UnknownTool", {})
        assert result == "Other: UnknownTool"


class TestIsPublicCategory:
    """Tests for is_public_category function."""

    def test_api_matomo_is_public(self):
        assert is_public_category("API: Matomo") is True

    def test_api_metabase_is_public(self):
        assert is_public_category("API: Metabase") is True

    def test_read_knowledge_is_public(self):
        assert is_public_category("Read: knowledge") is True

    def test_write_interactive_is_public(self):
        assert is_public_category("Write: interactive") is True

    def test_skill_any_is_public(self):
        assert is_public_category("Skill: matomo_query") is True
        assert is_public_category("Skill: save_report") is True
        assert is_public_category("Skill: custom_skill") is True

    def test_shell_explore_is_admin(self):
        assert is_public_category("Shell: explore") is False

    def test_write_temp_is_admin(self):
        assert is_public_category("Write: temp") is False

    def test_thinking_todo_is_admin(self):
        assert is_public_category("Thinking: todo") is False

    def test_execute_script_is_admin(self):
        assert is_public_category("Execute: script") is False


class TestPublicCategoriesSet:
    """Tests for PUBLIC_CATEGORIES constant."""

    def test_contains_api_categories(self):
        assert "API: Matomo" in PUBLIC_CATEGORIES
        assert "API: Metabase" in PUBLIC_CATEGORIES
        assert "API: Matomo + Metabase" in PUBLIC_CATEGORIES

    def test_contains_knowledge_read(self):
        assert "Read: knowledge" in PUBLIC_CATEGORIES
        assert "Read: skill definition" in PUBLIC_CATEGORIES
        assert "Read: docs" in PUBLIC_CATEGORIES

    def test_does_not_contain_shell(self):
        assert "Shell: explore" not in PUBLIC_CATEGORIES
        assert "Shell: setup" not in PUBLIC_CATEGORIES
