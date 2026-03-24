"""Tests for sync_sites skill."""

import tempfile
from pathlib import Path

from skills.sync_sites.scripts.sync_sites import (
    SITES,
    fetch_custom_dimensions,
    fetch_event_categories,
    fetch_saved_segments,
    format_number,
    generate_baselines_section,
    generate_dimensions_section,
    generate_events_section,
    generate_segments_section,
    update_doc_section,
)


class TestSiteConfig:
    def test_sites_defined(self):
        expected = {"emplois", "pilotage", "communaute", "dora", "plateforme", "rdv-insertion", "mon-recap", "marche"}
        assert set(SITES.keys()) == expected

    def test_emplois_config(self):
        emplois = SITES["emplois"]
        assert emplois.matomo_id == 117
        assert emplois.user_kind_dimension == 1
        assert "emplois.md" in emplois.doc_path


class TestFormatNumber:
    def test_format_number_with_value(self):
        assert format_number(1234) == "1,234"
        assert format_number(0) == "0"

    def test_format_number_none(self):
        assert format_number(None) == "-"


class TestFetchFunctions:
    def test_fetch_custom_dimensions(self, mocker):
        mock_api = mocker.MagicMock()
        mock_api.get_configured_dimensions.return_value = [
            {"idcustomdimension": 1, "name": "UserKind", "scope": "visit", "active": True},
            {"idcustomdimension": 2, "name": "Unused", "scope": "visit", "active": False},
        ]

        result = fetch_custom_dimensions(mock_api, 117)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["name"] == "UserKind"
        assert result[0]["active"] is True

    def test_fetch_saved_segments(self, mocker):
        mock_api = mocker.MagicMock()
        mock_api._request.return_value = [
            {"name": "Candidats", "definition": "dimension1==job_seeker", "auto_archive": 1},
        ]

        result = fetch_saved_segments(mock_api, 117)

        assert len(result) == 1
        assert result[0]["name"] == "Candidats"
        assert result[0]["definition"] == "dimension1==job_seeker"

    def test_fetch_event_categories(self, mocker):
        mock_api = mocker.MagicMock()
        mock_api.get_event_categories.return_value = [
            {"label": "candidature", "nb_events": 490000, "nb_visits": 50000},
            {"label": "employeurs", "nb_events": 110000, "nb_visits": 30000},
        ]

        result = fetch_event_categories(mock_api, 117, "month", "2025-12-01")

        assert len(result) == 2
        assert result[0]["category"] == "candidature"
        assert result[0]["events"] == 490000


class TestGenerateSections:
    """Test markdown generation functions."""

    def test_generate_dimensions_section_with_data(self):
        """Dimensions section renders correctly."""
        dims = [
            {"id": 1, "name": "UserKind", "scope": "visit", "active": True},
            {"id": 2, "name": "Unused", "scope": "visit", "active": False},
        ]

        result = generate_dimensions_section(dims)

        assert "## Custom Dimensions" in result
        assert "| 1 | visit | UserKind |" in result
        assert "Inactive dimensions: Unused" in result

    def test_generate_dimensions_section_empty(self):
        """Empty dimensions handled correctly."""
        result = generate_dimensions_section([])

        assert "No active custom dimensions configured" in result

    def test_generate_segments_section_with_data(self):
        """Segments section renders correctly."""
        segs = [
            {"name": "Candidats", "definition": "dimension1==job_seeker"},
            {"name": "Employeurs", "definition": "dimension1==employer"},
        ]

        result = generate_segments_section(segs)

        assert "## Saved Segments" in result
        assert "| Candidats |" in result
        assert "`dimension1==job_seeker`" in result

    def test_generate_segments_section_truncates_long_definitions(self):
        """Long segment definitions are truncated."""
        segs = [
            {"name": "Complex", "definition": "a" * 100},
        ]

        result = generate_segments_section(segs)

        assert "..." in result
        # Should truncate to ~60 chars
        assert "a" * 100 not in result

    def test_generate_events_section_with_data(self):
        """Events section renders correctly."""
        events = [
            {"name": "candidature", "events": 490000, "visits": 50000},
            {"name": "employeurs", "events": 110000, "visits": 30000},
        ]

        result = generate_events_section(events, "2025-12")

        assert "## Event Names" in result
        assert "2025-12" in result
        assert "| candidature |" in result
        # Should be sorted by event count (candidature first)
        lines = result.split("\n")
        candidature_line = [line for line in lines if "candidature" in line][0]
        employeurs_line = [line for line in lines if "employeurs" in line][0]
        assert lines.index(candidature_line) < lines.index(employeurs_line)


class TestUpdateDocSection:
    """Test document section updating."""

    def test_update_existing_section(self):
        """Existing section is replaced."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Site\n\n## Custom Dimensions\n\nOld content here.\n\n## Other Section\n\nKeep this.\n")
            f.flush()
            doc_path = Path(f.name)

        new_content = "## Custom Dimensions\n\nNew content here."
        result = update_doc_section(doc_path, "Custom Dimensions", new_content, dry_run=False)

        assert result is True
        updated = doc_path.read_text()
        assert "New content here" in updated
        assert "Old content here" not in updated
        assert "Keep this" in updated  # Other section preserved

        doc_path.unlink()

    def test_update_nonexistent_section_returns_false(self):
        """Non-existent section returns False."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Site\n\n## Other Section\n\nContent.\n")
            f.flush()
            doc_path = Path(f.name)

        new_content = "## Missing Section\n\nNew content."
        result = update_doc_section(doc_path, "Missing Section", new_content, dry_run=False)

        assert result is False

        doc_path.unlink()

    def test_dry_run_does_not_modify(self):
        """Dry run does not modify file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            original = "# Site\n\n## Custom Dimensions\n\nOld content.\n"
            f.write(original)
            f.flush()
            doc_path = Path(f.name)

        new_content = "## Custom Dimensions\n\nNew content."
        result = update_doc_section(doc_path, "Custom Dimensions", new_content, dry_run=True)

        assert result is True
        assert doc_path.read_text() == original  # File unchanged

        doc_path.unlink()


class TestGenerateBaselinesSection:
    """Test baselines markdown generation."""

    def test_generates_tables(self):
        """Baselines section generates proper tables."""
        data = {
            "monthly_stats": [
                {
                    "month": "2025-01",
                    "visitors": 1000,
                    "visits": 2000,
                    "daily_avg_visitors": 32,
                    "daily_avg_visits": 65,
                },
                {
                    "month": "2025-02",
                    "visitors": 1200,
                    "visits": 2400,
                    "daily_avg_visitors": 43,
                    "daily_avg_visits": 86,
                },
            ],
            "user_types": {},
            "engagement": [
                {"month": "2025-01", "bounce_rate": "45%", "actions_per_visit": 3.0, "avg_time": 182},
                {"month": "2025-02", "bounce_rate": "40%", "actions_per_visit": 3.5, "avg_time": 200},
            ],
        }

        result = generate_baselines_section(data, 2025)

        assert "## Traffic Baselines (2025)" in result
        assert "### Monthly Visitor Stats" in result
        assert "| 2025-01 |" in result
        assert "### Engagement Metrics" in result
        assert "3m 02s" in result  # 182 seconds formatted

    def test_handles_none_values(self):
        """None values are formatted as dashes."""
        data = {
            "monthly_stats": [
                {
                    "month": "2025-04",
                    "visitors": None,
                    "visits": None,
                    "daily_avg_visitors": None,
                    "daily_avg_visits": None,
                },
            ],
            "user_types": {},
            "engagement": [],
        }

        result = generate_baselines_section(data, 2025)

        assert "| 2025-04 |" in result
        # Should have dashes for None values
        line = [x for x in result.split("\n") if "2025-04" in x][0]
        assert "-" in line
