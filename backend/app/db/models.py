
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column

from app.db.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    incident_id = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    title = mapped_column(String(200), nullable=False)
    original_text = mapped_column(Text, nullable=False)
    affected_service = mapped_column(Text, nullable=True)
    severity = mapped_column(
        String(20), nullable=False, server_default=text("'UNKNOWN'")
    )
    status = mapped_column(
        String(20), nullable=False, server_default=text("'OPEN'")
    )
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('SEV1', 'SEV2', 'SEV3', 'SEV4', 'UNKNOWN')",
            name="incidents_severity_check",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED')",
            name="incidents_status_check",
        ),
        CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
            name="incidents_time_check",
        ),
        Index("idx_incidents_status_created", "status", "created_at"),
    )


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    evidence_id = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    incident_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.incident_id", ondelete="RESTRICT"),
        nullable=False,
    )
    evidence_type = mapped_column(String(50), nullable=False)
    source_type = mapped_column(String(30), nullable=False)
    source_name = mapped_column(Text, nullable=True)
    source_record_id = mapped_column(Text, nullable=True)
    event_time = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    excerpt = mapped_column(Text, nullable=True)
    original_ref = mapped_column(Text, nullable=True)
    content_hash = mapped_column(Text, nullable=True)
    reliability_score = mapped_column(Numeric(5, 4), nullable=True)
    payload = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(
            "reliability_score IS NULL OR reliability_score BETWEEN 0 AND 1",
            name="evidence_reliability_check",
        ),
        CheckConstraint(
            "source_type IN ('UPLOAD', 'INTEGRATION')",
            name="evidence_source_type_check",
        ),
        Index("idx_evidence_incident_event", "incident_id", "event_time"),
    )
