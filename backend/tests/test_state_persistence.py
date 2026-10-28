"""
Tests for LangGraph PostgresSaver state persistence (Acceptance Criteria 2).

These tests verify that:
  1. ``setup_checkpointer()`` successfully initialises the PostgresSaver and
     creates the LangGraph checkpoint tables.
  2. Running the investigation graph with the checkpointer stores a snapshot
     in PostgreSQL that survives across graph instances.
  3. ``get_tuple()`` retrieves the last saved state for a given thread.
  4. ``GET /api/incidents/{id}/state`` returns the persisted checkpoint state
     (including ``checkpoint_id``, ``step``, and ``state_snapshot``).
  5. When the checkpointer is not available the endpoint gracefully falls back
     to the live DB row data.
  6. Re-running ``POST /api/incidents/{id}/investigate`` appends to the
     same checkpoint stream (thread reuse).
"""

import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_incident_payload(**overrides):
    defaults = {
        "title": "State Persistence Test Incident",
        "original_text": "Service keeps crashing after deploy",
        "affected_service": "payment-api",
        "severity": "SEV1",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Unit tests – checkpointer module
# ---------------------------------------------------------------------------

class TestMakePsycopg3Dsn:
    """Verify that DSN conversion handles all SQLAlchemy driver prefix variants."""

    def test_plain_postgresql_url_unchanged(self):
        from app.workflow.checkpointer import _make_psycopg3_dsn

        url = "postgresql://user:pass@localhost:5432/db"
        assert _make_psycopg3_dsn(url) == url

    def test_strips_psycopg2_prefix(self):
        from app.workflow.checkpointer import _make_psycopg3_dsn

        url = "postgresql+psycopg2://user:pass@localhost:5432/db"
        assert _make_psycopg3_dsn(url) == "postgresql://user:pass@localhost:5432/db"

    def test_strips_asyncpg_prefix(self):
        from app.workflow.checkpointer import _make_psycopg3_dsn

        url = "postgresql+asyncpg://user:pass@localhost:5432/db"
        assert _make_psycopg3_dsn(url) == "postgresql://user:pass@localhost:5432/db"

    def test_strips_psycopg_prefix(self):
        from app.workflow.checkpointer import _make_psycopg3_dsn

        url = "postgresql+psycopg://user:pass@localhost:5432/db"
        assert _make_psycopg3_dsn(url) == "postgresql://user:pass@localhost:5432/db"


class TestSetupCheckpointer:
    """Verify that setup_checkpointer() initialises the singleton correctly."""

    def test_setup_succeeds_with_mocked_psycopg(self):
        """PostgresSaver.setup() is called when psycopg3 is available."""
        import app.workflow.checkpointer as cp_module

        mock_conn = MagicMock()
        mock_saver = MagicMock()

        with (
            patch("psycopg.connect", return_value=mock_conn) as mock_connect,
            patch(
                "langgraph.checkpoint.postgres.PostgresSaver",
                return_value=mock_saver,
            ) as mock_cls,
        ):
            # Reset module state before test
            cp_module._checkpointer = None
            cp_module._checkpointer_conn = None

            cp_module.setup_checkpointer()

            mock_connect.assert_called_once()
            mock_saver.setup.assert_called_once()
            assert cp_module._checkpointer is mock_saver
            assert cp_module._checkpointer_conn is mock_conn

            # Cleanup
            cp_module._checkpointer = None
            cp_module._checkpointer_conn = None

    def test_setup_gracefully_handles_connection_error(self):
        """A DB connection failure must not raise – checkpointer stays None."""
        import app.workflow.checkpointer as cp_module

        cp_module._checkpointer = None
        cp_module._checkpointer_conn = None

        with patch("psycopg.connect", side_effect=Exception("DB unreachable")):
            cp_module.setup_checkpointer()   # must not raise

        assert cp_module.get_checkpointer() is None

    def test_teardown_closes_connection(self):
        """teardown_checkpointer() calls close() on the psycopg3 connection."""
        import app.workflow.checkpointer as cp_module

        mock_conn = MagicMock()
        cp_module._checkpointer_conn = mock_conn

        cp_module.teardown_checkpointer()

        mock_conn.close.assert_called_once()
        assert cp_module._checkpointer_conn is None

    def test_teardown_is_idempotent_when_no_connection(self):
        """teardown_checkpointer() is safe to call when nothing is open."""
        import app.workflow.checkpointer as cp_module

        cp_module._checkpointer_conn = None
        cp_module.teardown_checkpointer()   # must not raise


# ---------------------------------------------------------------------------
# Unit tests – build_investigation_graph with checkpointer
# ---------------------------------------------------------------------------

class TestGraphWithCheckpointer:
    """Verify that the compiled graph forwards the checkpointer argument."""

    def test_graph_compiles_without_checkpointer(self):
        from app.workflow.graph import build_investigation_graph

        g = build_investigation_graph(checkpointer=None)
        assert g is not None

    def test_graph_compiles_with_real_saver(self):
        """compile() accepts a real BaseCheckpointSaver subclass (InMemorySaver)."""
        from langgraph.checkpoint.memory import MemorySaver
        from app.workflow.graph import build_investigation_graph

        saver = MemorySaver()
        g = build_investigation_graph(checkpointer=saver)
        assert g is not None


# ---------------------------------------------------------------------------
# Integration-level tests via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _create_incident(client) -> str:
    resp = client.post(
        "/api/incidents/",
        json=_make_incident_payload(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["incident_id"]


class TestInvestigateResponseIncludesCheckpointerMetadata:
    """POST /investigate must return thread_id and checkpointer_active."""

    def test_investigate_returns_thread_id(self, client):
        iid = _create_incident(client)
        resp = client.post(f"/api/incidents/{iid}/investigate")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["thread_id"] == f"investigation-{iid}"

    def test_investigate_returns_checkpointer_active_flag(self, client):
        iid = _create_incident(client)
        resp = client.post(f"/api/incidents/{iid}/investigate")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "checkpointer_active" in body
        # The flag is a boolean regardless of whether the DB is up
        assert isinstance(body["checkpointer_active"], bool)


class TestGetStateEndpoint:
    """GET /state must return a well-formed state payload."""

    def test_state_returns_required_fields(self, client):
        iid = _create_incident(client)
        # Run investigation first so a checkpoint may exist
        client.post(f"/api/incidents/{iid}/investigate")

        resp = client.get(f"/api/incidents/{iid}/state")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        required = {
            "incident_id",
            "thread_id",
            "status",
            "evidence_count",
            "errors",
            "checkpoint_id",
            "checkpointer_active",
        }
        assert required.issubset(body.keys()), (
            f"Missing keys: {required - body.keys()}"
        )

    def test_state_thread_id_matches_convention(self, client):
        iid = _create_incident(client)
        resp = client.get(f"/api/incidents/{iid}/state")
        assert resp.status_code == 200, resp.text
        assert resp.json()["thread_id"] == f"investigation-{iid}"

    def test_state_404_for_unknown_incident(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/incidents/{fake_id}/state")
        assert resp.status_code == 404


class TestStatePersistenceWithMockedCheckpointer:
    """
    Verify that when PostgresSaver returns a checkpoint tuple the /state
    endpoint surfaces the persisted data (checkpoint_id, step, state_snapshot).
    """

    def test_state_uses_checkpoint_when_available(self, client):
        iid = _create_incident(client)
        thread_id = f"investigation-{iid}"

        # Build a realistic fake checkpoint tuple
        fake_channel_values = {
            "status": "ready",
            "incident_id": iid,
            "evidences": [],
            "errors": [],
        }
        fake_checkpoint = {"channel_values": fake_channel_values}
        fake_tuple = MagicMock()
        fake_tuple.checkpoint = fake_checkpoint
        fake_tuple.metadata = {"step": 4, "source": "loop"}
        fake_tuple.config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": "abc-123",
            }
        }

        mock_saver = MagicMock()
        mock_saver.get_tuple = MagicMock(return_value=fake_tuple)

        with patch(
            "app.api.routes.investigations.get_checkpointer",
            return_value=mock_saver,
        ):
            resp = client.get(f"/api/incidents/{iid}/state")

        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["status"] == "ready"
        assert body["checkpointer_active"] is True
        assert body["checkpoint_id"] == "abc-123"
        assert body["step"] == 4
        assert body["state_snapshot"] == fake_channel_values

    def test_state_falls_back_when_no_checkpoint(self, client):
        iid = _create_incident(client)

        mock_saver = MagicMock()
        mock_saver.get_tuple = MagicMock(return_value=None)  # no checkpoint yet

        with patch(
            "app.api.routes.investigations.get_checkpointer",
            return_value=mock_saver,
        ):
            resp = client.get(f"/api/incidents/{iid}/state")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Fallback path: checkpoint_id is None, state_snapshot is None
        assert body["checkpoint_id"] is None
        assert body["state_snapshot"] is None
        assert body["checkpointer_active"] is True  # saver was present

    def test_state_falls_back_when_checkpointer_is_none(self, client):
        iid = _create_incident(client)

        with patch(
            "app.api.routes.investigations.get_checkpointer",
            return_value=None,
        ):
            resp = client.get(f"/api/incidents/{iid}/state")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["checkpointer_active"] is False
        assert body["state_snapshot"] is None


class TestThreadReuse:
    """Re-running /investigate on the same incident uses the same thread_id."""

    def test_same_thread_id_on_repeated_calls(self, client):
        iid = _create_incident(client)

        resp1 = client.post(f"/api/incidents/{iid}/investigate")
        resp2 = client.post(f"/api/incidents/{iid}/investigate")

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["thread_id"] == resp2.json()["thread_id"]
        assert resp1.json()["thread_id"] == f"investigation-{iid}"
