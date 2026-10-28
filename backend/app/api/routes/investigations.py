from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db import repositories
from app.workflow.graph import build_investigation_graph
from app.workflow.checkpointer import get_checkpointer

router = APIRouter(prefix="/incidents", tags=["Investigations"])

# Thread-id convention: one thread per incident UUID so that re-running
# /investigate on the same incident appends to the same checkpoint stream.
def _thread_id(incident_id: UUID) -> str:
    return f"investigation-{incident_id}"


@router.post(
    "/{incident_id}/investigate",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Execute LangGraph preparation workflow for incident",
)
def trigger_investigation(
    incident_id: UUID,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    incident = repositories.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    evidences = repositories.list_evidence_for_incident(db, incident_id)

    initial_state = {
        "incident_id": str(incident.incident_id),
        "incident": {
            "incident_id": str(incident.incident_id),
            "title": incident.title,
            "original_text": incident.original_text,
            "affected_service": incident.affected_service,
            "severity": incident.severity,
            "status": incident.status,
            "started_at": (
                incident.started_at.isoformat() if incident.started_at else None
            ),
            "ended_at": (
                incident.ended_at.isoformat() if incident.ended_at else None
            ),
        },
        "evidences": [
            {
                "evidence_id": str(ev.evidence_id),
                "incident_id": str(ev.incident_id),
                "evidence_type": ev.evidence_type,
                "source_type": ev.source_type,
                "source_name": ev.source_name,
                "source_record_id": ev.source_record_id,
                "event_time": (
                    ev.event_time.isoformat() if ev.event_time else None
                ),
                "excerpt": ev.excerpt,
                "original_ref": ev.original_ref,
                "reliability_score": (
                    float(ev.reliability_score)
                    if ev.reliability_score is not None
                    else None
                ),
                "payload": ev.payload,
            }
            for ev in evidences
        ],
        "status": "received",
        "errors": [],
    }

    checkpointer = get_checkpointer()
    graph = build_investigation_graph(checkpointer=checkpointer)

    thread_id = _thread_id(incident_id)
    result = graph.invoke(
        initial_state,
        config={"configurable": {"thread_id": thread_id}},
    )

    # Attach persistence metadata to the response so callers know where to
    # retrieve state from.
    result["thread_id"] = thread_id
    result["checkpointer_active"] = checkpointer is not None
    return result


@router.get(
    "/{incident_id}/state",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Retrieve current investigation state from PostgreSQL checkpoint",
)
def get_investigation_state(
    incident_id: UUID,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    incident = repositories.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )

    thread_id = _thread_id(incident_id)
    checkpointer = get_checkpointer()

    # ------------------------------------------------------------------
    # Attempt to load the latest checkpoint snapshot from PostgreSQL.
    # ------------------------------------------------------------------
    if checkpointer is not None:
        try:
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint_tuple = checkpointer.get_tuple(config)

            if checkpoint_tuple is not None:
                saved_state = checkpoint_tuple.checkpoint.get("channel_values", {})
                metadata = checkpoint_tuple.metadata or {}
                return {
                    "incident_id": str(incident.incident_id),
                    "thread_id": thread_id,
                    "status": saved_state.get("status", incident.status),
                    "evidence_count": len(saved_state.get("evidences", [])),
                    "errors": saved_state.get("errors", []),
                    "checkpoint_id": checkpoint_tuple.config.get(
                        "configurable", {}
                    ).get("checkpoint_id"),
                    "step": metadata.get("step"),
                    "source": metadata.get("source"),
                    "checkpointer_active": True,
                    "state_snapshot": saved_state,
                }
        except Exception as exc:
            # Log but fall through to the lightweight fallback below.
            import logging
            logging.getLogger(__name__).warning(
                "Could not retrieve checkpoint for thread '%s': %s", thread_id, exc
            )

    # ------------------------------------------------------------------
    # Fallback: return live DB row data (no persistent checkpoint found).
    # ------------------------------------------------------------------
    evidences = repositories.list_evidence_for_incident(db, incident_id)
    return {
        "incident_id": str(incident.incident_id),
        "thread_id": thread_id,
        "status": incident.status,
        "evidence_count": len(evidences),
        "errors": [],
        "checkpoint_id": None,
        "step": None,
        "source": None,
        "checkpointer_active": checkpointer is not None,
        "state_snapshot": None,
    }
