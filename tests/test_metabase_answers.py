"""
Answer verification tests for Metabase queries.

This test suite validates that given natural language questions,
the system can find correct answers using Metabase cards.

The tests use known-answer cases where we've verified the expected
result range by running the queries manually.

Run with: pytest tests/test_metabase_answers.py -v

To add new test cases:
1. Run the relevant card/query manually to get the current value
2. Define an appropriate range that accounts for data changes
3. Add to KNOWN_ANSWERS below
"""

import os
from dataclasses import dataclass
from typing import Optional, Union
import pytest

from lib.query import get_metabase
from skills.metabase_query.scripts.cards_db import load_cards_db

# Check if we have credentials for integration tests
_HAS_CREDENTIALS = bool(os.environ.get("METABASE_STATS_API_KEY"))
requires_credentials = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Integration test requires METABASE_STATS_API_KEY"
)


@dataclass
class ExpectedAnswer:
    """A known-answer test case."""

    question: str
    """Natural language question (for documentation)."""

    card_id: int
    """The card ID that answers this question."""

    expected_range: Optional[tuple[int, int]] = None
    """Expected numeric range (min, max) for the answer."""

    expected_contains: Optional[list[str]] = None
    """Expected strings that should appear in the result."""

    column_index: int = 0
    """Which column contains the answer (for multi-column results)."""

    row_index: int = 0
    """Which row contains the answer (for multi-row results)."""

    description: str = ""
    """Human-readable description of what this tests."""


# Known-answer test cases
# These are verified by running the queries and checking the results
# Ranges should be wide enough to account for normal data changes
KNOWN_ANSWERS = [
    # File active candidates
    ExpectedAnswer(
        question="Combien de candidats sont dans la file active ?",
        card_id=4413,
        expected_range=(50000, 150000),
        description="File active count - candidates waiting 30+ days without acceptance",
    ),
    # Add more test cases as you validate them:
    #
    # ExpectedAnswer(
    #     question="Combien de postes en tension sont ouverts ?",
    #     card_id=3678,
    #     expected_range=(2000, 5000),
    #     description="Open positions in tension",
    # ),
    #
    # ExpectedAnswer(
    #     question="Quelle est la répartition par genre dans la file active ?",
    #     card_id=4803,
    #     expected_contains=["Femme", "Homme"],
    #     description="Gender distribution in file active",
    # ),
]


@pytest.fixture(scope="module")
def api():
    """Create API client for all tests."""
    return get_metabase(instance="stats")


@requires_credentials
class TestKnownAnswers:
    """Test that cards return expected results."""

    @pytest.mark.parametrize(
        "case",
        KNOWN_ANSWERS,
        ids=[f"{c.card_id}_{c.question[:30]}" for c in KNOWN_ANSWERS],
    )
    def test_known_answer(self, api, case: ExpectedAnswer):
        """Verify card returns expected answer."""
        result = api.execute_card(case.card_id)

        assert result.row_count > 0, f"Card {case.card_id} returned no rows"

        if case.expected_range:
            # Get the numeric value
            value = result.rows[case.row_index][case.column_index]
            assert isinstance(value, (int, float)), (
                f"Expected numeric value, got {type(value)}: {value}"
            )
            min_val, max_val = case.expected_range
            assert min_val <= value <= max_val, (
                f"Value {value} outside expected range [{min_val}, {max_val}] "
                f"for question: {case.question}"
            )

        if case.expected_contains:
            # Check that expected strings appear somewhere in results
            all_text = str(result.rows)
            for expected in case.expected_contains:
                assert expected in all_text, (
                    f"Expected '{expected}' not found in results "
                    f"for question: {case.question}"
                )


class TestCardDiscovery:
    """Test that we can find cards for common questions."""

    def test_search_file_active(self):
        """Can find cards about file active."""
        db = load_cards_db()
        cards = db.search("file active")
        assert len(cards) > 0, "Should find cards about file active"

    def test_search_candidatures(self):
        """Can find cards about candidatures."""
        db = load_cards_db()
        cards = db.search("candidature")
        assert len(cards) > 0, "Should find cards about candidatures"

    def test_search_by_table(self):
        """Can find cards by table name."""
        db = load_cards_db()
        cards = db.by_table("candidatures_echelle_locale")
        assert len(cards) > 0, "Should find cards using this table"


@requires_credentials
class TestEndToEnd:
    """
    End-to-end tests simulating agent workflow.

    These tests verify the full flow:
    1. Search for relevant cards
    2. Execute the card
    3. Verify result makes sense
    """

    def test_find_and_execute_card(self, api):
        """Find a card by search and execute it."""
        db = load_cards_db()

        # Search for a card
        cards = db.search("candidature")
        assert len(cards) > 0

        # Execute the first one
        card = cards[0]
        result = api.execute_card(card.id)

        # Should return some data
        assert result.row_count >= 0
        assert len(result.columns) > 0

    def test_card_sql_is_valid(self, api):
        """Cards with SQL can be used to understand the query."""
        db = load_cards_db()

        # Get any card with SQL from the database
        cards = db.all()
        cards_with_sql = [c for c in cards if c.sql_query]
        assert len(cards_with_sql) > 0, "Should have cards with SQL"

        card = cards_with_sql[0]
        assert card.sql_query, "Card should have SQL"

        # SQL should contain recognizable keywords
        sql_lower = card.sql_query.lower()
        assert any(kw in sql_lower for kw in ["select", "from", "where"]), (
            "SQL should contain basic keywords"
        )
