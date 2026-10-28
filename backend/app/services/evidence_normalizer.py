from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Dict, Optional
from uuid import UUID

from app.schemas.evidence import EvidenceCreate, EvidenceSourceType

KNOWN_TOP_LEVEL_FIELDS = {
    "evidence_id",
    "incident_id",
    "evidence_type",
    "source_type",
    "source_name",
    "source_record_id",
    "event_time",
    "ingested_at",
    "excerpt",
    "original_ref",
    "content_hash",
    "reliability_score",
    "payload",
}

TIMESTAMP_CANDIDATE_KEYS = [
    "event_time",
    "timestamp",
    "time",
    "@timestamp",
    "datetime",
    "created_at",
    "occurred_at",
]

EXCERPT_CANDIDATE_KEYS = [
    "excerpt",
    "message",
    "log",
    "summary",
    "description",
    "text",
    "body",
    "content",
    "query",
    "error",
    "event",
]

SOURCE_NAME_CANDIDATE_KEYS = [
    "source_name",
    "source",
    "system",
    "service",
    "service_name",
    "app",
    "application",
]

RECORD_ID_CANDIDATE_KEYS = [
    "source_record_id",
    "id",
    "record_id",
    "issue_key",
    "trace_id",
    "event_id",
    "commit",
    "span_id",
]

REF_CANDIDATE_KEYS = [
    "original_ref",
    "url",
    "link",
    "ref",
    "uri",
    "permalink",
]


def _parse_event_time(raw_val: Any) -> Optional[datetime]:
    if raw_val is None:
        return None
    if isinstance(raw_val, datetime):
        return raw_val

    if isinstance(raw_val, (int, float)):
        # Support unix timestamps in seconds or milliseconds
        if raw_val > 1e11:  # Milliseconds
            raw_val = raw_val / 1000.0
        try:
            return datetime.fromtimestamp(raw_val, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None

    if isinstance(raw_val, str) and raw_val.strip():
        val = raw_val.strip()
        # Handle ISO format including 'Z'
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    return None


def _infer_evidence_type(data: Dict[str, Any]) -> str:
    # Check if explicit evidence_type provided
    raw_type = data.get("evidence_type")
    if isinstance(raw_type, str) and raw_type.strip():
        return raw_type.strip()

    # Heuristic checks based on fields present in the raw data
    keys = {k.lower() for k in data.keys()}

    if any(k in keys for k in ("level", "loglevel", "log_level", "stack", "stack_trace", "traceback")):
        return "application_log"
    if any(k in keys for k in ("metric", "metrics", "metric_name", "value", "unit", "gauge")):
        return "metric"
    if any(k in keys for k in ("ticket", "issue_key", "jira", "priority", "assignee", "reporter")):
        return "ticket"
    if any(k in keys for k in ("channel", "slack", "sender", "author", "user")):
        return "slack_message"
    if any(k in keys for k in ("deployment", "commit", "deploy", "image_tag", "build_id")):
        return "deployment_log"

    return "generic"


def _infer_source_type(data: Dict[str, Any]) -> EvidenceSourceType:
    raw_src = data.get("source_type")
    if isinstance(raw_src, str):
        upper = raw_src.strip().upper()
        if upper in ("UPLOAD", "INTEGRATION"):
            return upper  # type: ignore

    return "UPLOAD"


def compute_content_hash(data: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash for raw evidence content."""
    raw_bytes = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


def normalize_evidence_dict(
    raw_data: Dict[str, Any],
    incident_id: Optional[UUID] = None,
) -> EvidenceCreate:
    """
    Normalizes an arbitrary user-submitted dictionary into a compliant EvidenceCreate model.
    - Extracts known metadata (event_time, excerpt, source_record_id, etc.) using heuristics.
    - Captures all unexpected/unknown fields into the 'payload' JSONB dictionary.
    - Computes a deterministic content_hash for deduplication.
    - Defaults source_type to 'UPLOAD'.
    """
    if not isinstance(raw_data, dict):
        raw_data = {"raw_content": str(raw_data)}

    # 1. Determine payload dictionary (merge existing payload with any extra fields)
    existing_payload = raw_data.get("payload")
    payload: Dict[str, Any] = {}
    if isinstance(existing_payload, dict):
        payload.update(existing_payload)

    # Collect unknown top-level keys into payload
    for k, v in raw_data.items():
        if k not in KNOWN_TOP_LEVEL_FIELDS:
            payload[k] = v

    # 2. Extract or infer fields
    evidence_type = _infer_evidence_type(raw_data)
    source_type = _infer_source_type(raw_data)

    # Event time
    event_time: Optional[datetime] = None
    for key in TIMESTAMP_CANDIDATE_KEYS:
        if key in raw_data and raw_data[key] is not None:
            parsed = _parse_event_time(raw_data[key])
            if parsed:
                event_time = parsed
                break

    # Excerpt
    excerpt: Optional[str] = None
    for key in EXCERPT_CANDIDATE_KEYS:
        val = raw_data.get(key)
        if isinstance(val, str) and val.strip():
            excerpt = val.strip()
            break
    if not excerpt and "raw_content" in payload:
        excerpt = str(payload["raw_content"])[:300]

    # Source Name
    source_name: Optional[str] = None
    for key in SOURCE_NAME_CANDIDATE_KEYS:
        val = raw_data.get(key)
        if isinstance(val, str) and val.strip():
            source_name = val.strip()
            break

    # Source Record ID
    source_record_id: Optional[str] = None
    for key in RECORD_ID_CANDIDATE_KEYS:
        val = raw_data.get(key)
        if val is not None:
            source_record_id = str(val).strip()
            break

    # Original Ref
    original_ref: Optional[str] = None
    for key in REF_CANDIDATE_KEYS:
        val = raw_data.get(key)
        if isinstance(val, str) and val.strip():
            original_ref = val.strip()
            break

    # Reliability score
    reliability_score: Optional[Decimal] = None
    raw_score = raw_data.get("reliability_score") or raw_data.get("confidence") or raw_data.get("score")
    if raw_score is not None:
        try:
            score_dec = Decimal(str(raw_score))
            if Decimal("0") <= score_dec <= Decimal("1"):
                reliability_score = score_dec
        except Exception:
            reliability_score = None

    # Content hash
    content_hash = raw_data.get("content_hash")
    if not content_hash or not isinstance(content_hash, str):
        content_hash = compute_content_hash(raw_data)

    return EvidenceCreate(
        incident_id=incident_id,
        evidence_type=evidence_type,
        source_type=source_type,
        source_name=source_name,
        source_record_id=source_record_id,
        event_time=event_time,
        excerpt=excerpt,
        original_ref=original_ref,
        content_hash=content_hash,
        reliability_score=reliability_score,
        payload=payload,
    )
