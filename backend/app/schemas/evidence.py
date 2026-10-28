
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


EvidenceSourceType = Literal["UPLOAD", "INTEGRATION"]


class EvidenceCreate(BaseModel):
    incident_id: Optional[UUID] = None
    evidence_type: str = Field(min_length=1, max_length=50)
    source_type: EvidenceSourceType
    source_name: Optional[str] = None
    source_record_id: Optional[str] = None
    event_time: Optional[datetime] = None
    excerpt: Optional[str] = None
    original_ref: Optional[str] = None
    content_hash: Optional[str] = None
    reliability_score: Optional[Decimal] = Field(
        default=None, ge=0, le=1, max_digits=5, decimal_places=4
    )
    payload: Dict[str, Any] = Field(default_factory=dict)


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_id: UUID
    incident_id: UUID
    evidence_type: str
    source_type: EvidenceSourceType
    source_name: Optional[str]
    source_record_id: Optional[str]
    event_time: Optional[datetime]
    ingested_at: datetime
    excerpt: Optional[str]
    original_ref: Optional[str]
    content_hash: Optional[str]
    reliability_score: Optional[Decimal]
    payload: Dict[str, Any]


class EvidenceBatchResponse(BaseModel):
    inserted_count: int
    skipped_count: int
    items: List[EvidenceResponse]
