"""
PII guard for SQL queries.

Best-effort tripwire that detects queries selecting personal data columns.
This is NOT a security boundary — it can be bypassed with creative SQL.
The real boundary is the Metabase API key scope (read-only, scoped tables).

PII_RULES is maintained via `scripts/audit_pii.py` which audits Metabase
instance metadata interactively. Run `audit_pii.py --apply` to sync.

Usage:
    from lib._pii_guard import check_sql_for_pii

    result = check_sql_for_pii("SELECT email FROM utilisateurs")
    if result.blocked:
        print(result.reason)  # "Query selects PII columns: email"
"""

import re
from dataclasses import dataclass, field

# PII rules: table → set of PII columns for that table.
# The guard checks which known tables a query references, then only blocks
# PII columns belonging to those tables. Queries on unknown tables are not blocked.
# Managed by scripts/audit_pii.py --apply.
PII_RULES: dict[str, set[str]] = {
    "utilisateurs": {"email", "nom", "prenom"},
    "pdi_base_unique_tous_les_pros": {"email"},
    "matometa_webinaire_inscriptions": {
        "email", "first_name", "last_name", "organizer_email",
    },
    "candidatures_candidats_recherche_active": {
        "hash_nir", "nir", "sexe_selon_nir",
        "annee_naissance_selon_nir", "mois_naissance_selon_nir",
    },
    "candidats_recherche_active": {
        "hash_nir", "nir", "sexe_selon_nir",
        "annee_naissance_selon_nir", "mois_naissance_selon_nir",
    },
}

# Derived set for internal use.
PII_TABLES = set(PII_RULES.keys())

# Aggregate functions — when a PII column appears ONLY inside one of these,
# the query is allowed (e.g., COUNT(DISTINCT email) is fine).
_AGGREGATE_PATTERN = re.compile(
    r"\b(count|sum|avg|min|max)\s*\(\s*(distinct\s+)?",
    re.IGNORECASE,
)


@dataclass
class PIICheckResult:
    blocked: bool
    reason: str = ""
    matched_columns: list[str] = field(default_factory=list)
    matched_tables: list[str] = field(default_factory=list)


def _find_referenced_pii_tables(normalized: str) -> list[str]:
    """Find which PII tables are referenced anywhere in the query."""
    return [
        table for table in PII_TABLES
        if re.search(rf"\b{re.escape(table)}\b", normalized)
    ]


def check_sql_for_pii(sql: str) -> PIICheckResult:
    """Check a SQL query for PII column/table access.

    Returns PIICheckResult with blocked=True if the query appears to select
    personal data outside of aggregate functions.

    The check is table-aware: only columns defined as PII for the tables
    referenced in the query are checked. Queries on unknown tables pass through.
    """
    normalized = " ".join(sql.lower().split())

    # --- Find which PII tables this query touches ---
    referenced_tables = _find_referenced_pii_tables(normalized)

    if not referenced_tables:
        # Query doesn't reference any known PII table — can't determine risk
        return PIICheckResult(blocked=False)

    # --- Check SELECT * on PII tables ---
    if re.search(r"\bselect\s+\*", normalized):
        return PIICheckResult(
            blocked=True,
            reason=f"SELECT * on PII table(s): {', '.join(referenced_tables)}",
            matched_tables=referenced_tables,
        )

    # --- Build relevant PII columns from referenced tables ---
    relevant_columns: set[str] = set()
    for table in referenced_tables:
        relevant_columns |= PII_RULES[table]

    # --- Check PII columns in SELECT clause ---
    select_match = re.search(r"\bselect\b(.+?)\bfrom\b", normalized, re.DOTALL)
    if not select_match:
        return PIICheckResult(blocked=False)

    select_clause = select_match.group(1)

    matched_columns = []
    for col in relevant_columns:
        pattern = rf"\b{re.escape(col)}\b"
        if not re.search(pattern, select_clause):
            continue

        # Check if EVERY occurrence is inside an aggregate function.
        cleaned = _remove_aggregates(select_clause)
        if re.search(pattern, cleaned):
            matched_columns.append(col)

    if matched_columns:
        return PIICheckResult(
            blocked=True,
            reason=f"Query selects PII columns: {', '.join(sorted(matched_columns))}",
            matched_columns=sorted(matched_columns),
        )

    return PIICheckResult(blocked=False)


def _remove_aggregates(clause: str) -> str:
    """Remove aggregate function calls from a SQL clause.

    Handles nested parentheses: COUNT(DISTINCT email) → removed.
    """
    result = []
    i = 0
    while i < len(clause):
        m = _AGGREGATE_PATTERN.search(clause, i)
        if not m:
            result.append(clause[i:])
            break
        result.append(clause[i : m.start()])
        # Skip past the aggregate and its parenthesized content
        paren_start = clause.find("(", m.start())
        if paren_start == -1:
            break
        depth = 1
        j = paren_start + 1
        while j < len(clause) and depth > 0:
            if clause[j] == "(":
                depth += 1
            elif clause[j] == ")":
                depth -= 1
            j += 1
        i = j
    return "".join(result)
