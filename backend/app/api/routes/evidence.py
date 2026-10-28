import csv
import io
import json
from typing import Any, Dict, List
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.db import repositories
from app.db.database import get_db
from app.schemas.evidence import (
    EvidenceBatchResponse,
    EvidenceResponse,
)
from app.services.evidence_normalizer import normalize_evidence_dict

router = APIRouter(prefix="/incidents", tags=["Evidence"])


@router.post(
    "/{incident_id}/evidence",
    response_model=EvidenceBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload one or multiple evidence files for an incident (JSON, JSONL, or text logs)",
)
async def upload_evidence(
    incident_id: UUID,
    files: List[UploadFile] = File(
        ..., description="One or more evidence files (JSON, JSONL, or text)"
    ),
    deduplicate: bool = Query(
        default=True,
        description="Skip items whose content_hash already exists for this incident",
    ),
    db: Session = Depends(get_db),
) -> EvidenceBatchResponse:
    incident = repositories.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cannot associate evidence: Incident '{incident_id}' not found",
        )

    parsed_raw_records: List[Dict[str, Any]] = []

    for file in files:
        raw_bytes = await file.read()
        filename = file.filename or "uploaded_file"
        text_content = raw_bytes.decode("utf-8", errors="replace").strip()

        if not text_content:
            continue

        # 1. Try CSV parsing if file is a .csv
        if filename.lower().endswith(".csv"):
            try:
                reader = csv.DictReader(io.StringIO(text_content))
                csv_records = []
                for row in reader:
                    row_dict = {
                        k.strip(): (v.strip() if isinstance(v, str) else v)
                        for k, v in row.items()
                        if k is not None
                    }
                    if any(row_dict.values()):
                        row_dict.setdefault("source_name", filename)
                        csv_records.append(row_dict)
                if csv_records:
                    parsed_raw_records.extend(csv_records)
                    continue
            except Exception:
                pass

        # 2. Try standard JSON parsing (array or object)
        try:
            parsed = json.loads(text_content)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        item.setdefault("source_name", filename)
                        parsed_raw_records.append(item)
                    else:
                        parsed_raw_records.append({
                            "excerpt": str(item),
                            "source_name": filename,
                        })
            elif isinstance(parsed, dict):
                parsed.setdefault("source_name", filename)
                parsed_raw_records.append(parsed)
            continue
        except json.JSONDecodeError:
            pass

        # 2. Try JSON Lines (JSONL)
        lines = text_content.splitlines()
        is_jsonl = False
        jsonl_records = []
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
                    jsonl_records.append({
                        "excerpt": str(item),
                        "source_name": filename,
                    })
                is_jsonl = True
            except json.JSONDecodeError:
                is_jsonl = False
                break

        if is_jsonl and jsonl_records:
            parsed_raw_records.extend(jsonl_records)
            continue

        # 3. Fallback: treat as raw text log lines
        for line in lines:
            line_str = line.strip()
            if line_str:
                parsed_raw_records.append({
                    "evidence_type": "application_log",
                    "excerpt": line_str,
                    "source_name": filename,
                    "payload": {"raw_line": line_str},
                })

    normalized_items = [
        normalize_evidence_dict(item, incident_id=incident_id)
        for item in parsed_raw_records
    ]

    inserted, skipped = repositories.create_evidence_batch(
        db, incident_id, normalized_items, deduplicate=deduplicate
    )

    return EvidenceBatchResponse(
        inserted_count=len(inserted),
        skipped_count=skipped,
        items=[EvidenceResponse.model_validate(it) for it in inserted],
    )


@router.get(
    "/{incident_id}/evidence",
    response_model=List[EvidenceResponse],
    status_code=status.HTTP_200_OK,
    summary="List evidence associated with an incident",
)
def list_evidence(
    incident_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> List[EvidenceResponse]:
    incident = repositories.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    return repositories.list_evidence_for_incident(
        db, incident_id, limit=limit, offset=offset
    )
