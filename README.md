# AI-Powered Root-Cause Investigation Platform

An evidence-driven platform designed to ingest multi-source incident telemetry, organize supporting evidence, and prepare structured states for causal root-cause analysis.

---

## Sprint 1: Foundation & Workflow Orchestration

Sprint 1 establishes the foundational data contracts, API boundaries, and state preparation workflow for incident investigations.

### Key Objectives
- **Standardized Data Contracts**: Pydantic models for incidents and evidence (supporting Jira, Kubernetes logs, Prometheus metrics, Slack threads, and GitHub PRs).
- **Tolerant Multi-File Ingestion**: Upload one or multiple telemetry files (`.json`, `.jsonl`, `.csv`, `.txt`) simultaneously with automatic field extraction, JSONB payload preservation, and content-hash deduplication.
- **REST API Layer**: FastAPI service for incident intake, multi-file evidence ingestion, and state inspection.
- **LangGraph State Machine**: A deterministic 4-node preparation workflow (`Validate Incident` → `Load Evidence` → `Prepare Investigation State` → `Complete Preparation`).
- **State Persistence**: Checkpointing workflow state and retrieving execution snapshots using a stable `thread_id`.
- **Enterprise Incident Scenarios**: 3 comprehensive, realistic synthetic test scenarios:
  1. **The Bad Config Push**: K8s ConfigMap typo causes pod crashloop; Jira shows skipped peer review; Slack shows on-call engineer confusing staging and prod.
  2. **Cascading Third-Party Deprecation**: Payment gateway rotates TLS certificate; outbound microservice fails; Datadog shows HTTP 502 spike.
  3. **Database Connection Leak**: PR introduces unclosed connection in loop; gradual memory exhaustion over 4 hours before service collapse.

---

## Repository Structure

```text
root-cause-platform/
├── backend/                  # FastAPI backend service
│   ├── app/
│   │   ├── api/routes/       # REST API endpoint handlers (incidents, evidence, investigations)
│   │   ├── core/             # Application configuration and settings
│   │   ├── db/               # Relational models and repositories
│   │   ├── schemas/          # Pydantic schemas (Incident, Evidence)
│   │   ├── services/         # Incident validator & evidence normalizer
│   │   ├── workflow/         # LangGraph state graph and node definitions
│   │   └── main.py           # FastAPI application entrypoint
│   ├── tests/                # Automated pytest suite (29+ unit & scenario tests)
│   ├── requirements.txt      # Python dependencies
│   └── .env.example          # Sample environment configuration
├── data/
│   └── scenarios/            # Enterprise scenarios with multi-file telemetry (.json, .jsonl, .csv, .log)
│       ├── scenario_01/      # The Bad Config Push (k8s_crashloop, jira_hotfix, slack_oncall)
│       ├── scenario_02/      # Cascading Third-Party Deprecation (datadog_metrics, app_tls_errors, advisory)
│       └── scenario_03/      # Database Connection Leak (github_pr, prometheus_metrics, k8s_oom)
├── docs/                     # Architectural and interface specifications
│   ├── architecture.md       # Sprint 1 system architecture
│   ├── data-contract.md      # Incident, evidence, and state contract specifications
│   └── api-contract.md       # REST API endpoints and schemas
└── README.md
```

---

## Quickstart

### 1. Prerequisites
- Python 3.11+
- PostgreSQL (optional for local in-memory development, required for persistent storage)

### 2. Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1    # On Windows PowerShell
# source venv/bin/activate     # On Linux / macOS

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

### 3. Run the Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

Once running, [http://127.0.0.1:8000](http://127.0.0.1:8000).

### 4. Run Tests

```bash
pytest
```

---

## Core API Endpoints (Sprint 1)

| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/incidents` | Create an incident record |
| `GET` | `/api/incidents` | List all incidents |
| `GET` | `/api/incidents/{id}` | Retrieve incident details |
| `POST` | `/api/incidents/{id}/evidence` | Upload 1..N evidence files (`.json`, `.jsonl`, `.csv`, `.txt`) with deduplication |
| `GET` | `/api/incidents/{id}/evidence` | List all evidence items associated with an incident |
| `POST` | `/api/incidents/{id}/investigate` | Trigger/run the LangGraph preparation workflow |
| `GET` | `/api/incidents/{id}/state` | Inspect current investigation workflow state |

---

## Documentation Links

For detailed specifications, see:
- [System Architecture](docs/architecture.md)
- [Data Contracts & Schemas](docs/data-contract.md)
- [REST API Contract](docs/api-contract.md)
