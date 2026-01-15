"""
Test suite comparing model performance finding Metabase cards
using markdown documentation vs SQLite database.

Usage:
    python -m tests.test_card_retrieval

This spawns sub-agents with restricted tool access to evaluate
which approach (markdown vs sqlite) performs better for card retrieval.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Test cases: questions with expected card IDs
# IDs are from the original public dashboards on pilotage.inclusion.beta.gouv.fr
TEST_CASES = [
    {
        "id": "file_active_count",
        "question": "Find the card that counts candidates in the file active (waiting 30+ days with no accepted candidature)",
        "expected_card_ids": [4413],  # [408] Nombre de candidats en recherche active...
        "expected_keywords": ["file active", "30 jours", "candidat"],
        "difficulty": "easy",
    },
    {
        "id": "file_active_by_region",
        "question": "Find the card that shows file active candidates broken down by region",
        "expected_card_ids": [4805],  # [408] Répartition candidats dans la file active par région
        "expected_keywords": ["région", "file active"],
        "difficulty": "easy",
    },
    {
        "id": "refusal_reasons_by_siae",
        "question": "Find the card showing refusal reasons (motifs de refus) by SIAE type",
        "expected_card_ids": [4293],  # [408] répartition des motifs de refus par type de SIAE
        "expected_keywords": ["motif", "refus", "SIAE"],
        "difficulty": "medium",
    },
    {
        "id": "women_representation",
        "question": "Find cards related to women representation in IAE candidatures (dashboard 216)",
        "expected_card_ids": [2257, 4691, 4709, 4743, 4745],  # Dashboard 216 cards about women/gender
        "expected_keywords": ["femme", "genre"],
        "difficulty": "medium",
    },
    {
        "id": "prolongation_requests",
        "question": "Find the card counting total prolongation requests (demandes de prolongation)",
        "expected_card_ids": [2681],  # [336] Nombre de demandes de prolongation
        "expected_keywords": ["prolongation", "demande"],
        "difficulty": "medium",
    },
    {
        "id": "auto_prescription_rate",
        "question": "Find cards about auto-prescription rates by SIAE type",
        "expected_card_ids": [3874],  # Evolution du taux d'auto-prescription par type de SIAE
        "expected_keywords": ["auto-prescription", "taux", "type"],
        "difficulty": "hard",
    },
    {
        "id": "postes_tension",
        "question": "Find cards counting job positions that are hard to fill (postes en tension)",
        "expected_card_ids": [3678],  # [408] Nombre de fiches de poste en tension
        "expected_keywords": ["tension", "poste", "fiche"],
        "difficulty": "medium",
    },
    {
        "id": "esat_specific",
        "question": "Find cards specific to ESAT structures",
        "expected_card_ids": [],  # Many valid answers - check topic instead
        "expected_keywords": ["ESAT", "esat"],
        "difficulty": "easy",
        "check_topic": "esat",
    },
]


@dataclass
class AgentResult:
    """Result from a sub-agent search."""
    test_id: str
    mode: str  # "markdown" or "sqlite"
    found_card_ids: list[int]
    raw_response: str
    duration_seconds: float
    success: bool
    error: Optional[str] = None


def run_markdown_agent(test_case: dict) -> AgentResult:
    """Run agent with access to markdown files only."""
    start = time.time()

    prompt = f"""You have access ONLY to markdown files in knowledge/stats/.
Do NOT use any SQLite database or Python scripts.

Your task: {test_case['question']}

Search the markdown files to find the relevant Metabase card(s).
Return your answer in this exact JSON format:
{{"card_ids": [1234, 5678], "card_names": ["Card name 1", "Card name 2"], "reasoning": "Brief explanation"}}

Use Glob to find files, then Read to examine them. Start with knowledge/stats/_index.md to understand the structure.
"""

    try:
        result = subprocess.run(
            [
                "claude",
                "-p", prompt,
                "--output-format", "text",
                "--max-turns", "10",
                "--allowedTools", "Glob,Read",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=Path(__file__).parent.parent,
        )

        duration = time.time() - start
        response = result.stdout

        # Try to extract card IDs from response
        card_ids = extract_card_ids(response)

        return AgentResult(
            test_id=test_case["id"],
            mode="markdown",
            found_card_ids=card_ids,
            raw_response=response,
            duration_seconds=duration,
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None,
        )
    except subprocess.TimeoutExpired:
        return AgentResult(
            test_id=test_case["id"],
            mode="markdown",
            found_card_ids=[],
            raw_response="",
            duration_seconds=120,
            success=False,
            error="Timeout after 120s",
        )
    except Exception as e:
        return AgentResult(
            test_id=test_case["id"],
            mode="markdown",
            found_card_ids=[],
            raw_response="",
            duration_seconds=time.time() - start,
            success=False,
            error=str(e),
        )


def run_sqlite_agent(test_case: dict) -> AgentResult:
    """Run agent with access to SQLite database only."""
    start = time.time()

    db_path = Path(__file__).parent.parent / "knowledge" / "metabase" / "cards.db"

    prompt = f"""You have access ONLY to the SQLite database at {db_path}.
Do NOT read any markdown files.

Your task: {test_case['question']}

## Database Schema

Tables:
- cards (id, name, description, collection_id, dashboard_id, topic, sql_query, tables_referenced, created_at, updated_at)
- cards_fts (full-text search on: name, description, sql_query)
- dashboards (id, name, description, topic, pilotage_url, collection_id)

## Topics Taxonomy

Cards are categorized by topic:
- file-active: Candidats dans la file active (30+ days waiting)
- postes-tension: Postes en tension (difficult to recruit)
- demographie: Age, gender, geographic breakdowns
- candidatures: Candidature metrics, states, flows
- employeurs: SIAE and employer information
- prescripteurs: Prescripteur and orientation data
- auto-prescription: Auto-prescription metrics
- controles: Control and compliance
- prolongations: PASS extensions
- etp-effectifs: ETP and workforce metrics
- esat: ESAT-specific data
- generalites-iae: General IAE statistics

## Search Strategy

1. Start by identifying the relevant topic(s)
2. Use full-text search (cards_fts) for keyword matching
3. Filter by topic for precision

## Example Queries

- List topics: sqlite3 {db_path} "SELECT topic, COUNT(*) FROM cards GROUP BY topic"
- Full-text search: sqlite3 {db_path} "SELECT id, name FROM cards_fts WHERE cards_fts MATCH 'candidature'"
- By topic: sqlite3 {db_path} "SELECT id, name FROM cards WHERE topic = 'file-active'"
- Combined: sqlite3 {db_path} "SELECT c.id, c.name FROM cards c JOIN cards_fts f ON c.id = f.rowid WHERE f.cards_fts MATCH 'prolongation' AND c.topic = 'prolongations'"

Return your answer in this exact JSON format:
{{"card_ids": [1234, 5678], "card_names": ["Card name 1", "Card name 2"], "reasoning": "Brief explanation"}}
"""

    try:
        result = subprocess.run(
            [
                "claude",
                "-p", prompt,
                "--output-format", "text",
                "--max-turns", "10",
                "--allowedTools", "Bash(sqlite3:*)",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=Path(__file__).parent.parent,
        )

        duration = time.time() - start
        response = result.stdout

        # Try to extract card IDs from response
        card_ids = extract_card_ids(response)

        return AgentResult(
            test_id=test_case["id"],
            mode="sqlite",
            found_card_ids=card_ids,
            raw_response=response,
            duration_seconds=duration,
            success=result.returncode == 0,
            error=result.stderr if result.returncode != 0 else None,
        )
    except subprocess.TimeoutExpired:
        return AgentResult(
            test_id=test_case["id"],
            mode="sqlite",
            found_card_ids=[],
            raw_response="",
            duration_seconds=120,
            success=False,
            error="Timeout after 120s",
        )
    except Exception as e:
        return AgentResult(
            test_id=test_case["id"],
            mode="sqlite",
            found_card_ids=[],
            raw_response="",
            duration_seconds=time.time() - start,
            success=False,
            error=str(e),
        )


def extract_card_ids(response: str) -> list[int]:
    """Extract card IDs from agent response."""
    import re

    # Try to find JSON in response
    json_match = re.search(r'\{[^{}]*"card_ids"\s*:\s*\[[^\]]*\][^{}]*\}', response, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return [int(x) for x in data.get("card_ids", [])]
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback: look for patterns like "ID: 1234" or "card 1234"
    id_patterns = [
        r'\*\*ID:\*\*\s*(\d+)',
        r'ID:\s*(\d+)',
        r'card[_\s]+id[:\s]+(\d+)',
        r'card\s+(\d{4,})',
    ]

    found_ids = set()
    for pattern in id_patterns:
        for match in re.finditer(pattern, response, re.IGNORECASE):
            try:
                card_id = int(match.group(1))
                if 1000 <= card_id <= 99999:  # Reasonable card ID range
                    found_ids.add(card_id)
            except ValueError:
                pass

    return list(found_ids)


def evaluate_result(result: AgentResult, test_case: dict) -> dict:
    """Evaluate how well the agent performed."""
    expected_ids = set(test_case["expected_card_ids"])
    found_ids = set(result.found_card_ids)

    # Calculate metrics
    if expected_ids:
        true_positives = len(found_ids & expected_ids)
        precision = true_positives / len(found_ids) if found_ids else 0
        recall = true_positives / len(expected_ids)
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    else:
        # For tests without specific expected IDs, check if any cards found
        precision = 1.0 if found_ids else 0
        recall = 1.0 if found_ids else 0
        f1 = 1.0 if found_ids else 0

    # Check if keywords appear in response
    keyword_hits = sum(
        1 for kw in test_case.get("expected_keywords", [])
        if kw.lower() in result.raw_response.lower()
    )
    keyword_coverage = keyword_hits / len(test_case.get("expected_keywords", [1])) if test_case.get("expected_keywords") else 1

    return {
        "test_id": result.test_id,
        "mode": result.mode,
        "success": result.success,
        "duration_seconds": result.duration_seconds,
        "found_card_ids": result.found_card_ids,
        "expected_card_ids": list(expected_ids),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "keyword_coverage": keyword_coverage,
        "correct": f1 >= 0.5,  # Consider correct if F1 >= 0.5
        "error": result.error,
    }


def run_test_suite(test_cases: list[dict] = None, modes: list[str] = None):
    """Run the full test suite."""
    if test_cases is None:
        test_cases = TEST_CASES
    if modes is None:
        modes = ["markdown", "sqlite"]

    results = []

    print("=" * 70)
    print("METABASE CARD RETRIEVAL TEST SUITE")
    print("=" * 70)
    print(f"Test cases: {len(test_cases)}")
    print(f"Modes: {', '.join(modes)}")
    print()

    for i, test_case in enumerate(test_cases):
        print(f"\n[{i+1}/{len(test_cases)}] Test: {test_case['id']}")
        print(f"    Question: {test_case['question'][:60]}...")
        print(f"    Difficulty: {test_case['difficulty']}")

        for mode in modes:
            print(f"\n    Running {mode} agent...", end=" ", flush=True)

            if mode == "markdown":
                result = run_markdown_agent(test_case)
            else:
                result = run_sqlite_agent(test_case)

            evaluation = evaluate_result(result, test_case)
            results.append(evaluation)

            status = "✅" if evaluation["correct"] else "❌"
            print(f"{status} ({result.duration_seconds:.1f}s)")
            print(f"        Found: {result.found_card_ids[:5]}{'...' if len(result.found_card_ids) > 5 else ''}")
            print(f"        F1: {evaluation['f1']:.2f}, Keywords: {evaluation['keyword_coverage']:.0%}")
            if result.error:
                print(f"        Error: {result.error[:50]}...")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for mode in modes:
        mode_results = [r for r in results if r["mode"] == mode]
        correct = sum(1 for r in mode_results if r["correct"])
        avg_f1 = sum(r["f1"] for r in mode_results) / len(mode_results) if mode_results else 0
        avg_duration = sum(r["duration_seconds"] for r in mode_results) / len(mode_results) if mode_results else 0

        print(f"\n{mode.upper()}:")
        print(f"  Accuracy: {correct}/{len(mode_results)} ({100*correct/len(mode_results):.0f}%)")
        print(f"  Avg F1: {avg_f1:.2f}")
        print(f"  Avg Duration: {avg_duration:.1f}s")

    # Save results
    output_path = Path(__file__).parent / "card_retrieval_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test card retrieval performance")
    parser.add_argument("--mode", choices=["markdown", "sqlite", "both"], default="both",
                        help="Which mode(s) to test")
    parser.add_argument("--test", type=str, help="Run specific test by ID")
    parser.add_argument("--quick", action="store_true", help="Run only easy tests")
    args = parser.parse_args()

    # Filter test cases
    test_cases = TEST_CASES
    if args.test:
        test_cases = [t for t in TEST_CASES if t["id"] == args.test]
    elif args.quick:
        test_cases = [t for t in TEST_CASES if t["difficulty"] == "easy"]

    # Determine modes
    modes = ["markdown", "sqlite"] if args.mode == "both" else [args.mode]

    run_test_suite(test_cases, modes)
