"""Tests for lib.webinaires: schema, helpers, Grist sync, upsert logic."""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from lib.webinaires import (
    GristClient,
    T_INSCRIPTIONS,
    T_SESSIONS,
    T_SYNC_META,
    T_WEBINAIRES,
    _extract_organisation,
    _grist_duration_to_minutes,
    _ts_to_iso,
    ensure_schema,
    infer_product,
    sync_grist,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db():
    """In-memory SQLite database with schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


@pytest.fixture
def grist_client():
    """GristClient with mocked HTTP session."""
    with patch.dict("os.environ", {
        "GRIST_API_KEY": "fake-key",
        "GRIST_WEBINAIRES_DOC_ID": "fake-doc",
    }):
        client = GristClient()
        client._session = MagicMock()
        return client


# =============================================================================
# Product inference
# =============================================================================


class TestInferProduct:
    def test_dora(self):
        assert infer_product("Présentation de DORA et prise en main") == "dora"

    def test_marche(self):
        assert infer_product("Devenez expert des achats inclusifs") == "marche"

    def test_marche_accent(self):
        assert infer_product("Découvrez le Marché de l'inclusion") == "marche"

    def test_pilotage(self):
        assert infer_product("Webinaire Pilotage : indicateurs") == "pilotage"

    def test_immersion(self):
        assert infer_product("Utiliser le site d'Immersion Facilitée") == "immersion"

    def test_communaute(self):
        assert infer_product("Bienvenue sur la Communauté") == "communaute"

    def test_rdv_insertion(self):
        assert infer_product("Formation RDV-Insertion pour les CD") == "rdv-insertion"

    def test_emplois(self):
        assert infer_product("Les emplois de l'inclusion") == "emplois"

    def test_emplois_prescripteur(self):
        assert infer_product("Webinaire pour les prescripteurs habilités") == "emplois"

    def test_emplois_pass_iae(self):
        assert infer_product("Comprendre le Pass IAE") == "emplois"

    def test_unknown(self):
        assert infer_product("Formation générale sur le numérique") is None

    def test_empty(self):
        assert infer_product("") is None

    def test_none(self):
        assert infer_product(None) is None

    def test_priority_dora_over_emplois(self):
        """Dora pattern is checked before emplois."""
        assert infer_product("DORA pour les prescripteurs") == "dora"


# =============================================================================
# Timestamp helpers
# =============================================================================


class TestTsToIso:
    def test_valid_timestamp(self):
        result = _ts_to_iso(1700000000)
        assert result.startswith("2023-11-14")
        assert "+00:00" in result

    def test_float_timestamp(self):
        result = _ts_to_iso(1700000000.5)
        assert result is not None

    def test_zero(self):
        assert _ts_to_iso(0) is None

    def test_none(self):
        assert _ts_to_iso(None) is None

    def test_invalid(self):
        assert _ts_to_iso("not-a-number") is None


class TestGristDurationToMinutes:
    def test_30_min(self):
        assert _grist_duration_to_minutes("30 min") == 30

    def test_45_min(self):
        assert _grist_duration_to_minutes("45 min") == 45

    def test_60_min(self):
        assert _grist_duration_to_minutes("60 min") == 60

    def test_none(self):
        assert _grist_duration_to_minutes(None) is None

    def test_empty(self):
        assert _grist_duration_to_minutes("") is None


# =============================================================================
# Organisation extraction (Livestorm custom fields)
# =============================================================================


class TestExtractOrganisation:
    def test_company_field(self):
        fields = [{"id": "company", "value": "ACME Corp"}]
        assert _extract_organisation(fields) == "ACME Corp"

    def test_structure_field(self):
        fields = [{"id": "quel_est_le_nom_de_votre_structure", "value": "PLIE Bordeaux"}]
        assert _extract_organisation(fields) == "PLIE Bordeaux"

    def test_entreprise_field(self):
        fields = [{"id": "entreprise", "value": "Mission Locale"}]
        assert _extract_organisation(fields) == "Mission Locale"

    def test_no_match(self):
        fields = [{"id": "departement", "value": "75"}]
        assert _extract_organisation(fields) is None

    def test_empty(self):
        assert _extract_organisation([]) is None

    def test_priority(self):
        """company takes precedence over entreprise."""
        fields = [
            {"id": "entreprise", "value": "second"},
            {"id": "company", "value": "first"},
        ]
        assert _extract_organisation(fields) == "first"

    def test_skips_empty_value(self):
        fields = [
            {"id": "company", "value": ""},
            {"id": "entreprise", "value": "Fallback"},
        ]
        assert _extract_organisation(fields) == "Fallback"


# =============================================================================
# Database schema
# =============================================================================


class TestSchema:
    def test_tables_exist(self, db):
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert T_WEBINAIRES in tables
        assert T_SESSIONS in tables
        assert T_INSCRIPTIONS in tables
        assert T_SYNC_META in tables

    def test_ensure_schema_idempotent(self, db):
        """Calling ensure_schema twice doesn't fail."""
        ensure_schema(db)
        ensure_schema(db)

    def test_registration_unique_constraint(self, db):
        """Duplicate (source, webinar_id, session_id, email) is rejected."""
        db.execute(
            f"INSERT INTO {T_INSCRIPTIONS} (source, webinar_id, session_id, email) "
            "VALUES ('test', 'w1', 's1', 'a@b.com')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                f"INSERT INTO {T_INSCRIPTIONS} (source, webinar_id, session_id, email) "
                "VALUES ('test', 'w1', 's1', 'a@b.com')"
            )

    def test_registration_different_sessions_ok(self, db):
        """Same email in different sessions is allowed."""
        db.execute(
            f"INSERT INTO {T_INSCRIPTIONS} (source, webinar_id, session_id, email) "
            "VALUES ('test', 'w1', 's1', 'a@b.com')"
        )
        db.execute(
            f"INSERT INTO {T_INSCRIPTIONS} (source, webinar_id, session_id, email) "
            "VALUES ('test', 'w1', 's2', 'a@b.com')"
        )
        count = db.execute(f"SELECT COUNT(*) FROM {T_INSCRIPTIONS}").fetchone()[0]
        assert count == 2


# =============================================================================
# Grist sync
# =============================================================================


def _mock_grist_response(records):
    """Create a mock response for GristClient.get_records."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"records": records}
    resp.raise_for_status = MagicMock()
    return resp


SAMPLE_WEBINAIRES = [
    {
        "id": 11,
        "fields": {
            "event_id": "dora-prise-en-main-001",
            "titre": "DORA présentation et prise en main",
            "description": "Découvrez DORA",
            "organizer_email": "delphine@inclusion.gouv.fr",
            "duree": "60 min",
            "date_event": 1769086800,
            "date_fin": 1769090400,
            "lien_webinaire": "https://webinaire.example.com/1",
            "capacite": 350,
            "nb_inscrits": 2,
            "status": True,
            "form_inscription_url": "https://tally.so/r/xxx",
        },
    },
    {
        "id": 23,
        "fields": {
            "event_id": "missions-locales-001",
            "titre": "Webinaire special Missions Locales",
            "description": "L'essentiel pour les Missions Locales",
            "organizer_email": "aurelie@inclusion.gouv.fr",
            "duree": "45 min",
            "date_event": 1770195600,
            "date_fin": 1770198300,
            "lien_webinaire": "https://webinaire.example.com/2",
            "capacite": 350,
            "nb_inscrits": 220,
            "status": True,
            "form_inscription_url": "https://tally.so/r/yyy",
        },
    },
]

SAMPLE_INSCRIPTIONS = [
    {
        "id": 1,
        "fields": {
            "email": "nora@example.fr",
            "nom": "Bentadmia",
            "prenom": "Nora",
            "entreprise": "CIO d'Elancourt",
            "date_inscription": 1767715153.834,
            "a_participe": False,
            "event_id": "dora-prise-en-main-001",
        },
    },
    {
        "id": 2,
        "fields": {
            "email": "Laure@EXAMPLE.FR",
            "nom": "SORBEE",
            "prenom": "Laure",
            "entreprise": "ESAT Les Néfliers",
            "date_inscription": 1767775834.152,
            "a_participe": True,
            "event_id": "dora-prise-en-main-001",
        },
    },
    {
        "id": 3,
        "fields": {
            "email": "julie@example.fr",
            "nom": "Dupont",
            "prenom": "Julie",
            "entreprise": "Mission Locale de Reims",
            "date_inscription": 1770000000,
            "a_participe": True,
            "event_id": "missions-locales-001",
        },
    },
]


class TestGristSync:
    def test_sync_webinars(self, db, grist_client):
        """Webinaires are inserted with correct fields."""
        def mock_get(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get
        sync_grist(db, grist_client)

        rows = db.execute(f"SELECT * FROM {T_WEBINAIRES} ORDER BY id").fetchall()
        assert len(rows) == 2

        dora = dict(rows[0])
        assert dora["id"] == "grist:dora-prise-en-main-001"
        assert dora["source"] == "grist"
        assert dora["title"] == "DORA présentation et prise en main"
        assert dora["product"] == "dora"
        assert dora["duration_minutes"] == 60
        assert dora["capacity"] == 350

    def test_sync_inscriptions(self, db, grist_client):
        """Inscriptions are inserted with correct fields."""
        def mock_get(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            if "Inscriptions" in url:
                return _mock_grist_response(SAMPLE_INSCRIPTIONS)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get
        sync_grist(db, grist_client)

        rows = db.execute(
            f"SELECT * FROM {T_INSCRIPTIONS} ORDER BY email"
        ).fetchall()
        assert len(rows) == 3

        julie = dict(rows[0])
        assert julie["email"] == "julie@example.fr"
        assert julie["first_name"] == "Julie"
        assert julie["last_name"] == "Dupont"
        assert julie["organisation"] == "Mission Locale de Reims"
        assert julie["attended"] == 1
        assert julie["webinar_id"] == "grist:missions-locales-001"
        assert julie["session_id"] == ""

    def test_email_lowercased(self, db, grist_client):
        """Emails are normalized to lowercase."""
        def mock_get(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            if "Inscriptions" in url:
                return _mock_grist_response(SAMPLE_INSCRIPTIONS)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get
        sync_grist(db, grist_client)

        emails = [
            r[0] for r in db.execute(
                f"SELECT email FROM {T_INSCRIPTIONS} ORDER BY email"
            ).fetchall()
        ]
        assert all(e == e.lower() for e in emails)
        assert "laure@example.fr" in emails

    def test_idempotent(self, db, grist_client):
        """Running sync twice doesn't duplicate data."""
        def mock_get(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            if "Inscriptions" in url:
                return _mock_grist_response(SAMPLE_INSCRIPTIONS)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get

        sync_grist(db, grist_client)
        sync_grist(db, grist_client)

        webinar_count = db.execute(f"SELECT COUNT(*) FROM {T_WEBINAIRES}").fetchone()[0]
        reg_count = db.execute(f"SELECT COUNT(*) FROM {T_INSCRIPTIONS}").fetchone()[0]
        assert webinar_count == 2
        assert reg_count == 3

    def test_updates_on_resync(self, db, grist_client):
        """Re-syncing updates changed fields (e.g. a_participe)."""
        def mock_get_v1(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            if "Inscriptions" in url:
                return _mock_grist_response(SAMPLE_INSCRIPTIONS[:1])
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get_v1
        sync_grist(db, grist_client)

        # Nora didn't attend initially
        attended = db.execute(
            f"SELECT attended FROM {T_INSCRIPTIONS} WHERE email='nora@example.fr'"
        ).fetchone()[0]
        assert attended == 0

        # Now she did attend
        updated = [{
            "id": 1,
            "fields": {
                **SAMPLE_INSCRIPTIONS[0]["fields"],
                "a_participe": True,
            },
        }]

        def mock_get_v2(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            if "Inscriptions" in url:
                return _mock_grist_response(updated)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get_v2
        sync_grist(db, grist_client)

        attended = db.execute(
            f"SELECT attended FROM {T_INSCRIPTIONS} WHERE email='nora@example.fr'"
        ).fetchone()[0]
        assert attended == 1

    def test_skips_empty_email(self, db, grist_client):
        """Records without email are skipped."""
        no_email = [{
            "id": 99,
            "fields": {
                "email": "",
                "nom": "Ghost",
                "prenom": "User",
                "event_id": "dora-prise-en-main-001",
            },
        }]

        def mock_get(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            if "Inscriptions" in url:
                return _mock_grist_response(no_email)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get
        sync_grist(db, grist_client)

        count = db.execute(f"SELECT COUNT(*) FROM {T_INSCRIPTIONS}").fetchone()[0]
        assert count == 0

    def test_skips_empty_event_id(self, db, grist_client):
        """Webinaires without event_id are skipped."""
        no_event_id = [{
            "id": 99,
            "fields": {
                "event_id": "",
                "titre": "Orphan webinar",
            },
        }]

        def mock_get(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(no_event_id)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get
        sync_grist(db, grist_client)

        count = db.execute(f"SELECT COUNT(*) FROM {T_WEBINAIRES}").fetchone()[0]
        assert count == 0

    def test_return_value(self, db, grist_client):
        """sync_grist returns (webinar_count, registration_count)."""
        def mock_get(url, **kwargs):
            if "Webinaires" in url:
                return _mock_grist_response(SAMPLE_WEBINAIRES)
            if "Inscriptions" in url:
                return _mock_grist_response(SAMPLE_INSCRIPTIONS)
            return _mock_grist_response([])

        grist_client._session.get.side_effect = mock_get
        webinars, regs = sync_grist(db, grist_client)
        assert webinars == 2
        assert regs == 3
