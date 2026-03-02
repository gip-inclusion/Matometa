# Architecture Audit: Matometa

> **Note (2026-03):** This plan predates the SQLite→PostgreSQL migration. SQLite references describe the architecture at the time of writing.

**Date:** 2026-01-10
**Scope:** Security, maintainability, testability, upgradeability, repo structure

---

## Summary

Matometa is a Flask-based web analytics assistant that uses Claude (via Agent SDK or CLI) to query Matomo and Metabase APIs. It has a knowledge base, reusable skills, and a SQLite-backed conversation system.

---

## 1. Security

### Critical Issues

| Issue | Location | Risk | Recommendation |
|-------|----------|------|----------------|
| **No authentication** | `web/app.py:298` | HIGH | Add authentication. Even basic auth or API keys for web access. Currently anyone with network access can interact with the agent. |
| **SQL injection pattern** | `web/database.py:459-466` | MEDIUM | The `update_conversation` uses f-string SQL building. Although field names are filtered, prefer parameterized queries throughout. |
| **Auto-approve all edits** | `web/agents/sdk.py:57` | HIGH | `permission_mode="acceptEdits"` gives the agent full file/bash access. Consider a whitelist approach or at least audit logging. |
| **API keys in .env** | `.env` | MEDIUM | While gitignored, plaintext secrets on disk. For production: use a secrets manager or environment-only injection. |

### Positive Security Patterns

- `validate_knowledge_path()` has layered defenses (regex + `relative_to()` + extension check)
- Docker container runs as non-root user
- Knowledge/skills mounted read-only in production

### Recommendations

1. **Add authentication layer** - OIDC or at minimum HTTP basic auth
2. **Audit logging** - Log all agent tool invocations with timestamps, user, and parameters
3. **Sandbox the agent** - Instead of `acceptEdits`, implement a review queue for file writes
4. **Rotate credentials** - The API keys in .env appear to be long-lived

---

## 2. Ease of Maintenance

### Issues

| Issue | Impact | Recommendation |
|-------|--------|----------------|
| **Monolithic `app.py`** (1090 lines) | Hard to navigate, test, modify | Split into blueprints: `api/conversations.py`, `api/reports.py`, `api/knowledge.py` |
| **Duplicate agent logic** | CLI and SDK backends share concepts | Extract shared `AgentSession` class for history/session management |
| **Mixed concerns in skills** | `SKILL.md` is docs + instructions | Consider separating agent-facing instructions from human documentation |
| **Hardcoded paths** | Scripts import with `Path(__file__).parent.parent...` | Use proper Python packaging or a `PYTHONPATH` convention |

### File Organization Debt

```
Current:
skills/
  matomo_query/
    SKILL.md          # Agent instructions
    scripts/
      matomo.py       # Python client
      conftest.py     # Test fixtures in wrong place

Better:
skills/
  matomo_query/
    SKILL.md
src/
  matometa/
    clients/
      matomo.py
      metabase.py
tests/
  conftest.py
  clients/
    test_matomo.py
```

### Recommendations

1. **Split Flask app into blueprints** - 3 separate files for API routes
2. **Create a `matometa` Python package** - Proper imports, installable with pip
3. **Move test fixtures to tests/conftest.py** - Currently scattered

---

## 3. Correctness & Testability

### Current State

- Tests exist for Matomo/Metabase clients (`tests/test_matomo.py`, etc.)
- Tests hit **live APIs** - no mocking
- No tests for web routes, database operations, or agent backends
- Database tests would require resetting state between runs

### Missing Test Coverage

| Component | Current | Needed |
|-----------|---------|--------|
| Matomo client | Yes (live) | Add mocked tests |
| Metabase client | Yes (live) | Add mocked tests |
| Web routes | No | Add Flask test client tests |
| Database CRUD | No | Add with in-memory SQLite |
| Agent backends | No | Add with mock Claude responses |
| Path validation | No | Add security-focused tests |

### Recommendations

1. **Add pytest-vcr or responses** - Record/replay HTTP interactions instead of live calls
2. **Use in-memory SQLite for tests** - `sqlite:///:memory:`
3. **Add property-based tests** for `validate_knowledge_path()` - Hypothesis can find edge cases
4. **Test the SSE streaming** - Flask test client supports streaming responses
5. **Add type checking** - `mypy` would catch issues like the `check_same_thread=False` concern

---

## 4. Upgradeability

### Version Pinning Issues

| Item | Current | Risk |
|------|---------|------|
| Claude model | Hardcoded `claude-sonnet-4-20250514` | Will need manual updates |
| Python version | 3.11 in Docker, but .pyc files are 3.14 | Version mismatch in dev/prod |
| SDK imports | Direct `from claude_agent_sdk import ...` | SDK API may change |
| Database schema | Manual migrations in code | No rollback, no version history |

### Recommendations

1. **Extract model versions to config** - `MODEL_TITLE_GENERATION = os.getenv("...")`
2. **Lock Python versions** - Use `.python-version` file, ensure dev matches prod
3. **Wrap SDK in adapter** - Isolate SDK-specific code so upgrades are localized
4. **Use Alembic for migrations** - Proper version history and rollback

---

## 5. On Splitting Repositories

### Current Coupling

```
knowledge/ <-- referenced by --> skills/
    ^                               |
    +-------- imported by ----------+
                                    |
                            web/agents/sdk.py
```

Skills import from knowledge paths. The web app loads `AGENTS.md` as system prompt. Everything is tightly coupled.

### Evaluation

| Factor | For Splitting | Against Splitting |
|--------|---------------|-------------------|
| **Deployment independence** | Knowledge updates without web rebuild | Atomic deploys become complex |
| **Clear boundaries** | Forces explicit APIs | Current simplicity is a feature |
| **Team scale** | Not needed for solo/small team | Adds coordination overhead |
| **Testing** | Easier to test components in isolation | Integration testing across repos is harder |

### Recommendation: Don't split now

The project is small enough that monorepo advantages outweigh multi-repo overhead. Instead:

1. **Internal structure** - Organize as if they were separate packages:
   ```
   packages/
     knowledge/      # Pure markdown, no code
     core/           # Python clients, shared code
     web/            # Flask app only
     skills/         # SKILL.md files only (scripts move to core/)
   ```

2. **If splitting becomes necessary** (e.g., knowledge needs to be shared with other projects):
   - Extract `knowledge/` as a git submodule or separate repo
   - Keep `skills/` + `web/` together (skills are UI-specific)
   - The web app would fetch knowledge at build/deploy time

3. **Consider splitting only when**:
   - Multiple teams work on different parts
   - Knowledge is consumed by other systems
   - Deployment cadence differs significantly

---

## Priority Recommendations

| Priority | Action | Effort |
|----------|--------|--------|
| **HIGH** | Add authentication (OAuth/OIDC via Caddy) | Low |
| **HIGH** | Audit logging for agent actions | Medium |
| **MEDIUM** | Split app.py into blueprints | Medium |
| **MEDIUM** | Add mocked tests | Medium |
| **LOW** | Consider internal package structure | High |
| **LOW** | Don't split repos yet | N/A |

---

## Next Steps

1. Set up OAuth on Caddy for authentication
2. Add request logging middleware
3. Gradually refactor app.py as features are added
