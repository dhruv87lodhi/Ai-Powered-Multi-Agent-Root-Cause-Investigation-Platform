# REST API Contract (Sprint 1)

## Base URL
`/api`

---

## Core Endpoints Overview

| Method | Endpoint | Purpose | Request Body | Response |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/incidents` | Create a new incident record | `IncidentCreate` | `201 Created` (`IncidentResponse`) |
| `GET` | `/api/incidents` | List all incidents | None (optional query params) | `200 OK` (`list[IncidentResponse]`) |
| `GET` | `/api/incidents/{id}` | Retrieve incident details | None | `200 OK` (`IncidentResponse`) |
| `POST` | `/api/incidents/{id}/evidence` | Upload one or multiple evidence files (`.json`, `.jsonl`, `.csv`, `.txt`) | `multipart/form-data` (`files`) | `201 Created` (`EvidenceBatchResponse`) |
| `GET` | `/api/incidents/{id}/evidence` | List all evidence items for an incident | None | `200 OK` (`list[EvidenceResponse]`) |
| `POST` | `/api/incidents/{id}/investigate` | Trigger the LangGraph state machine workflow | None | `200 OK` (`InvestigationState`) |
| `GET` | `/api/incidents/{id}/state` | Inspect current investigation workflow state | None | `200 OK` (`InvestigationState`) |

---

## Benchmark & Scenario Ingestion Strategy

Rather than maintaining a separate or proprietary "benchmark loader" endpoint in backend application code, **all telemetry—including benchmark scenarios (`scenario_01`, `scenario_02`, `scenario_03`)—is ingested exclusively through the standard production REST API endpoints**:

1. **Incident Creation**: Benchmark incidents are submitted via `POST /api/incidents`.
2. **Evidence Ingestion**: Benchmark telemetry files are submitted via `POST /api/incidents/{id}/evidence` with `"source_type": "UPLOAD"`.
3. **Automated Verification**: Pytest suites load test datasets from `data/scenarios/` and verify the complete ingestion and state preparation pipeline through the standard HTTP interface.

This ensures:
- Full end-to-end testing of Pydantic schemas, database constraints, and API routing.
- Zero code duplication between test loaders and production ingestion paths.
- Total decoupling of the backend service from local filesystem dependencies.

---

## Detailed Endpoint Specifications

### 1. Create Incident
* **URL**: `POST /api/incidents`
* **Status**: `201 Created`
* **Request Payload**:
  ```json
  {
    "title": "Database connection pool exhausted",
    "original_text": "The order service started returning HTTP 500 errors because PostgreSQL connections were saturated.",
    "affected_service": "order-service",
    "severity": "SEV1",
    "started_at": "2026-10-24T09:30:00+05:30"
  }
  ```
* **Response Payload**:
  ```json
  {
    "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "title": "Database connection pool exhausted",
    "original_text": "The order service started returning HTTP 500 errors because PostgreSQL connections were saturated.",
    "affected_service": "order-service",
    "severity": "SEV1",
    "status": "OPEN",
    "started_at": "2026-10-24T09:30:00+05:30",
    "ended_at": null,
    "created_at": "2026-10-24T09:35:12+05:30",
    "updated_at": "2026-10-24T09:35:12+05:30"
  }
  ```

---

### 2. List Incidents
* **URL**: `GET /api/incidents?limit=50&offset=0`
* **Status**: `200 OK`
* **Response Payload**: `list[IncidentResponse]`

---

### 3. Get Incident
* **URL**: `GET /api/incidents/{incident_id}`
* **Status**: `200 OK` (or `404 Not Found`)
* **Response Payload**: `IncidentResponse`

---

### 4. Upload Evidence Files
* **URL**: `POST /api/incidents/{incident_id}/evidence`
* **Content-Type**: `multipart/form-data`
* **Status**: `201 Created`
* **Request**: Upload 1 or more files via the `files` form field (supports `.json`, `.jsonl`, `.csv`, `.txt`).
* **Query Parameters**:
  * `deduplicate` (bool, default: `true`): Skips files/records matching existing content hashes.
* **Response Payload**: `EvidenceBatchResponse`
  ```json
  {
    "inserted_count": 3,
    "skipped_count": 0,
    "items": [
      {
        "evidence_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
        "evidence_type": "ticket",
        "source_type": "UPLOAD",
        "source_name": "k8s_crashloop.json",
        "source_record_id": "JIRA-101",
        "event_time": "2026-10-24T09:32:00+05:30",
        "ingested_at": "2026-10-24T09:35:40+05:30",
        "excerpt": "Multiple users reporting timeouts when placing orders during checkout.",
        "original_ref": "https://jira.company.com/browse/JIRA-101",
        "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "reliability_score": 0.9500,
        "payload": {
          "reporter": "alice@company.com",
          "priority": "Highest"
        }
      }
    ]
  }
  ```

---

### 5. List Evidence for Incident
* **URL**: `GET /api/incidents/{incident_id}/evidence`
* **Status**: `200 OK`
* **Response Payload**: `list[EvidenceResponse]`

---

### 6. Run LangGraph Preparation Workflow
* **URL**: `POST /api/incidents/{incident_id}/investigate`
* **Status**: `200 OK`
* **Notes**: Re-running this endpoint on the same incident reuses the existing `thread_id`, appending a new checkpoint to the same stream rather than starting fresh.
* **Response Payload**:
  ```json
  {
    "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "status": "ready",
    "errors": [],
    "completed_at": "2026-10-24T09:36:00.123456+00:00",
    "thread_id": "investigation-c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "checkpointer_active": true
  }
  ```

---

### 7. Get Investigation State
* **URL**: `GET /api/incidents/{incident_id}/state`
* **Status**: `200 OK` (or `404 Not Found` if the incident does not exist)
* **Behaviour**:
  * If `PostgresSaver` is active and a checkpoint exists for the incident's `thread_id`, the response reflects the **persisted checkpoint state** from PostgreSQL.
  * If no checkpoint is found yet (workflow has not been triggered), the response falls back to **live database row data** with `state_snapshot: null`.
  * If the checkpointer is unavailable (DB unreachable at startup), `checkpointer_active` is `false` and live DB data is returned.
* **Response Payload** (checkpoint found):
  ```json
  {
    "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "thread_id": "investigation-c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "status": "ready",
    "evidence_count": 5,
    "errors": [],
    "checkpoint_id": "1f1d2892-48cf-60e0-800a-bda9c1a3aba5",
    "step": 10,
    "source": "loop",
    "checkpointer_active": true,
    "state_snapshot": {
      "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
      "status": "ready",
      "errors": [],
      "evidences": ["..."]
    }
  }
  ```
* **Response Payload** (no checkpoint yet / fallback):
  ```json
  {
    "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "thread_id": "investigation-c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "status": "OPEN",
    "evidence_count": 3,
    "errors": [],
    "checkpoint_id": null,
    "step": null,
    "source": null,
    "checkpointer_active": true,
    "state_snapshot": null
  }
  ```
