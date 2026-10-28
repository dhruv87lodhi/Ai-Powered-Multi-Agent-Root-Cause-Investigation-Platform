# Data Contracts — Sprint 1
## AI-Powered Root Cause Investigation Platform

---

## 1. Purpose

This document defines the authoritative data contracts, relational database schema, and validation rules used in **Sprint 1** of the **AI-Powered Root Cause Investigation Platform**.

The objective of these contracts is to ensure that incident telemetry and supporting evidence adhere to a consistent, strongly typed, and validated specification as they are ingested via REST APIs, stored in PostgreSQL, and orchestrated through the LangGraph state machine.

For Sprint 1, the platform focuses on:
- Standardized, production-grade schema for **Incidents** and **Evidence Items**.
- PostgreSQL relational tables with database-level integrity constraints (`CHECK`, `FOREIGN KEY`, `NOT NULL`, `INDEX`).
- Pydantic models for API request boundary validation and response serialization.
- Relational mapping between incidents and multi-source evidence.
- State preparation and deterministic workflow progression via LangGraph.
- State persistence and checkpoint retrieval using unique `thread_id` keys.

---

## 2. Scope

### In Scope (Sprint 1)
- Relational PostgreSQL schema (`incidents` and `evidence_items` tables).
- Incident schema with standard SRE severities (`SEV1`–`SEV4`, `UNKNOWN`) and lifecycle statuses (`OPEN`, `INVESTIGATING`, `RESOLVED`, `CLOSED`).
- Evidence schema supporting multi-modal ingestion (`UPLOAD`, `INTEGRATION`) with PostgreSQL `JSONB` for raw payloads.
- REST API request and response data contracts (`IncidentCreate`, `IncidentResponse`, `EvidenceCreate`, `EvidenceResponse`).
- Pure validation service and database check constraint enforcement.
- LangGraph `InvestigationState` schema and node state transitions (`received` → `validated` → `prepared` → `READY`).

### Out of Scope (Deferred to Future Sprints)
- LLM-generated root-cause hypotheses and candidate ranking.
- Structural Causal Models (SCM) and directed acyclic graph (DAG) synthesis.
- Autonomous contradiction detection and counterfactual reasoning.
- Automated code patch generation and automated remediation verification.
- Direct OAuth integrations with Jira, Slack, or GitHub.

---

## 3. Relational Database Schema

The persistent storage layer uses **PostgreSQL**. Tables are defined via SQLAlchemy ORM in [backend/app/db/models.py](file:///c:/Users/Dhruv%20Lodhi/programs/EPAM/MAIN/root-cause-platform/backend/app/db/models.py).

### 3.1 Table: `incidents`

Represents an observed system anomaly, outage, or performance degradation requiring investigation.

| Column Name | PostgreSQL Type | Nullable | Default / Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `incident_id` | `UUID` | **No** | Primary Key (`gen_random_uuid()`) | Globally unique identifier for the incident. |
| `title` | `VARCHAR(200)` | **No** | None | Brief, human-readable summary of the incident. |
| `original_text` | `TEXT` | **No** | None | Comprehensive problem description or report. |
| `affected_service` | `TEXT` | Yes | `NULL` | Component, microservice, or system impacted. |
| `severity` | `VARCHAR(20)` | **No** | `'UNKNOWN'`<br>Check: `IN ('SEV1', 'SEV2', 'SEV3', 'SEV4', 'UNKNOWN')` | Standard engineering impact severity. |
| `status` | `VARCHAR(20)` | **No** | `'OPEN'`<br>Check: `IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED')` | Current incident lifecycle state. |
| `started_at` | `TIMESTAMPTZ` | Yes | `NULL` | Timestamp when the incident was detected or began. |
| `ended_at` | `TIMESTAMPTZ` | Yes | `NULL`<br>Check: `ended_at >= started_at` | Timestamp when the incident was resolved. |
| `created_at` | `TIMESTAMPTZ` | **No** | `NOW()` | Audit record creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` | **No** | `NOW()` | Audit record last updated timestamp. |

* **Indexes**:
  * `idx_incidents_status_created` on `(status, created_at)` for high-performance filtering of active incidents.

---

### 3.2 Table: `evidence_items`

Stores discrete telemetry artifacts, logs, metrics, or messages linked to an incident.

| Column Name | PostgreSQL Type | Nullable | Default / Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `evidence_id` | `UUID` | **No** | Primary Key (`gen_random_uuid()`) | Unique platform identifier for the evidence record. |
| `incident_id` | `UUID` | **No** | FK → `incidents.incident_id`<br>`ON DELETE RESTRICT` | Parent incident reference. |
| `evidence_type` | `VARCHAR(50)` | **No** | None | Classification (e.g., `application_log`, `ticket`, `metric`, `slack_message`). |
| `source_type` | `VARCHAR(30)` | **No** | Check: `IN ('UPLOAD', 'INTEGRATION')` | Channel through which evidence entered the platform. |
| `source_name` | `TEXT` | Yes | `NULL` | External origin system (e.g., `"jira"`, `"datadog"`, `"slack"`). |
| `source_record_id` | `TEXT` | Yes | `NULL` | External locator ID (e.g., `"JIRA-501"`, `"DEPLOY-204"`). |
| `event_time` | `TIMESTAMPTZ` | Yes | `NULL` | Timestamp of the event in the original source system. |
| `ingested_at` | `TIMESTAMPTZ` | **No** | `NOW()` | Timestamp when stored into the platform. |
| `excerpt` | `TEXT` | Yes | `NULL` | Short extracted snippet or human-readable summary. |
| `original_ref` | `TEXT` | Yes | `NULL` | External URL, permalink, or log bucket URI. |
| `content_hash` | `TEXT` | Yes | `NULL` | Hash (SHA-256) of raw content for deduplication. |
| `reliability_score` | `NUMERIC(5,4)`| Yes | Check: `0.0000 <= score <= 1.0000` | Normalized confidence score (0 to 1). |
| `payload` | `JSONB` | **No** | `'{}'::jsonb` | Complete, unstructured/semi-structured raw payload. |

* **Indexes**:
  * `idx_evidence_incident_event` on `(incident_id, event_time)` for chronological event stream generation.

---

## 4. Incident Data Contract

### 4.1 Allowed Severities & Definitions

| Severity | Definition | Operational Example |
| :--- | :--- | :--- |
| `SEV1` | **Critical Outage**: Catastrophic impact on core user-facing functionality or business revenue. Immediate war-room. | Entire checkout service down; payment processing failing for all customers. |
| `SEV2` | **Major Degradation**: Significant customer impact or partial system failure without full outage. | 40% of API calls timing out; background inventory sync failing. |
| `SEV3` | **Minor Issue**: Low-to-moderate degradation with functional workaround available. | Latency spikes on internal reporting dashboard. |
| `SEV4` | **Low Impact / Cosmetic**: Minor bug or nuisance with minimal operational consequence. | Styling issue on non-critical admin settings page. |
| `UNKNOWN` | **Unassessed**: Initial triage state prior to impact assessment. | Newly ingested synthetic or uncategorized telemetry. |

### 4.2 Allowed Lifecycle Statuses

* `OPEN`: Incident is recorded but active investigation has not commenced.
* `INVESTIGATING`: Workflow has started; evidence is being analyzed.
* `RESOLVED`: Root cause identified and mitigating action applied.
* `CLOSED`: Post-incident review completed; record archived.

### 4.3 Incident JSON Example

```json
{
  "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
  "title": "Database connection pool exhausted",
  "original_text": "The order service started returning HTTP 500 errors because PostgreSQL connections were saturated. Latency escalated to >10s.",
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

## 5. Evidence Data Contract

### 5.1 Ingestion Sources (`source_type`)

* `UPLOAD`: File (`.json`, `.jsonl`, `.csv`, `.txt`) or snippet submitted via API or UI.
* `INTEGRATION`: Automated webhooks or scheduled pollers from external tools (Jira, Slack, Datadog).

### 5.2 Evidence JSON Example

```json
[
  {
    "evidence_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "evidence_type": "ticket",
    "source_type": "INTEGRATION",
    "source_name": "jira",
    "source_record_id": "JIRA-501",
    "event_time": "2026-10-24T09:32:00+05:30",
    "ingested_at": "2026-10-24T09:35:40+05:30",
    "excerpt": "Multiple users reporting timeouts when placing orders during checkout.",
    "original_ref": "https://jira.company.com/browse/JIRA-501",
    "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "reliability_score": 0.9500,
    "payload": {
      "reporter": "alice@company.com",
      "priority": "Highest",
      "components": ["checkout", "order-api"]
    }
  },
  {
    "evidence_id": "8f2a1b9c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
    "incident_id": "c1f8a847-a8d2-4b2a-89bc-9937bc38d9b1",
    "evidence_type": "application_log",
    "source_type": "UPLOAD",
    "source_name": "kubernetes_deployment",
    "source_record_id": "DEPLOY-204",
    "event_time": "2026-10-24T09:25:00+05:30",
    "ingested_at": "2026-10-24T09:35:41+05:30",
    "excerpt": "Database pool config updated: max_connections decreased from 100 to 20.",
    "original_ref": "arn:aws:logs:us-east-1:123456789:log-group:order-service",
    "content_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
    "reliability_score": 1.0000,
    "payload": {
      "environment": "production",
      "commit": "a4f890c",
      "author": "devops-bot"
    }
  }
]
```

---

## 6. Identifier Disambiguation

To ensure clean system boundaries and traceability:

* **`incident_id`**: Internal platform UUID identifying the overarching incident.
* **`evidence_id`**: Internal platform UUID identifying a specific evidentiary item.
* **`source_record_id`**: External identifier assigned by the originating system (e.g., `"JIRA-501"`, `"DEPLOY-204"`, Slack message ID).
* **`original_ref`**: URI, permalink, or pointer allowing human engineers or automated agents to inspect the raw external source.
* **`thread_id`**: Execution identifier used exclusively by LangGraph checkpointers to track and retrieve state transitions.

---

## 7. API Schemas & Boundaries

API models are validated with Pydantic v2 in [backend/app/schemas/](file:///c:/Users/Dhruv%20Lodhi/programs/EPAM/MAIN/root-cause-platform/backend/app/schemas/).

### 7.1 Incident Schemas
* **`IncidentCreate`**:
  * `title`: `str` (1–200 characters)
  * `original_text`: `str` (minimum 1 character)
  * `affected_service`: `Optional[str]`
  * `severity`: `Severity` (default: `"UNKNOWN"`)
  * `started_at`: `Optional[datetime]`
  * `ended_at`: `Optional[datetime]`
* **`IncidentResponse`**: Returns all fields including `incident_id`, `created_at`, `updated_at`, and `status`.

### 7.2 Evidence Schemas
* **`EvidenceCreate`**:
  * `incident_id`: `UUID`
  * `evidence_type`: `str` (1–50 characters)
  * `source_type`: `EvidenceSourceType` (`"UPLOAD" | "INTEGRATION"`)
  * `source_name`: `Optional[str]`
  * `source_record_id`: `Optional[str]`
  * `event_time`: `Optional[datetime]`
  * `excerpt`: `Optional[str]`
  * `original_ref`: `Optional[str]`
  * `reliability_score`: `Optional[Decimal]` (0.0 to 1.0)
  * `payload`: `Dict[str, Any]` (default: `{}`)
* **`EvidenceResponse`**: Returns all stored columns including `evidence_id` and `ingested_at`.

---

## 8. LangGraph Investigation State Machine

Defined in [backend/app/workflow/state.py](file:///c:/Users/Dhruv%20Lodhi/programs/EPAM/MAIN/root-cause-platform/backend/app/workflow/state.py).

### 8.1 State Schema

```python
from typing import TypedDict


class InvestigationState(TypedDict, total=False):
    incident_id: str
    incident: dict
    evidences: list[dict]
    status: str
    errors: list[str]
    completed_at: str
```

### 8.2 State Lifecycle Transitions

```text
  [Input Incident Payload]
              │
              ▼
    receive_incident   ──(failed)──► [END]
              │
              ▼
    validate_incident  ──(failed)──► [END]
              │
              ▼
  prepare_investigation ──(failed)──► [END]
              │
              ▼
         mark_ready
              │
              ▼
            [READY]
```

* **`received`**: Initial node confirms incident presence and extracts `incident_id`.
* **`validated`**: Incident passes data validation rules via [incident_validator.py](file:///c:/Users/Dhruv%20Lodhi/programs/EPAM/MAIN/root-cause-platform/backend/app/services/incident_validator.py).
* **`prepared`**: Evidence and incident context are structured for causal analysis.
* **`READY`**: Pipeline completes preparation; injects UTC ISO `completed_at` timestamp.
* **`failed`**: Any validation or state anomaly terminates graph execution with populated `errors` list.

---

## 9. State Persistence & Checkpointing

* LangGraph workflows are executed with runtime configuration binding to a stable `thread_id`:
  ```python
  config = {"configurable": {"thread_id": f"investigation-{incident_id}"}}
  ```
* Sprint 1 uses **`PostgresSaver`** (synchronous, from `langgraph-checkpoint-postgres`) as the production checkpointer. The singleton is initialised in `backend/app/workflow/checkpointer.py` and wired into the FastAPI `lifespan` startup handler.
* On startup, `PostgresSaver.setup()` is called to idempotently create four LangGraph-managed tables in the same `ai_root_cause` database:
  * `checkpoints` — one row per graph step per `thread_id` (full state snapshot).
  * `checkpoint_blobs` — serialized channel values for each snapshot.
  * `checkpoint_writes` — pending writes buffer before commit.
  * `checkpoint_migrations` — schema version tracking for the checkpointer.
* The `thread_id` convention is `investigation-{incident_id}`, so re-running `POST /investigate` on the same incident appends to the same checkpoint stream rather than creating a new one.
* If the database is unreachable at startup the checkpointer silently stays `None`; all routes fall back to live DB row data without crashing (`checkpointer_active: false` in the response).
* Checkpoint data is accessible via `GET /api/incidents/{id}/state`, which returns `checkpoint_id`, `step`, `source`, and `state_snapshot` when a persisted checkpoint is found.

---

## 10. Sprint 1 Acceptance Criteria

- [x] Relational database schema with PostgreSQL constraints implemented in `models.py`.
- [x] Strong Pydantic request/response boundary models defined in `schemas/`.
- [x] Pure incident validation service with timezone and constraint validation in `incident_validator.py`.
- [x] LangGraph deterministic 4-node pipeline with conditional fail-fast routing in `graph.py` and `nodes.py`.
- [x] CRUD repository functions with PostgreSQL session management in `repositories.py`.
- [x] Tolerant multi-file evidence ingestion (`.json`, `.jsonl`, `.csv`, `.txt`) with SHA-256 deduplication via `evidence_normalizer.py` and `repositories.create_evidence_batch()`.
- [x] `PostgresSaver` checkpointer wired into FastAPI lifespan, creating checkpoint tables on startup and persisting state snapshots keyed by `thread_id` per incident.
- [x] `GET /api/incidents/{id}/state` returns live checkpoint state (`checkpoint_id`, `step`, `source`, `state_snapshot`) with graceful fallback when no checkpoint exists.
- [x] Comprehensive automated test coverage (**49 tests passing**) across health checks, repositories, graph nodes, multi-file ingestion, 3 enterprise scenario pipelines, and state persistence (unit + mocked integration).
- [x] Authoritative, aligned Data Contract documentation in `docs/data-contract.md`.