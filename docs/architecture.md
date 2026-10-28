# System Architecture — Sprint 1

## 1. Overview

The AI-Powered Root-Cause Investigation Platform helps investigate incidents by organizing incident details and supporting evidence into a structured format.

In Sprint 1, we focus on building the foundation of the system:

- Defining incident and evidence data contracts.
- Creating a basic FastAPI backend.
- Defining a LangGraph workflow to prepare an incident for investigation.
- Persisting and retrieving workflow state.
- Using sample software engineering incidents for demonstration.

The actual root-cause analysis and multi-agent investigation will be implemented in later sprints.

## 2. High-Level Architecture

The system consists of the following components:

1. **Sample Data:** Contains enterprise incident scenarios with realistic multi-source telemetry files (.json, .jsonl, .csv, .log).
2. **FastAPI Backend:** Exposes APIs to submit incidents, upload telemetry files, and retrieve their status.
3. **Data Contracts:** Define the standard structure of incidents and evidence, backed by PostgreSQL `JSONB` for raw payloads.
4. **LangGraph Workflow:** Manages the steps required to prepare an incident for investigation.
5. **State Persistence:** Stores workflow state so it can be retrieved later.
6. **Tests:** Verify API behavior, data validation, workflow execution, and state retrieval.

## 3. Architecture Diagram

```text
        Incident & Multi-File Telemetry
        (incident.json + .json, .jsonl, .csv, .log)
                |
                v
        FastAPI Ingestion
                |
                v
        Normalize Telemetry
        & Validate Contracts
                |
                v
        LangGraph Workflow
                |
                v
        Prepare Investigation State
                |
                v
        Persist Workflow State
                |
                v
        Retrieve State via API
```

## 4. Data Layer

### Incident

Represents the problem that needs investigation.

Example fields:
- `incident_id`
- `title`
- `original_text`
- `affected_service`
- `severity` (`SEV1`–`SEV4`, `UNKNOWN`)
- `status` (`OPEN`, `INVESTIGATING`, `RESOLVED`, `CLOSED`)
- `started_at` / `ended_at`

### Evidence

Represents telemetry artifacts (logs, metrics, traces, pull requests, alerts, chats) linked to an incident.

Core schema fields:
- `evidence_id`: UUID
- `incident_id`: UUID
- `evidence_type`: `VARCHAR(50)` (e.g., `application_log`, `metric`, `ticket`, `slack_message`)
- `source_type`: `VARCHAR(30)` (`UPLOAD` | `INTEGRATION`)
- `source_name`: origin file or system (e.g., `k8s_crashloop.json`, `datadog`)
- `source_record_id`: external ID (e.g., `HOTFIX-409`, `PR-842`)
- `event_time`: timestamp
- `excerpt`: extracted summary or message snippet
- `content_hash`: SHA-256 hash for deduplication
- `payload`: PostgreSQL `JSONB` storing all raw and arbitrary fields without schema loss

The exact fields and validation rules are defined in `data-contract.md`.

## 5. Backend Layer

FastAPI provides the API endpoints for the Sprint 1 workflow.

Responsibilities:
- Accept incident investigation requests.
- Validate incoming data.
- Start the LangGraph workflow.
- Return the workflow execution result.
- Retrieve previously persisted workflow state.

The API request and response formats are documented in `api-contract.md`.

## 6. LangGraph Workflow

LangGraph controls the flow of execution using nodes and a shared state.

The initial workflow contains these logical steps:

1. **Validate Incident:** Check that the incident information is valid.
2. **Load Evidence:** Load and associate the available evidence with the incident.
3. **Prepare Investigation State:** Organize the incident and evidence into a structured state.
4. **Complete Preparation:** Mark the preparation workflow as completed.

Each node receives the current state and returns updates to it.

In Sprint 1, these nodes establish the workflow structure. They do not perform full root-cause analysis, generate hypotheses, or run multiple AI agents.

## 7. State Persistence

The workflow state contains the information required to track an investigation preparation run.

It may include:
- Incident details.
- Associated evidence.
- Current workflow status.
- Validation errors, if any.
- Preparation results.

Each investigation run uses a unique `thread_id` to identify its workflow state.

A LangGraph checkpointer saves state checkpoints so that the application can retrieve the saved state using the appropriate thread identifier.

The persistence implementation should be configurable. The initial setup may use a development-appropriate checkpointer, with the selected storage backend documented separately.

## 8. Testing

Sprint 1 tests cover:

- Incident and evidence data validation.
- Successful workflow execution.
- Handling invalid incident data.
- API responses and error handling.
- Saving and retrieving workflow state.
- Keeping separate investigation runs isolated.

Tests verify end-to-end multi-file ingestion across three enterprise scenarios:
1. **The Bad Config Push** (K8s ConfigMap typo, skipped Jira review, Slack staging/prod confusion)
2. **Cascading Third-Party Deprecation** (Payment gateway TLS cert rotation, HTTP 502 spike)
3. **Database Connection Leak** (PR unclosed connection in batch loop, 4-hour memory exhaustion)

## 9. Scope and Limitations

### Included in Sprint 1

- Incident and evidence data contracts.
- Sample incident scenarios.
- FastAPI endpoints.
- Basic LangGraph workflow.
- Workflow state persistence and retrieval.
- Automated tests.

### Not Included in Sprint 1

- AI-generated root-cause hypotheses.
- Multi-agent investigation.
- Structural Causal Models (SCM) and causal DAG validation.
- Contradiction analysis.
- Automated fix generation and verification.
- Production integrations with Jira, Slack, or deployment systems.

These capabilities can be introduced in subsequent sprints.

## 10. Design Principle

The initial architecture should be modular and easy to extend. Future investigation agents, causal validation components, and additional evidence sources should be added without requiring major changes to the existing data contracts or API layer.