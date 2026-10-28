import io
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models import EvidenceItem, Incident
from app.main import app

client = TestClient(app)


@pytest.fixture
def sample_incident():
    """Create a temporary incident for testing evidence ingestion."""
    session = SessionLocal()
    incident = Incident(
        title="Test Ingestion Incident",
        original_text="Simulated incident for evidence ingestion testing.",
        affected_service="order-service",
        severity="SEV2",
        status="OPEN",
    )
    session.add(incident)
    session.commit()
    session.refresh(incident)
    inc_id = str(incident.incident_id)
    session.close()

    yield inc_id

    # Cleanup
    session = SessionLocal()
    try:
        session.query(EvidenceItem).filter(
            EvidenceItem.incident_id == inc_id
        ).delete(synchronize_session=False)
        session.query(Incident).filter(
            Incident.incident_id == inc_id
        ).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()


def test_upload_single_file_with_unknown_fields(sample_incident):
    """Real-world test: User uploads a JSON file containing unknown telemetry fields."""
    raw_log = {
        "message": "Connection refused to database replica-02",
        "timestamp": "2026-10-25T14:30:00Z",
        "service": "billing-api",
        "level": "ERROR",
        # Arbitrary unknown fields that don't exist as columns in evidence_items table
        "pod_name": "billing-worker-7d9f8c",
        "cluster": "us-east-prod",
        "kubernetes_namespace": "production",
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "retry_attempt": 3,
    }

    file_bytes = json.dumps(raw_log).encode("utf-8")
    files = [("files", ("error_event.json", io.BytesIO(file_bytes), "application/json"))]

    res = client.post(f"/api/incidents/{sample_incident}/evidence", files=files)
    assert res.status_code == 201
    batch_res = res.json()
    assert batch_res["inserted_count"] == 1
    assert batch_res["skipped_count"] == 0

    item = batch_res["items"][0]
    assert item["incident_id"] == sample_incident
    assert item["source_type"] == "UPLOAD"  # Defaulted
    assert item["evidence_type"] == "application_log"  # Inferred from 'level'
    assert item["excerpt"] == "Connection refused to database replica-02"
    assert item["source_name"] == "error_event.json"
    assert item["source_record_id"] == "0af7651916cd43dd8448eb211c80319c"  # Extracted from trace_id
    assert item["content_hash"] is not None

    # Crucial: verify ALL unknown fields are preserved in payload JSONB
    assert item["payload"]["pod_name"] == "billing-worker-7d9f8c"
    assert item["payload"]["cluster"] == "us-east-prod"
    assert item["payload"]["kubernetes_namespace"] == "production"
    assert item["payload"]["retry_attempt"] == 3


def test_upload_file_deduplication(sample_incident):
    """Test hash-based deduplication when uploading the same file multiple times."""
    logs = [
        {"message": "Database ping failed", "timestamp": "2026-10-25T14:31:00Z"},
        {"message": "Database retry 1 failed", "timestamp": "2026-10-25T14:32:00Z"},
    ]
    file_bytes = json.dumps(logs).encode("utf-8")
    files = [("files", ("db_logs.json", io.BytesIO(file_bytes), "application/json"))]

    # First upload: 2 inserted, 0 skipped
    res1 = client.post(f"/api/incidents/{sample_incident}/evidence", files=files)
    assert res1.status_code == 201
    assert res1.json()["inserted_count"] == 2
    assert res1.json()["skipped_count"] == 0

    # Second upload of identical file: 0 inserted, 2 skipped
    files_repeat = [("files", ("db_logs.json", io.BytesIO(file_bytes), "application/json"))]
    res2 = client.post(f"/api/incidents/{sample_incident}/evidence", files=files_repeat)
    assert res2.status_code == 201
    assert res2.json()["inserted_count"] == 0
    assert res2.json()["skipped_count"] == 2


def test_upload_multiple_heterogeneous_files(sample_incident):
    """Test uploading multiple JSON, JSONL, and text files in one multipart request."""
    # File 1: JSON array with logs
    file1_content = json.dumps([
        {"message": "Worker thread crashed", "stack": "NullPointerException at line 42"},
        {"message": "Worker thread restarted", "restart_count": 1},
    ]).encode("utf-8")

    # File 2: Single JSON object with metric
    file2_content = json.dumps({
        "metric_name": "jvm.memory.heap.used",
        "value": 4194304000,
        "host": "prod-node-09",
    }).encode("utf-8")

    # File 3: JSONL log lines
    file3_content = (
        '{"level": "INFO", "message": "Healthcheck failed for /livez"}\n'
        '{"level": "CRITICAL", "message": "Container marked Unhealthy by kubelet"}\n'
    ).encode("utf-8")

    # File 4: Plain text log
    file4_content = b"Kernel panic - not syncing: Fatal exception\nSystem halted."

    files = [
        ("files", ("worker_logs.json", io.BytesIO(file1_content), "application/json")),
        ("files", ("memory_metric.json", io.BytesIO(file2_content), "application/json")),
        ("files", ("k8s_events.jsonl", io.BytesIO(file3_content), "application/jsonl")),
        ("files", ("syslog.txt", io.BytesIO(file4_content), "text/plain")),
    ]

    res = client.post(f"/api/incidents/{sample_incident}/evidence", files=files)
    assert res.status_code == 201
    data = res.json()

    # 2 (file1) + 1 (file2) + 2 (file3) + 2 (file4) = 7 items
    assert data["inserted_count"] == 7
    assert data["skipped_count"] == 0
    assert len(data["items"]) == 7

    # Verify source_name reflects each file
    source_names = {it["source_name"] for it in data["items"]}
    assert "worker_logs.json" in source_names
    assert "memory_metric.json" in source_names
    assert "k8s_events.jsonl" in source_names
    assert "syslog.txt" in source_names

    # Verify through GET /evidence
    list_res = client.get(f"/api/incidents/{sample_incident}/evidence")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 7


def test_upload_csv_file(sample_incident):
    """Test uploading a CSV telemetry file (e.g., slow queries or database logs)."""
    csv_content = (
        "timestamp,query_id,duration_ms,query,database,user\n"
        "2026-10-25T14:30:00Z,Q-101,4520,SELECT * FROM orders WHERE status='PENDING',orders_db,app_user\n"
        "2026-10-25T14:31:00Z,Q-102,7810,UPDATE inventory SET stock = stock - 1,inventory_db,service_account\n"
    ).encode("utf-8")

    files = [("files", ("slow_queries.csv", io.BytesIO(csv_content), "text/csv"))]

    res = client.post(f"/api/incidents/{sample_incident}/evidence", files=files)
    assert res.status_code == 201
    data = res.json()
    assert data["inserted_count"] == 2
    assert data["skipped_count"] == 0

    item1 = data["items"][0]
    assert item1["source_name"] == "slow_queries.csv"
    assert "SELECT * FROM orders" in item1["excerpt"]
    assert item1["payload"]["duration_ms"] == "4520"
    assert item1["payload"]["database"] == "orders_db"
    assert item1["payload"]["query_id"] == "Q-101"


def test_upload_404_for_unknown_incident():
    """Verify that uploading evidence to nonexistent incident returns 404."""
    random_id = str(uuid4())
    files = [("files", ("test.json", io.BytesIO(b'{"message": "test"}'), "application/json"))]
    res = client.post(f"/api/incidents/{random_id}/evidence", files=files)
    assert res.status_code == 404
