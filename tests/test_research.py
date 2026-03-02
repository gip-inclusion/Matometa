"""Tests for research corpus: search helpers, formatting, chunking, and refresh logic."""

import hashlib
import json

import psycopg2
import pytest

# ---------------------------------------------------------------------------
# Helpers from scripts/refresh_research.py
# ---------------------------------------------------------------------------
from scripts.refresh_research import (
    _split_text,
    build_chunks,
    ensure_research_schema,
    extract_block_text,
    extract_page_properties,
    extract_page_title,
    extract_text_from_rich_text,
    text_hash,
)

# ---------------------------------------------------------------------------
# Helpers from scripts/search_research.py
# ---------------------------------------------------------------------------
from scripts.search_research import (
    extract_body,
    format_citation,
    format_date,
    get_type_label,
)

# ---------------------------------------------------------------------------
# Helpers from web/routes/research.py
# ---------------------------------------------------------------------------
from web.routes.research import _build_result, _dedupe_by_page, _extract_body

# =============================================================================
# _extract_body / extract_body  (identical logic in two modules)
# =============================================================================


class TestExtractBody:
    """Tests for the body extraction function (strips metadata header)."""

    def test_with_separator(self):
        text = "Title\n[Database]\nKey: Value\n---\nActual body text"
        assert _extract_body(text) == "Actual body text"

    def test_with_separator_multiline_body(self):
        text = "Title\n[DB]\n---\nLine 1\nLine 2\nLine 3"
        assert _extract_body(text) == "Line 1\nLine 2\nLine 3"

    def test_without_separator_skips_metadata(self):
        text = "Title\n[Database name]\nType: Verbatim\nDate: 2024-01-15\nThis is the body"
        assert _extract_body(text) == "This is the body"

    def test_without_separator_blank_lines(self):
        text = "Title\n\n[Database name]\nKey: Val\nBody here"
        assert _extract_body(text) == "Body here"

    def test_only_title(self):
        assert _extract_body("Just a title") == ""

    def test_title_and_metadata_only(self):
        text = "Title\n[DB]\nKey: Value"
        assert _extract_body(text) == ""

    def test_empty_string(self):
        assert _extract_body("") == ""

    def test_multiple_separators(self):
        text = "Title\n[DB]\n---\nFirst part\n---\nSecond part"
        assert _extract_body(text) == "First part\n---\nSecond part"

    def test_scripts_extract_body_matches(self):
        """extract_body from search_research.py should match _extract_body."""
        cases = [
            "Title\n[DB]\n---\nBody text",
            "Title\n[DB]\nKey: Value\nBody here",
            "Just title",
            "",
            "Title\n\nBody after blank",
        ]
        for text in cases:
            assert extract_body(text) == _extract_body(text), f"Mismatch for: {text!r}"


# =============================================================================
# _build_result (now takes a single joined row dict)
# =============================================================================


class TestBuildResult:
    def _row(self, **overrides):
        """Create a fake joined row (chunk + page fields)."""
        base = {
            "id": 1,
            "page_id": "page-abc",
            "chunk_index": 0,
            "text": "Title\n[DB]\n---\nSome body",
            "database_key": "entretiens",
            "title": "Interview with Alice",
            "database_name": "Entretiens et actions de recherche",
            "url": "https://notion.so/page-abc",
            "properties_json": json.dumps({"Type": "❝ Verbatim", "Date": "2024-03-15"}),
        }
        base.update(overrides)
        return base

    def test_basic(self):
        r = _build_result(self._row(), score=0.85)
        assert r["chunk_id"] == 1
        assert r["page_id"] == "page-abc"
        assert r["body"] == "Some body"
        assert r["page_title"] == "Interview with Alice"
        assert r["score"] == 0.85

    def test_no_score(self):
        r = _build_result(self._row())
        assert "score" not in r

    def test_none_properties(self):
        r = _build_result(self._row(properties_json=None, title=None, url=None, database_name=None))
        assert r["page_title"] is None
        assert r["page_url"] is None
        assert r["page_type"] is None

    def test_score_rounding(self):
        r = _build_result(self._row(), score=0.123456789)
        assert r["score"] == 0.1235


# =============================================================================
# _dedupe_by_page
# =============================================================================


class TestDedupeByPage:
    def test_empty(self):
        assert _dedupe_by_page([]) == []

    def test_no_duplicates(self):
        results = [
            {"page_id": "a", "score": 0.9},
            {"page_id": "b", "score": 0.8},
        ]
        deduped = _dedupe_by_page(results)
        assert len(deduped) == 2
        assert deduped[0]["matching_chunks"] == 1

    def test_keeps_first_occurrence(self):
        results = [
            {"page_id": "a", "score": 0.9},
            {"page_id": "a", "score": 0.7},
            {"page_id": "b", "score": 0.8},
        ]
        deduped = _dedupe_by_page(results)
        assert len(deduped) == 2
        assert deduped[0]["page_id"] == "a"
        assert deduped[0]["score"] == 0.9
        assert deduped[0]["matching_chunks"] == 2
        assert deduped[1]["page_id"] == "b"

    def test_counts_all_duplicates(self):
        results = [{"page_id": "x", "score": i} for i in range(5)]
        deduped = _dedupe_by_page(results)
        assert len(deduped) == 1
        assert deduped[0]["matching_chunks"] == 5


# =============================================================================
# format_date
# =============================================================================


class TestFormatDate:
    def test_iso_datetime(self):
        assert format_date("2024-03-15T10:30:00.000Z") == "2024-03-15"

    def test_date_only(self):
        assert format_date("2024-03-15") == "2024-03-15"

    def test_short_date(self):
        assert format_date("2024-03") == "2024-03"

    def test_none(self):
        assert format_date(None) is None

    def test_empty(self):
        assert format_date("") is None


# =============================================================================
# get_type_label
# =============================================================================


class TestGetTypeLabel:
    def test_verbatim(self):
        assert get_type_label("❝ Verbatim") == "Verbatim"

    def test_observation(self):
        assert get_type_label("👀 Observation") == "Observation"

    def test_entretien(self):
        assert get_type_label("🗣 Entretien") == "Entretien"

    def test_none(self):
        assert get_type_label(None) is None

    def test_no_emoji(self):
        assert get_type_label("Plain label") == "Plain label"

    def test_multiple_emojis(self):
        assert get_type_label("🧮 Questionnaire / quanti") == "Questionnaire / quanti"


# =============================================================================
# format_citation
# =============================================================================


class TestFormatCitation:
    def _result(self, **overrides):
        base = {
            "page_id": "abc-123",
            "title": "Entretien prescripteur RSA",
            "body": "Les bénéficiaires ont du mal avec le numérique.",
            "database_key": "entretiens",
            "database_name": "Entretiens et actions de recherche",
            "page_type": "❝ Verbatim",
            "page_date": "2024-06-10",
            "page_url": "https://notion.so/abc-123",
            "score": 0.87,
        }
        base.update(overrides)
        return base

    def test_basic_structure(self):
        citation = format_citation(self._result())
        lines = citation.split("\n")
        assert all(line.startswith("> ") for line in lines)

    def test_contains_title(self):
        citation = format_citation(self._result())
        assert "Entretien prescripteur RSA" in citation

    def test_contains_body(self):
        citation = format_citation(self._result())
        assert "bénéficiaires" in citation

    def test_contains_attribution(self):
        citation = format_citation(self._result())
        assert "Verbatim" in citation
        assert "2024-06-10" in citation

    def test_contains_links(self):
        citation = format_citation(self._result())
        assert "[Explorer]" in citation
        assert "[Notion]" in citation
        assert "abc-123" in citation

    def test_truncates_long_body_at_sentence(self):
        long_body = "First sentence. " * 30
        citation = format_citation(self._result(body=long_body))
        # Should be truncated — the body in the citation should be shorter than the input
        body_in_citation = citation.split("\n")[1].lstrip("> ")
        assert len(body_in_citation) < len(long_body)

    def test_no_body(self):
        citation = format_citation(self._result(body=""))
        lines = citation.split("\n")
        # Should only have title and attribution lines
        assert len(lines) == 2

    def test_no_notion_url(self):
        citation = format_citation(self._result(page_url=None))
        assert "[Notion]" not in citation
        assert "[Explorer]" in citation

    def test_emoji_prefix_for_verbatim(self):
        citation = format_citation(self._result(page_type="❝ Verbatim"))
        assert "❝" in citation

    def test_db_prefix_fallback(self):
        citation = format_citation(self._result(page_type=None))
        # Should fall back to DB_PREFIXES for "entretiens" → "🗣"
        assert "🗣" in citation


# =============================================================================
# text_hash
# =============================================================================


class TestTextHash:
    def test_deterministic(self):
        assert text_hash("hello") == text_hash("hello")

    def test_different_inputs(self):
        assert text_hash("hello") != text_hash("world")

    def test_is_hex_16_chars(self):
        h = text_hash("test string")
        assert len(h) == 16
        int(h, 16)  # should not raise

    def test_matches_sha256(self):
        text = "some text"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        assert text_hash(text) == expected


# =============================================================================
# _split_text
# =============================================================================


class TestSplitText:
    def test_short_text_no_split(self):
        assert _split_text("hello", 100) == ["hello"]

    def test_exact_boundary(self):
        text = "a" * 50
        assert _split_text(text, 50) == [text]

    def test_splits_at_newline(self):
        text = "line one\nline two\nline three"
        pieces = _split_text(text, 15)
        assert len(pieces) >= 2
        # All text should be preserved
        assert "".join(p.strip() for p in pieces) == text.replace("\n", "")

    def test_splits_at_space(self):
        text = "word " * 20  # 100 chars
        pieces = _split_text(text, 30)
        assert len(pieces) >= 2
        for piece in pieces:
            assert len(piece) <= 30

    def test_forced_split(self):
        # No whitespace at all — must force-split
        text = "a" * 100
        pieces = _split_text(text, 40)
        assert len(pieces) == 3
        assert pieces[0] == "a" * 40

    def test_preserves_content(self):
        text = "Hello world this is a test of splitting behavior"
        pieces = _split_text(text, 20)
        joined = " ".join(p.strip() for p in pieces)
        # All words should still be present
        for word in text.split():
            assert word in joined


# =============================================================================
# Notion API extraction helpers
# =============================================================================


class TestExtractTextFromRichText:
    def test_empty(self):
        assert extract_text_from_rich_text([]) == ""

    def test_single(self):
        assert extract_text_from_rich_text([{"plain_text": "hello"}]) == "hello"

    def test_multiple(self):
        rt = [{"plain_text": "hello "}, {"plain_text": "world"}]
        assert extract_text_from_rich_text(rt) == "hello world"

    def test_missing_plain_text(self):
        assert extract_text_from_rich_text([{"bold": True}]) == ""


class TestExtractBlockText:
    def test_paragraph(self):
        block = {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "Some text"}]},
        }
        assert extract_block_text(block) == "Some text"

    def test_heading(self):
        block = {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "A heading"}]},
        }
        assert extract_block_text(block) == "A heading"

    def test_bulleted_list(self):
        block = {
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"plain_text": "item"}]},
        }
        assert extract_block_text(block) == "item"

    def test_child_page(self):
        block = {"type": "child_page", "child_page": {"title": "Sub page"}}
        assert extract_block_text(block) == "Sub page"

    def test_unsupported_type(self):
        block = {"type": "divider", "divider": {}}
        assert extract_block_text(block) == ""


class TestExtractPageTitle:
    def test_standard(self):
        page = {
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "My Page"}]},
            }
        }
        assert extract_page_title(page) == "My Page"

    def test_empty_title(self):
        page = {"properties": {"Name": {"type": "title", "title": []}}}
        assert extract_page_title(page) == ""

    def test_no_title_property(self):
        page = {
            "properties": {
                "Status": {"type": "select", "select": {"name": "Done"}},
            }
        }
        assert extract_page_title(page) == ""


class TestExtractPageProperties:
    def test_title(self):
        page = {"properties": {"Name": {"type": "title", "title": [{"plain_text": "Test"}]}}}
        assert extract_page_properties(page)["Name"] == "Test"

    def test_select(self):
        page = {"properties": {"Type": {"type": "select", "select": {"name": "Verbatim"}}}}
        assert extract_page_properties(page)["Type"] == "Verbatim"

    def test_select_none(self):
        page = {"properties": {"Type": {"type": "select", "select": None}}}
        assert extract_page_properties(page)["Type"] is None

    def test_multi_select(self):
        page = {
            "properties": {
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "A"}, {"name": "B"}],
                }
            }
        }
        assert extract_page_properties(page)["Tags"] == ["A", "B"]

    def test_date(self):
        page = {"properties": {"Date": {"type": "date", "date": {"start": "2024-01-15"}}}}
        assert extract_page_properties(page)["Date"] == "2024-01-15"

    def test_relation(self):
        page = {
            "properties": {
                "Linked": {
                    "type": "relation",
                    "relation": [
                        {"id": "aaa-bbb-ccc-ddd-eee-fff-ggg-hhh-111"},
                    ],
                }
            }
        }
        props = extract_page_properties(page)
        assert props["Linked"] == ["aaa-bbb-ccc-ddd-eee-fff-ggg-hhh-111"]

    def test_rich_text(self):
        page = {
            "properties": {
                "Notes": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "Some notes"}],
                }
            }
        }
        assert extract_page_properties(page)["Notes"] == "Some notes"

    def test_people(self):
        page = {
            "properties": {
                "Assigned": {
                    "type": "people",
                    "people": [{"name": "Alice"}, {"name": "Bob"}],
                }
            }
        }
        assert extract_page_properties(page)["Assigned"] == ["Alice", "Bob"]


# =============================================================================
# build_chunks (integration with PostgreSQL)
# =============================================================================


@pytest.fixture
def research_db():
    """Create a PostgreSQL connection with research tables for testing."""
    from web.config import DATABASE_URL

    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    conn = psycopg2.connect(DATABASE_URL)
    ensure_research_schema(conn)
    conn.commit()
    yield conn
    # Truncate research tables
    cur = conn.cursor()
    cur.execute(
        "TRUNCATE TABLE research_chunks, research_blocks, research_relations, "
        "research_pages, research_sync_meta CASCADE"
    )
    conn.commit()
    conn.close()


def _insert_page(conn, page_id="page-1", db_key="entretiens", title="Test Page", properties=None):
    props = properties or {"Type": "❝ Verbatim"}
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO research_pages (id, database_key, database_name, title, properties_json, url) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (page_id, db_key, "Entretiens", title, json.dumps(props), f"https://notion.so/{page_id}"),
    )
    conn.commit()


def _insert_blocks(conn, page_id, texts):
    cur = conn.cursor()
    for i, text in enumerate(texts):
        cur.execute(
            "INSERT INTO research_blocks (id, page_id, type, text_content, position) VALUES (%s, %s, %s, %s, %s)",
            (f"block-{page_id}-{i}", page_id, "paragraph", text, i),
        )
    conn.commit()


class TestBuildChunks:
    def test_single_page_few_blocks(self, research_db):
        """Page with <= CHUNK_THRESHOLD blocks → single chunk, no separator."""
        _insert_page(research_db, "p1", title="Short Page")
        _insert_blocks(research_db, "p1", ["Block one.", "Block two."])

        chunks = build_chunks(research_db)
        assert len(chunks) == 1
        assert chunks[0]["page_id"] == "p1"
        assert chunks[0]["chunk_index"] == 0
        assert "Short Page" in chunks[0]["text"]
        assert "Block one." in chunks[0]["text"]
        assert "\n---\n" not in chunks[0]["text"]

    def test_many_blocks_split(self, research_db):
        """Page with > CHUNK_THRESHOLD blocks → multiple chunks with --- separator."""
        _insert_page(research_db, "p2", title="Long Page")
        # Create enough blocks to exceed threshold and target chars
        blocks = [f"Block {i} with some text to fill space." for i in range(20)]
        _insert_blocks(research_db, "p2", blocks)

        chunks = build_chunks(research_db)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk["page_id"] == "p2"
            assert "Long Page" in chunk["text"]
            assert "\n---\n" in chunk["text"]

    def test_chunk_indices_sequential(self, research_db):
        _insert_page(research_db, "p3", title="Multi")
        _insert_blocks(research_db, "p3", [f"Block {i}." for i in range(15)])

        chunks = build_chunks(research_db)
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_empty_blocks_filtered(self, research_db):
        _insert_page(research_db, "p4", title="Sparse")
        _insert_blocks(research_db, "p4", ["Real content", "", "   ", "More content"])

        chunks = build_chunks(research_db)
        assert len(chunks) == 1
        assert "Real content" in chunks[0]["text"]
        assert "More content" in chunks[0]["text"]

    def test_database_key_preserved(self, research_db):
        _insert_page(research_db, "p5", db_key="conclusions", title="Conclusion")
        _insert_blocks(research_db, "p5", ["A conclusion."])

        chunks = build_chunks(research_db)
        assert chunks[0]["database_key"] == "conclusions"

    def test_no_pages_no_chunks(self, research_db):
        assert build_chunks(research_db) == []

    def test_page_without_blocks(self, research_db):
        _insert_page(research_db, "p6", title="Empty Page")
        chunks = build_chunks(research_db)
        # Should produce either 0 or 1 chunk (header only)
        for c in chunks:
            assert c["page_id"] == "p6"

    def test_multiple_pages(self, research_db):
        _insert_page(research_db, "p7", title="Page A")
        _insert_page(research_db, "p8", title="Page B")
        _insert_blocks(research_db, "p7", ["Content A"])
        _insert_blocks(research_db, "p8", ["Content B"])

        chunks = build_chunks(research_db)
        page_ids = {c["page_id"] for c in chunks}
        assert page_ids == {"p7", "p8"}


# =============================================================================
# ensure_research_schema
# =============================================================================


class TestEnsureSchema:
    def test_creates_all_tables(self, research_db):
        cur = research_db.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'research_%%'"
        )
        tables = {r[0] for r in cur.fetchall()}
        assert "research_pages" in tables
        assert "research_blocks" in tables
        assert "research_relations" in tables
        assert "research_chunks" in tables
        assert "research_sync_meta" in tables

    def test_idempotent(self, research_db):
        """Running ensure_research_schema twice should not fail."""
        ensure_research_schema(research_db)
        research_db.commit()
        cur = research_db.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'research_%%'"
        )
        tables = {r[0] for r in cur.fetchall()}
        assert "research_pages" in tables

    def test_chunks_has_text_hash(self, research_db):
        cur = research_db.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'research_chunks'")
        cols = {r[0] for r in cur.fetchall()}
        assert "text_hash" in cols
