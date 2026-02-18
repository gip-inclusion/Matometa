# Data Protection — Defense in Depth

Matometa queries external databases (Metabase, Matomo) that contain personal data.
This document describes the measures in place and planned to prevent PII extraction.

## Threat model

An authenticated Matometa user can ask the agent to run SQL queries on Metabase
instances. These instances contain tables with personal data (emails, names, hashed
NIR, phone numbers). Without guards, the agent would execute any SQL and return
results containing PII.

Attack vectors:
- **Agent prompt**: user asks "export all emails from webinar attendees"
- **Direct API**: POST to `/api/query` with raw SQL (used by interactive apps)
- **Knowledge base**: SQL templates in `knowledge/` reference PII columns directly

## PII columns and tables

The authoritative list of guarded columns per table is `PII_RULES` in
`lib/_pii_guard.py`. Use `scripts/audit_pii.py` to audit Metabase instance
metadata and keep this list up to date.

Instances containing PII:

- **Stats** (`stats.inclusion.beta.gouv.fr`) — `utilisateurs`, `candidatures_candidats_recherche_active`, `candidats_recherche_active`
- **Datalake** (`datalake.inclusion.beta.gouv.fr`) — `pdi_base_unique_tous_les_pros`, `matometa_webinaire_inscriptions`
- **Dora** (`metabase.dora.inclusion.gouv.fr`) — not audited yet

## Defense layers

### Layer 1: SQL guard (implemented)

**File:** `lib/_pii_guard.py`

A regex-based tripwire in `execute_metabase_query()` that blocks SQL queries
selecting PII columns outside of aggregate functions.

- Checks the SELECT clause for column names defined in `PII_RULES` (`lib/_pii_guard.py`)
- Only checks columns relevant to the tables referenced in the query
- Blocks `SELECT *` when the query references any table in `PII_RULES`
- Allows aggregate usage: `COUNT(DISTINCT email)` passes
- Blocked queries are logged to `audit.db` with `pii_blocked: true`

**Limitations:**
- Regex-based, not a SQL parser — can be bypassed with aliases, CTEs, subqueries
- Cannot detect PII in `SELECT *` on unknown tables
- Column list must be maintained (use `scripts/audit_pii.py` to audit and sync)

**This is a tripwire, not a security boundary.**

### Layer 2: Agent prompt guardrail (implemented)

**File:** `AGENTS.md`, section "Data Protection"

Explicit instructions forbidding PII extraction, with examples of allowed vs
forbidden queries. The agent is instructed to refuse and cite RGPD.

**Limitations:**
- LLM-dependent — a determined user can bypass with prompt injection
- Only applies to the agent, not to `/api/query` direct calls

### Layer 3: Read-only Metabase API keys (in place)

The API keys used by Matometa are read-only. No risk of data modification or
deletion via Metabase.

**Limitation:** Read-only still means full read access to all tables the key
can see. The key is not scoped to specific tables.

**Recommended improvement:** Create a dedicated Metabase user per instance with
access restricted to non-PII tables or anonymized views. Use that user's API key
instead of an admin key.

### Layer 4: Anonymized views (planned, post-PoC)

Create database views that expose only aggregate or anonymized data:

```sql
-- Example: webinaire attendance without PII
CREATE VIEW matometa_inscriptions_anon AS
SELECT webinar_id, organisation, attended, attendance_rate,
       registered_at, source
FROM matometa_webinaire_inscriptions;

-- Example: user counts without identity
CREATE VIEW utilisateurs_stats AS
SELECT type, COUNT(*) as count, date_trunc('month', created_at) as month
FROM utilisateurs
GROUP BY type, date_trunc('month', created_at);
```

Then restrict the Matometa API key to only access these views (via Layer 3).

**Status:** Will be implemented when Matometa moves out of PoC phase.

## Auditing PII columns

**Script:** `scripts/audit_pii.py`

An interactive audit tool that connects to each Metabase instance, fetches
table/column metadata, and asks the operator to classify unreviewed columns
as PII or safe.

```bash
python scripts/audit_pii.py              # interactive review of new columns
python scripts/audit_pii.py --dry-run    # show unreviewed columns without prompting
python scripts/audit_pii.py --stats      # show review coverage stats
python scripts/audit_pii.py --apply      # update lib/_pii_guard.py with current PII rules
```

Decisions are persisted in `config/pii_reviewed.yaml` using hashed keys
(`sha256` of `"instance:table.column"`) so the file doesn't leak Metabase schema.
On subsequent runs, only new columns are shown.

Requires Metabase API keys in `.env`.

## Adding new PII columns manually

When new tables or columns containing personal data are discovered outside the
audit script:

1. Add the table and its PII columns to `PII_RULES` in `lib/_pii_guard.py`
2. Update the instance list in this document if needed
