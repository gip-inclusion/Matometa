"""Tests for Notion publishing feature.

Tests markdown-to-blocks conversion, frontmatter extraction,
the publish API endpoint, and the UI button behavior.
"""

import pytest

SAMPLE_REPORT = """\
---
date: 2026-01-15
website: emplois
original_query: "Quels sont les événements les plus fréquents ?"
query_category: "Event analysis"
---

# Analyse des événements

## Contexte

Ce rapport analyse les **événements principaux** sur le site *Emplois*.

### Données clés

| Événement | Volume | Description |
|-----------|--------|-------------|
| **clic-metiers** | 84 316 | Filtrage par métiers |
| start_application | 63 094 | Début candidature |

### Parcours utilisateur

```mermaid
flowchart TD
    A["Recherche"] --> B["Filtrage"]
    B --> C["Candidature"]
```

### Implémentation

```python
def track_event(category, action, name):
    _paq.push(['trackEvent', category, action, name])
```

- Premier point avec `code inline`
- Deuxième point avec [un lien](https://example.com)

1. Étape numérotée une
2. Étape numérotée deux

---

Fin du rapport.
"""


@pytest.fixture
def report(app):
    from web.database import store

    return store.create_report(
        title="Analyse des événements",
        content=SAMPLE_REPORT,
        website="emplois",
        category="Event analysis",
        user_id="test@example.com",
    )


@pytest.fixture
def report_with_db_query(app):
    from web.database import store

    return store.create_report(
        title="Test Report",
        content=SAMPLE_REPORT,
        website="emplois",
        category="testing",
        original_query="Generate a report about events",
        user_id="test@example.com",
    )


class TestMarkdownToBlocks:
    def test_strips_yaml_frontmatter(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("---\ndate: 2026-01-01\n---\n\n# Title\n")
        types = [b["type"] for b in blocks]
        assert "paragraph" not in types or not any("date:" in str(b) for b in blocks)
        assert any(b["type"] == "heading_1" for b in blocks)

    def test_headings(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("# H1\n\n## H2\n\n### H3\n")
        types = [b["type"] for b in blocks]
        assert types == ["heading_1", "heading_2", "heading_3"]

    def test_paragraph_with_inline_formatting(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("This is **bold** and *italic* and `code`.\n")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"
        rich = blocks[0]["paragraph"]["rich_text"]
        annotations = {r["text"]["content"]: r["annotations"] for r in rich}
        assert annotations["bold"]["bold"] is True
        assert annotations["italic"]["italic"] is True
        assert annotations["code"]["code"] is True

    def test_link_parsing(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("See [example](https://example.com) here.\n")
        rich = blocks[0]["paragraph"]["rich_text"]
        link_obj = next(r for r in rich if r["text"].get("link"))
        assert link_obj["text"]["link"]["url"] == "https://example.com"
        assert link_obj["text"]["content"] == "example"

    def test_code_block_with_language(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("```python\nprint('hello')\n```\n")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "python"
        assert blocks[0]["code"]["rich_text"][0]["text"]["content"] == "print('hello')"

    def test_mermaid_block(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("```mermaid\nflowchart TD\n    A --> B\n```\n")
        assert blocks[0]["type"] == "code"
        assert blocks[0]["code"]["language"] == "mermaid"

    def test_table(self):
        from web.notion import markdown_to_blocks

        md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
        blocks = markdown_to_blocks(md)
        assert len(blocks) == 1
        table = blocks[0]
        assert table["type"] == "table"
        assert table["table"]["table_width"] == 2
        assert table["table"]["has_column_header"] is True
        rows = table["table"]["children"]
        assert len(rows) == 3  # header + 2 data rows
        # Check cell content
        first_cell = rows[0]["table_row"]["cells"][0][0]["text"]["content"]
        assert first_cell.strip() == "A"

    def test_bullet_list(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("- one\n- two\n")
        assert len(blocks) == 2
        assert all(b["type"] == "bulleted_list_item" for b in blocks)

    def test_numbered_list(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("1. first\n2. second\n")
        assert len(blocks) == 2
        assert all(b["type"] == "numbered_list_item" for b in blocks)

    def test_divider(self):
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks("text\n\n---\n\nmore text\n")
        types = [b["type"] for b in blocks]
        assert "divider" in types

    def test_full_report_block_count(self):
        """The sample report should produce a reasonable number of blocks."""
        from web.notion import markdown_to_blocks

        blocks = markdown_to_blocks(SAMPLE_REPORT)
        assert len(blocks) > 10
        types = {b["type"] for b in blocks}
        assert types >= {
            "heading_1",
            "heading_2",
            "heading_3",
            "paragraph",
            "table",
            "code",
            "bulleted_list_item",
            "numbered_list_item",
            "divider",
        }

    def test_code_block_truncated_at_2000(self):
        from web.notion import markdown_to_blocks

        long_code = "x" * 3000
        blocks = markdown_to_blocks(f"```python\n{long_code}\n```\n")
        content = blocks[0]["code"]["rich_text"][0]["text"]["content"]
        assert len(content) <= 2000


class TestFrontmatterExtraction:
    def test_frontmatter_query_overrides_db_field(self, mocker):
        from web.notion import publish_report

        mocker.patch("web.notion.is_configured", return_value=True)
        mock_req = mocker.patch("web.notion.notion_request")
        mock_req.return_value = {"id": "abc", "url": "https://notion.so/page"}
        publish_report(
            title="Test",
            content=SAMPLE_REPORT,
            original_query="Generate a report about something",
        )
        call_args = mock_req.call_args_list[0]
        payload = call_args[0][2]
        query_text = payload["properties"]["Requête initiale"]["rich_text"][0]["text"]["content"]
        assert query_text == "Quels sont les événements les plus fréquents ?"

    def test_frontmatter_date_overrides_argument(self, mocker):
        from web.notion import publish_report

        mocker.patch("web.notion.is_configured", return_value=True)
        mock_req = mocker.patch("web.notion.notion_request")
        mock_req.return_value = {"id": "abc", "url": "https://notion.so/page"}
        publish_report(
            title="Test",
            content=SAMPLE_REPORT,
            date="1999-01-01",
        )
        call_args = mock_req.call_args_list[0]
        payload = call_args[0][2]
        assert payload["properties"]["Date de publication"]["date"]["start"] == "2026-01-15"

    def test_db_field_used_when_no_frontmatter(self, mocker):
        from web.notion import publish_report

        mocker.patch("web.notion.is_configured", return_value=True)
        mock_req = mocker.patch("web.notion.notion_request")
        mock_req.return_value = {"id": "abc", "url": "https://notion.so/page"}
        content_no_fm = "# Just a heading\n\nSome text.\n"
        publish_report(
            title="Test",
            content=content_no_fm,
            original_query="fallback query",
            date="2026-06-01",
        )
        call_args = mock_req.call_args_list[0]
        payload = call_args[0][2]
        assert payload["properties"]["Requête initiale"]["rich_text"][0]["text"]["content"] == "fallback query"
        assert payload["properties"]["Date de publication"]["date"]["start"] == "2026-06-01"


class TestPublishNotionEndpoint:
    def test_returns_503_when_not_configured(self, mocker, app, client, report):
        mocker.patch("web.notion.is_configured", return_value=False)
        resp = client.post(
            f"/api/reports/{report.id}/publish-notion",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert resp.status_code == 503

    def test_returns_404_for_missing_report(self, mocker, app, client):
        mocker.patch("web.notion.is_configured", return_value=True)
        resp = client.post(
            "/api/reports/99999/publish-notion",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert resp.status_code == 404

    def test_publishes_and_stores_url(self, mocker, app, client, report):
        mocker.patch("web.notion.is_configured", return_value=True)
        mock_publish = mocker.patch("web.notion.publish_report")
        mock_publish.return_value = ("page-id-123", "https://notion.so/My-Page-123")
        resp = client.post(
            f"/api/reports/{report.id}/publish-notion",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://notion.so/My-Page-123"

        # Second call should return cached URL without calling publish again
        mock_publish.reset_mock()
        resp2 = client.post(
            f"/api/reports/{report.id}/publish-notion",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["url"] == "https://notion.so/My-Page-123"
        mock_publish.assert_not_called()

    def test_returns_500_on_error(self, mocker, app, client, report):
        mocker.patch("web.notion.is_configured", return_value=True)
        mocker.patch("web.notion.publish_report", side_effect=Exception("timeout"))
        resp = client.post(
            f"/api/reports/{report.id}/publish-notion",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == "Failed to publish to Notion"


class TestNotionButton:
    def test_shows_export_button_when_no_url(self, app, client, report):
        resp = client.get(
            f"/rapports/{report.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert resp.status_code == 200
        assert b'id="notionBtn" data-report-id=' in resp.content
        assert b'href="https://notion.so' not in resp.content

    def test_shows_link_after_publish(self, mocker, app, client, report):
        mocker.patch("web.notion.is_configured", return_value=True)
        mock_publish = mocker.patch("web.notion.publish_report")
        mock_publish.return_value = ("page-id", "https://notion.so/Page-123")
        client.post(
            f"/api/reports/{report.id}/publish-notion",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        resp = client.get(
            f"/rapports/{report.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        assert resp.status_code == 200
        assert "Lien Notion".encode() in resp.content
        assert b"https://notion.so/Page-123" in resp.content
