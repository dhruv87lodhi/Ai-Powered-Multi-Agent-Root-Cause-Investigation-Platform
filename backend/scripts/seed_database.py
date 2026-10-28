"""
Database Seeding Script for Benchmark Scenarios.

Loads the 3 enterprise benchmark scenarios (scenario_01, scenario_02, scenario_03)
into PostgreSQL (incidents, evidence_items, and LangGraph checkpoints).
Safe to run repeatedly (idempotent; deduplicates by content hash).
"""

import csv
import io
import json
import os
from pathlib import Path
import sys

# Ensure backend directory is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from app.core.config import settings
from app.db.database import Base, engine, SessionLocal
import app.db.models  # Register models
from app.db.models import Incident, EvidenceItem
from app.db import repositories
from app.schemas.incident import IncidentCreate
from app.services.evidence_normalizer import normalize_evidence_dict
from app.workflow.checkpointer import setup_checkpointer, get_checkpointer
from app.workflow.graph import build_investigation_graph


def find_scenarios_dir() -> Path:
    candidates = [
        PROJECT_ROOT / "data" / "scenarios",
        BACKEND_DIR / "data" / "scenarios",
        Path("data/scenarios").resolve(),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError(f"Could not find data/scenarios directory among: {candidates}")


def parse_evidence_file(file_path: Path):
    """Parses a telemetry file (.json, .jsonl, .log, .csv) into a list of raw dicts."""
    filename = file_path.name
    content = file_path.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return []

    # 1. CSV
    if filename.lower().endswith(".csv"):
        try:
            reader = csv.DictReader(io.StringIO(content))
            return [
                {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
                for row in reader
            ]
        except Exception:
            pass

    # 2. JSON array or single object
    if filename.lower().endswith(".json"):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        item.setdefault("source_name", filename)
                return parsed
            elif isinstance(parsed, dict):
                parsed.setdefault("source_name", filename)
                return [parsed]
        except json.JSONDecodeError:
            pass

    # 3. JSON Lines (.jsonl)
    lines = content.splitlines()
    jsonl_records = []
    is_jsonl = True
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        try:
            item = json.loads(line_str)
            if isinstance(item, dict):
                item.setdefault("source_name", filename)
                jsonl_records.append(item)
            else:
                is_jsonl = False
                break
        except json.JSONDecodeError:
            is_jsonl = False
            break

    if is_jsonl and jsonl_records:
        return jsonl_records

    # 4. Fallback: text log lines
    records = []
    for line in lines:
        line_str = line.strip()
        if line_str:
            records.append({
                "evidence_type": "application_log",
                "excerpt": line_str,
                "source_name": filename,
                "payload": {"raw_line": line_str},
            })
    return records


def seed_database():
    print("=" * 70)
    print("AI ROOT CAUSE PLATFORM - BENCHMARK DATABASE SEEDER")
    print("=" * 70)
    print(f"Target Database URL: {settings.DATABASE_URL}")

    # 1. Ensure tables exist
    print("\n[1/4] Ensuring PostgreSQL schema tables exist...")
    Base.metadata.create_all(bind=engine)
    print("  -> incidents and evidence_items tables verified.")

    # 2. Setup checkpointer
    print("\n[2/4] Initialising LangGraph PostgresSaver checkpointer...")
    setup_checkpointer()
    checkpointer = get_checkpointer()
    if checkpointer:
        print("  -> PostgresSaver active (checkpoint tables verified).")
    else:
        print("  -> Warning: PostgresSaver could not connect; continuing with live DB.")

    # 3. Ingest benchmark scenarios
    scenarios_dir = find_scenarios_dir()
    scenario_dirs = sorted([d for d in scenarios_dir.iterdir() if d.is_dir() and d.name.startswith("scenario_")])
    print(f"\n[3/4] Found {len(scenario_dirs)} scenario folders in {scenarios_dir}...")

    session = SessionLocal()
    results = []

    try:
        for s_dir in scenario_dirs:
            scenario_name = s_dir.name
            incident_file = s_dir / "incident.json"
            if not incident_file.is_file():
                print(f"  -> Skipping {scenario_name}: no incident.json found.")
                continue

            with open(incident_file, encoding="utf-8") as f:
                inc_raw = json.load(f)

            inc_schema = IncidentCreate(**inc_raw)

            # Check if incident already exists by title
            stmt = select(Incident).where(Incident.title == inc_schema.title)
            existing_incident = session.execute(stmt).scalar_one_or_none()

            if existing_incident:
                incident = existing_incident
                print(f"\n  * Scenario '{scenario_name}': Using existing incident {incident.incident_id}")
            else:
                incident = repositories.create_incident(session, inc_schema)
                print(f"\n  * Scenario '{scenario_name}': Created new incident {incident.incident_id}")

            print(f"    Title: {incident.title[:65]}...")
            print(f"    Severity: {incident.severity} | Service: {incident.affected_service}")

            # Parse and ingest all evidence files
            evidence_files = [f for f in sorted(s_dir.iterdir()) if f.name != "incident.json" and f.is_file()]
            total_inserted = 0
            total_skipped = 0

            for ev_file in evidence_files:
                raw_items = parse_evidence_file(ev_file)
                normalized = [normalize_evidence_dict(item, incident_id=incident.incident_id) for item in raw_items]
                inserted, skipped = repositories.create_evidence_batch(
                    session, incident.incident_id, normalized, deduplicate=True
                )
                total_inserted += len(inserted)
                total_skipped += skipped
                print(f"    - {ev_file.name}: {len(inserted)} inserted, {skipped} skipped (deduped)")

            # Total evidence in DB for this incident
            all_evidence = repositories.list_evidence_for_incident(session, incident.incident_id, limit=500)

            # Run LangGraph workflow to produce checkpoint
            thread_id = f"investigation-{incident.incident_id}"
            workflow_status = "NOT_RUN"
            checkpoint_id = None

            try:
                graph = build_investigation_graph(checkpointer=checkpointer)
                initial_state = {
                    "incident_id": str(incident.incident_id),
                    "incident": {
                        "incident_id": str(incident.incident_id),
                        "title": incident.title,
                        "original_text": incident.original_text,
                        "affected_service": incident.affected_service,
                        "severity": incident.severity,
                        "status": incident.status,
                        "started_at": incident.started_at.isoformat() if incident.started_at else None,
                        "ended_at": incident.ended_at.isoformat() if incident.ended_at else None,
                    },
                    "evidences": [
                        {
                            "evidence_id": str(ev.evidence_id),
                            "incident_id": str(ev.incident_id),
                            "evidence_type": ev.evidence_type,
                            "source_type": ev.source_type,
                            "source_name": ev.source_name,
                            "source_record_id": ev.source_record_id,
                            "event_time": ev.event_time.isoformat() if ev.event_time else None,
                            "excerpt": ev.excerpt,
                            "original_ref": ev.original_ref,
                            "reliability_score": float(ev.reliability_score) if ev.reliability_score is not None else None,
                            "payload": ev.payload,
                        }
                        for ev in all_evidence
                    ],
                    "status": "received",
                    "errors": [],
                }
                res = graph.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})
                workflow_status = res.get("status", "UNKNOWN")

                if checkpointer:
                    cp_tuple = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
                    if cp_tuple:
                        checkpoint_id = cp_tuple.config.get("configurable", {}).get("checkpoint_id")
            except Exception as e:
                workflow_status = f"ERROR: {e}"

            results.append({
                "scenario": scenario_name,
                "incident_id": str(incident.incident_id),
                "title": incident.title,
                "severity": incident.severity,
                "evidence_count": len(all_evidence),
                "workflow_status": workflow_status,
                "checkpoint_id": checkpoint_id or "N/A",
            })

    finally:
        session.close()

    # 4. Print summary table
    print("\n[4/4] Benchmark Seeding Summary:")
    print("=" * 105)
    print(f"{'Scenario':<14} | {'Severity':<8} | {'Evidences':<10} | {'Status':<8} | {'Incident ID':<36} | {'Checkpoint'}")
    print("-" * 105)
    for r in results:
        print(f"{r['scenario']:<14} | {r['severity']:<8} | {r['evidence_count']:<10} | {r['workflow_status']:<8} | {r['incident_id']:<36} | {str(r['checkpoint_id'])[:12]}")
    print("=" * 105)
    print("SUCCESS: Benchmark scenarios loaded into PostgreSQL.\n")


if __name__ == "__main__":
    seed_database()

