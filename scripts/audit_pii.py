"""
PII column audit for Metabase instances.

Connects to each configured Metabase instance, fetches table/column metadata,
and interactively asks the operator to classify columns as PII or safe.

Decisions are persisted in config/pii_reviewed.yaml using hashed keys
(sha256 of "instance:table.column") so the file doesn't leak Metabase schema.

On subsequent runs, only unreviewed columns are shown (incremental audit).

Usage:
    python scripts/audit_pii.py                  # interactive review of new columns
    python scripts/audit_pii.py --dry-run        # show unreviewed columns without prompting
    python scripts/audit_pii.py --stats          # show review coverage stats
    python scripts/audit_pii.py --apply          # update lib/_pii_guard.py with current PII rules
    python scripts/audit_pii.py --instance stats # audit a single instance

Requires Metabase API keys in .env (METABASE_STATS_API_KEY, etc.)
"""

import hashlib
import re
import sys
from pathlib import Path

import yaml

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from lib._sources import get_metabase, list_instances

# --- Config ---

REVIEW_FILE = ROOT / "config" / "pii_reviewed.yaml"
PII_GUARD_FILE = ROOT / "lib" / "_pii_guard.py"

# Patterns that suggest a column might contain PII.
# Used to prioritize which columns to show first during review.
PII_PATTERNS = [
    r"e[-_]?mail",
    r"first[-_]?name",
    r"last[-_]?name",
    r"\bnom\b",
    r"\bprenom\b",
    r"pr[eé]nom",
    r"\bnir\b",
    r"hash[-_]?nir",
    r"nss",
    r"phone",
    r"t[eé]l[eé]phone",
    r"\btel\b",
    r"mobile",
    r"adress?e",
    r"address",
    r"code[-_]?postal",
    r"\biban\b",
    r"password",
    r"\btoken\b",
    r"sexe",
    r"naissance",
    r"birth",
    r"organizer",
]


# --- Hashing ---

def hash_key(instance: str, table: str, column: str) -> str:
    """Hash a column identifier so the review file doesn't leak schema."""
    raw = f"{instance}:{table}.{column}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# --- Review file ---

def load_review() -> dict:
    """Load the review file. Returns {"pii": dict, "safe": dict}."""
    if not REVIEW_FILE.exists():
        return {"pii": {}, "safe": {}}

    with open(REVIEW_FILE) as f:
        data = yaml.safe_load(f) or {}

    return {
        "pii": {
            h: info for h, info in (data.get("pii") or {}).items()
        },
        "safe": {
            h: info for h, info in (data.get("safe") or {}).items()
        },
    }


def save_review(review: dict):
    """Save the review file."""
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "pii": review["pii"],
        "safe": review["safe"],
    }

    with open(REVIEW_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=True)


# --- Metabase metadata ---

def fetch_columns(instance_name: str) -> list[dict]:
    """Fetch all table/column metadata from a Metabase instance."""
    api = get_metabase(instance_name)
    columns = []

    # Get all databases visible to this API key
    databases = api._request("GET", "/api/database")
    db_list = databases if isinstance(databases, list) else databases.get("data", [])

    for db in db_list:
        db_id = db["id"]
        db_name = db.get("name", f"db_{db_id}")

        try:
            metadata = api._request(
                "GET",
                f"/api/database/{db_id}/metadata?include_hidden=true",
                query_type="metadata",
            )
        except Exception as e:
            print(f"  Warning: could not fetch metadata for {db_name}: {e}")
            continue

        tables = metadata.get("tables", [])
        for table in tables:
            table_name = table.get("name", "")
            # Skip Metabase internal tables
            if table_name.startswith("metabase_") or table.get("schema") == "information_schema":
                continue

            for col in table.get("fields", []):
                col_name = col.get("name", "")
                col_type = col.get("semantic_type") or col.get("base_type", "")
                columns.append({
                    "instance": instance_name,
                    "database": db_name,
                    "table": table_name,
                    "column": col_name,
                    "type": col_type,
                    "hash": hash_key(instance_name, table_name, col_name),
                })

    return columns


def matches_pii_pattern(column_name: str) -> bool:
    """Check if a column name matches known PII patterns."""
    lower = column_name.lower()
    return any(re.search(p, lower) for p in PII_PATTERNS)


# --- Update _pii_guard.py ---

def read_current_pii_rules() -> dict[str, set[str]]:
    """Read current PII_RULES from _pii_guard.py."""
    content = PII_GUARD_FILE.read_text()
    # Match the PII_RULES dict block
    match = re.search(
        r"PII_RULES:\s*dict\[str,\s*set\[str\]\]\s*=\s*\{(.+?)^\}",
        content,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        return {}

    block = match.group(1)
    rules: dict[str, set[str]] = {}

    # Parse each "table": {"col1", "col2", ...} entry
    for table_match in re.finditer(r'"([^"]+)":\s*\{([^}]+)\}', block):
        table = table_match.group(1)
        cols = set(re.findall(r'"([^"]+)"', table_match.group(2)))
        rules[table] = cols

    return rules


def update_pii_guard(new_rules: dict[str, set[str]]):
    """Update PII_RULES in _pii_guard.py."""
    content = PII_GUARD_FILE.read_text()

    # Build new PII_RULES block
    lines = ["PII_RULES: dict[str, set[str]] = {"]
    for table in sorted(new_rules.keys()):
        cols = sorted(new_rules[table])
        if len(cols) <= 3:
            col_str = ", ".join(f'"{c}"' for c in cols)
            lines.append(f'    "{table}": {{{col_str}}},')
        else:
            lines.append(f'    "{table}": {{')
            for col in cols:
                lines.append(f'        "{col}",')
            lines.append("    },")
    lines.append("}")
    new_block = "\n".join(lines)

    # Replace existing block
    updated = re.sub(
        r"PII_RULES:\s*dict\[str,\s*set\[str\]\]\s*=\s*\{.+?^\}",
        new_block,
        content,
        flags=re.DOTALL | re.MULTILINE,
    )

    PII_GUARD_FILE.write_text(updated)


def build_rules_from_review(review: dict) -> dict[str, set[str]]:
    """Build PII_RULES dict from review decisions."""
    rules: dict[str, set[str]] = {}
    for info in review["pii"].values():
        table = info.get("table", "")
        column = info.get("column", "")
        if table and column:
            rules.setdefault(table, set()).add(column)
    return rules


# --- Interactive review ---

def review_column(col: dict) -> str | None:
    """Ask the operator about a single column. Returns 'pii', 'safe', or None (skip)."""
    is_suspect = matches_pii_pattern(col["column"])
    marker = " [!]" if is_suspect else ""

    print(f"\n  [{col['instance']}] {col['database']}.{col['table']}")
    print(f"    column: {col['column']}{marker}  (type: {col['type']})")

    while True:
        try:
            answer = input("    PII? [y/n/s(kip)/q(uit)] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit"

        if answer in ("y", "yes"):
            return "pii"
        elif answer in ("n", "no"):
            return "safe"
        elif answer in ("s", "skip", ""):
            return None
        elif answer in ("q", "quit"):
            return "quit"
        else:
            print("    Enter y (PII), n (safe), s (skip), or q (quit)")


# --- Main ---

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Audit Metabase columns for PII")
    parser.add_argument("--dry-run", action="store_true", help="Show unreviewed columns without prompting")
    parser.add_argument("--stats", action="store_true", help="Show review coverage stats")
    parser.add_argument("--apply", action="store_true", help="Update lib/_pii_guard.py with reviewed PII rules")
    parser.add_argument("--instance", help="Audit a single instance (e.g. stats, datalake)")
    args = parser.parse_args()

    review = load_review()
    reviewed_hashes = set(review["pii"].keys()) | set(review["safe"].keys())

    # Determine which instances to audit
    instances = [args.instance] if args.instance else list_instances("metabase")

    if args.stats:
        print(f"Review file: {REVIEW_FILE}")
        print(f"PII entries: {len(review['pii'])}")
        print(f"Safe entries: {len(review['safe'])}")
        print(f"Total reviewed: {len(reviewed_hashes)}")

        current_rules = read_current_pii_rules()
        review_rules = build_rules_from_review(review)

        if review_rules == current_rules:
            print("\n_pii_guard.py is in sync with reviewed PII rules.")
        else:
            print("\n_pii_guard.py is NOT in sync. Run with --apply to update.")
            for table in sorted(set(review_rules.keys()) | set(current_rules.keys())):
                review_cols = review_rules.get(table, set())
                current_cols = current_rules.get(table, set())
                added = review_cols - current_cols
                removed = current_cols - review_cols
                if added:
                    print(f"  {table}: +{', '.join(sorted(added))}")
                if removed:
                    print(f"  {table}: -{', '.join(sorted(removed))}")
        return

    if args.apply:
        review_rules = build_rules_from_review(review)
        current_rules = read_current_pii_rules()
        if review_rules == current_rules:
            print("_pii_guard.py already in sync. Nothing to update.")
        else:
            update_pii_guard(review_rules)
            print(f"Updated PII_RULES in {PII_GUARD_FILE}")
            for table in sorted(set(review_rules.keys()) | set(current_rules.keys())):
                review_cols = review_rules.get(table, set())
                current_cols = current_rules.get(table, set())
                added = review_cols - current_cols
                removed = current_cols - review_cols
                if added:
                    print(f"  {table}: +{', '.join(sorted(added))}")
                if removed:
                    print(f"  {table}: -{', '.join(sorted(removed))}")
        return

    # Fetch metadata from all instances
    all_columns = []
    for inst in instances:
        print(f"Connecting to {inst}...", end=" ", flush=True)
        try:
            cols = fetch_columns(inst)
            unreviewed = [c for c in cols if c["hash"] not in reviewed_hashes]
            print(f"{len(cols)} columns, {len(unreviewed)} unreviewed")
            all_columns.extend(cols)
        except Exception as e:
            print(f"error: {e}")

    unreviewed = [c for c in all_columns if c["hash"] not in reviewed_hashes]

    if not unreviewed:
        print("\nAll columns reviewed. Nothing new to audit.")
        return

    # Sort: PII-pattern matches first, then alphabetical
    unreviewed.sort(key=lambda c: (not matches_pii_pattern(c["column"]), c["instance"], c["table"], c["column"]))

    suspects = sum(1 for c in unreviewed if matches_pii_pattern(c["column"]))
    print(f"\n{len(unreviewed)} columns to review ({suspects} match PII patterns [!])")

    if args.dry_run:
        for col in unreviewed:
            marker = " [!]" if matches_pii_pattern(col["column"]) else ""
            print(f"  [{col['instance']}] {col['table']}.{col['column']}{marker}")
        return

    # Interactive review
    reviewed_count = 0
    new_pii = 0

    for col in unreviewed:
        decision = review_column(col)

        if decision == "quit":
            break
        elif decision == "pii":
            review["pii"][col["hash"]] = {"table": col["table"], "column": col["column"]}
            reviewed_count += 1
            new_pii += 1
        elif decision == "safe":
            review["safe"][col["hash"]] = {"table": col["table"], "column": col["column"]}
            reviewed_count += 1

    # Save
    if reviewed_count > 0:
        save_review(review)
        total = len(review["pii"]) + len(review["safe"])
        print(f"\nSaved {reviewed_count} decisions ({total} total reviewed)")

        if new_pii > 0:
            print("Run with --apply to update lib/_pii_guard.py")
    else:
        print("\nNo decisions made.")


if __name__ == "__main__":
    main()
