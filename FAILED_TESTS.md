# Failed Tests — 2025-02-25

Full suite: **513 passed, 10 failed, 17 skipped, 20 errors**

All failures are pre-existing and unrelated to the expert-mode changes (plan lifecycle, project_key, DB provisioning, git attribution). They fall into 5 categories requiring external services or local data.

---

## 1. Gitea Client — Connection refused (6 tests)

**Root cause:** Gitea is not running locally. Tests try to connect to `host.docker.internal:3300`.

| Test | Type |
|------|------|
| `test_gitea.py::TestGiteaClient::test_version` | FAILED |
| `test_gitea.py::TestGiteaClient::test_create_repo` | FAILED |
| `test_gitea.py::TestGiteaClient::test_get_repo` | ERROR |
| `test_gitea.py::TestGiteaClient::test_push_files` | ERROR |
| `test_gitea.py::TestGiteaClient::test_create_branch` | ERROR |
| `test_gitea.py::TestGiteaClient::test_create_pull_request` | ERROR |

**Error:** `requests.exceptions.ConnectionError: Failed to resolve 'host.docker.internal'`

**Action required:**
- Start Docker Compose stack (`docker compose -f docker-compose.local.yml up`) before running these tests
- Or mark them `@pytest.mark.integration` so they're skipped by default

---

## 2. Metabase Client — Missing API keys (15 tests)

**Root cause:** `METABASE_STATS_API_KEY` (and other Metabase env vars) not set in `.env`.

| Test file | Tests affected | Type |
|-----------|---------------|------|
| `test_metabase_client.py::TestConnection` | 1 | ERROR |
| `test_metabase_client.py::TestExecuteSQL` | 5 | ERROR |
| `test_metabase_client.py::TestExecuteCard` | 2 | ERROR |
| `test_metabase_client.py::TestGetCard` | 2 | ERROR |
| `test_metabase_client.py::TestListCards` | 1 | ERROR |
| `test_metabase_client.py::TestSearchCards` | 2 | ERROR |
| `test_metabase_client.py::TestGetCardSQL` | 1 | ERROR |
| `test_metabase_client.py::TestDashboards` | 2 | ERROR |

**Error:** `ValueError` at setup — missing API key env vars

**Action required:**
- Add Metabase API keys to `.env`
- Or mark these tests `@pytest.mark.integration`

---

## 3. Metabase Cards DB — Missing SQLite file (3 tests)

**Root cause:** `knowledge/metabase/cards.db` doesn't exist. Needs to be populated by the sync script.

| Test | Type |
|------|------|
| `test_metabase_answers.py::TestCardDiscovery::test_search_file_active` | FAILED |
| `test_metabase_answers.py::TestCardDiscovery::test_search_candidatures` | FAILED |
| `test_metabase_answers.py::TestCardDiscovery::test_search_by_table` | FAILED |

**Error:** `FileNotFoundError: Cards database not found at knowledge/metabase/cards.db`

**Action required:**
```bash
python -m skills.sync_metabase.scripts.sync_inventory --instance stats
```

---

## 4. Notion — Missing token (3 tests)

**Root cause:** `NOTION_TOKEN` and `NOTION_REPORTS_DB` env vars not configured.

| Test | Type |
|------|------|
| `test_notion.py::TestFrontmatterExtraction::test_frontmatter_query_overrides_db_field` | FAILED |
| `test_notion.py::TestFrontmatterExtraction::test_frontmatter_date_overrides_argument` | FAILED |
| `test_notion.py::TestFrontmatterExtraction::test_db_field_used_when_no_frontmatter` | FAILED |

**Error:** `RuntimeError: Notion not configured (NOTION_TOKEN / NOTION_REPORTS_DB)`

**Action required:**
- Add `NOTION_TOKEN` and `NOTION_REPORTS_DB` to `.env`
- Or refactor tests to mock the Notion client

---

## 5. Query Integration — Missing API keys (2 tests)

**Root cause:** Matomo/Metabase API keys not available.

| Test | Type |
|------|------|
| `test_query.py::TestQueryIntegration::test_metabase_query_executes` | FAILED |
| `test_query.py::TestQueryIntegration::test_matomo_query_executes` | FAILED |

**Error:** `METABASE_STATS_API_KEY not set` / `MATOMO_API_KEY not set`

**Action required:**
- Add API keys to `.env`
- These are already marked `@pytest.mark.integration` — run with `pytest -m integration`

---

## Quick fix summary

| Category | # Tests | Fix |
|----------|---------|-----|
| Gitea connection | 6 | Start Docker stack or add `@pytest.mark.integration` |
| Metabase API keys | 15 | Add keys to `.env` or mark integration |
| Cards DB missing | 3 | Run `sync_inventory` script |
| Notion token | 3 | Add token to `.env` or mock |
| Query API keys | 2 | Add keys to `.env` (already marked integration) |
| **Total** | **30** | |

To run only non-integration tests cleanly:
```bash
.venv/bin/pytest -m "not integration" --ignore=tests/test_gitea.py --ignore=tests/test_metabase_client.py
```
