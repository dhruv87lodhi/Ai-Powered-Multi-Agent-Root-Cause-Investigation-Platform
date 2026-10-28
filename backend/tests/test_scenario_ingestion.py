import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models import EvidenceItem, Incident
from app.main import app

client = TestClient(app)

SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "scenarios"

_created_test_incident_ids: list[str] = []


@pytest.fixture(autouse=True)
def cleanup_benchmark_test_data():
    """Ensure benchmark test records created during each test run are cleaned up."""
    _created_test_incident_ids.clear()
    yield
    if _created_test_incident_ids:
        session = SessionLocal()
        try:
            session.query(EvidenceItem).filter(
                EvidenceItem.incident_id.in_(_created_test_incident_ids)
            ).delete(synchronize_session=False)
            session.query(Incident).filter(
                Incident.incident_id.in_(_created_test_incident_ids)
            ).delete(synchronize_session=False)
            session.commit()
        finally:
            session.close()


def test_scenario_01_api_ingestion_and_investigation():
    """Scenario 1 (The Bad Config Push):
    Upload incident + multiple telemetry files (K8s crashloop, Jira skipped review, Slack on-call confusion).
    """
    scenario_path = SCENARIOS_DIR / "scenario_01"

    # 1. Ingest incident metadata
    with open(scenario_path / "incident.json", encoding="utf-8") as f:
        incident_payload = json.load(f)

    res = client.post("/api/incidents", json=incident_payload)
    assert res.status_code == 201
    created_incident = res.json()
    incident_id = created_incident["incident_id"]
    _created_test_incident_ids.append(incident_id)
    assert UUID(incident_id)
    assert created_incident["severity"] == "SEV1"
    assert created_incident["status"] == "OPEN"

    # 2. Upload multiple distinct evidence files in a single multipart request
    evidence_files = [
        f for f in scenario_path.glob("*") if f.name != "incident.json"
    ]
    assert len(evidence_files) >= 3

    multipart_files = []
    opened_files = []
    try:
        for file_path in evidence_files:
            fp = open(file_path, "rb")
            opened_files.append(fp)
            multipart_files.append(("files", (file_path.name, fp, "application/octet-stream")))

        ev_res = client.post(
            f"/api/incidents/{incident_id}/evidence",
            files=multipart_files,
        )
        assert ev_res.status_code == 201
        batch_data = ev_res.json()
        assert batch_data["inserted_count"] >= 30
        assert batch_data["skipped_count"] == 0
    finally:
        for fp in opened_files:
            fp.close()

    # 3. Verify evidence listing API returns all items
    list_res = client.get(f"/api/incidents/{incident_id}/evidence")
    assert list_res.status_code == 200
    evidence_items = list_res.json()
    assert len(evidence_items) >= 30

    # Verify source names reflect uploaded files
    source_names = {item["source_name"] for item in evidence_items}
    assert "k8s_crashloop.json" in source_names
    assert "jira_hotfix.json" in source_names
    assert "slack_oncall.json" in source_names

    # 4. Trigger LangGraph investigation workflow
    inv_res = client.post(f"/api/incidents/{incident_id}/investigate")
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    assert inv_data["status"] == "READY"
    assert inv_data["errors"] == []
    assert "completed_at" in inv_data


def test_scenario_02_api_ingestion():
    """Scenario 2 (Cascading Third-Party Deprecation):
    Upload incident + Datadog 502 metrics, app TLS error log, third-party status advisory.
    """
    scenario_path = SCENARIOS_DIR / "scenario_02"

    with open(scenario_path / "incident.json", encoding="utf-8") as f:
        incident_payload = json.load(f)

    res = client.post("/api/incidents", json=incident_payload)
    assert res.status_code == 201
    incident_id = res.json()["incident_id"]
    _created_test_incident_ids.append(incident_id)

    evidence_files = [
        f for f in scenario_path.glob("*") if f.name != "incident.json"
    ]
    assert len(evidence_files) >= 3

    multipart_files = []
    opened_files = []
    try:
        for file_path in evidence_files:
            fp = open(file_path, "rb")
            opened_files.append(fp)
            multipart_files.append(("files", (file_path.name, fp, "application/octet-stream")))

        ev_res = client.post(
            f"/api/incidents/{incident_id}/evidence",
            files=multipart_files,
        )
        assert ev_res.status_code == 201
        batch_data = ev_res.json()
        # 11 datadog metrics + 11 app log lines + 10 advisory records >= 30 items
        assert batch_data["inserted_count"] >= 30
    finally:
        for fp in opened_files:
            fp.close()

    inv_res = client.post(f"/api/incidents/{incident_id}/investigate")
    assert inv_res.status_code == 200
    assert inv_res.json()["status"] == "READY"


def test_scenario_03_api_ingestion():
    """Scenario 3 (Database Connection Leak):
    Upload incident + GitHub PR with leak, Prometheus 4-hour leak metrics, K8s OOMKilled events.
    """
    scenario_path = SCENARIOS_DIR / "scenario_03"

    with open(scenario_path / "incident.json", encoding="utf-8") as f:
        incident_payload = json.load(f)

    res = client.post("/api/incidents", json=incident_payload)
    assert res.status_code == 201
    incident_id = res.json()["incident_id"]
    _created_test_incident_ids.append(incident_id)

    evidence_files = [
        f for f in scenario_path.glob("*") if f.name != "incident.json"
    ]
    assert len(evidence_files) >= 3

    multipart_files = []
    opened_files = []
    try:
        for file_path in evidence_files:
            fp = open(file_path, "rb")
            opened_files.append(fp)
            multipart_files.append(("files", (file_path.name, fp, "application/octet-stream")))

        ev_res = client.post(
            f"/api/incidents/{incident_id}/evidence",
            files=multipart_files,
        )
        assert ev_res.status_code == 201
        batch_data = ev_res.json()
        # 10 github PR records + 11 prometheus leak samples + 11 k8s oom jsonl events >= 30 items
        assert batch_data["inserted_count"] >= 30
    finally:
        for fp in opened_files:
            fp.close()

    inv_res = client.post(f"/api/incidents/{incident_id}/investigate")
    assert inv_res.status_code == 200
    assert inv_res.json()["status"] == "READY"
