"""Reconciliation Job model (T113).

Represents a reconciliation job that validates data consistency between
Cassandra and PostgreSQL.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class JobType(str, Enum):
    """Type of reconciliation job."""

    HOURLY_SCHEDULED = "HOURLY_SCHEDULED"
    MANUAL_ONDEMAND = "MANUAL_ONDEMAND"


class ValidationStrategy(str, Enum):
    """Validation strategy for reconciliation."""

    ROW_COUNT = "ROW_COUNT"
    CHECKSUM = "CHECKSUM"
    TIMESTAMP_RANGE = "TIMESTAMP_RANGE"
    SAMPLE = "SAMPLE"


class JobStatus(str, Enum):
    """Status of reconciliation job."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReconciliationJob(BaseModel):
    """Reconciliation job entity.

    Tracks a single reconciliation job execution with results and metadata.
    """

    job_id: UUID = Field(default_factory=uuid4, description="Unique job identifier")
    table_name: str = Field(..., min_length=1, max_length=255, description="Table being reconciled")
    job_type: JobType = Field(..., description="Job trigger type")
    validation_strategy: ValidationStrategy = Field(..., description="Validation approach used")
    started_at: datetime = Field(..., description="Job start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Job completion timestamp")
    status: JobStatus = Field(..., description="Current job status")
    cassandra_row_count: Optional[int] = Field(None, ge=0, description="Total rows in Cassandra")
    postgres_row_count: Optional[int] = Field(None, ge=0, description="Total rows in PostgreSQL")
    mismatch_count: Optional[int] = Field(None, ge=0, description="Number of mismatched records")
    drift_percentage: Optional[Decimal] = Field(
        None,
        ge=0,
        le=100,
        description="Percentage of records out of sync"
    )
    validation_errors: Optional[Dict[str, Any]] = Field(
        None,
        description="Detailed error information (JSON)"
    )
    alert_fired: bool = Field(False, description="Whether alert was sent to AlertManager")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="Record creation timestamp"
    )

    # Related mismatches (populated by repository join)
    mismatches: List["ReconciliationMismatch"] = Field(
        default_factory=list,
        description="List of detected mismatches"
    )

    class Config:
        """Pydantic configuration."""

        from_attributes = True
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat(),
            Decimal: float
        }

    @field_validator("completed_at")
    @classmethod
    def validate_completion_time(cls, v: Optional[datetime], info) -> Optional[datetime]:
        """Validate that completed_at is after started_at."""
        if v is not None and "started_at" in info.data:
            started_at = info.data["started_at"]
            if v < started_at:
                raise ValueError("completed_at must be after started_at")
        return v

    @field_validator("drift_percentage")
    @classmethod
    def calculate_drift_if_missing(cls, v: Optional[Decimal], info) -> Optional[Decimal]:
        """Calculate drift percentage if row counts are available."""
        if v is None and all(
            key in info.data for key in ["cassandra_row_count", "postgres_row_count"]
        ):
            cass_count = info.data["cassandra_row_count"]
            pg_count = info.data["postgres_row_count"]

            if cass_count and cass_count > 0:
                diff = abs(cass_count - pg_count)
                drift = Decimal(diff) / Decimal(cass_count) * Decimal(100)
                return drift.quantize(Decimal("0.01"))

        return v

    def is_drift_critical(self, critical_threshold: float = 5.0) -> bool:
        """Check if drift exceeds critical threshold.

        Args:
            critical_threshold: Drift percentage threshold for critical alert

        Returns:
            True if drift >= critical_threshold
        """
        if self.drift_percentage is None:
            return False
        return float(self.drift_percentage) >= critical_threshold

    def is_drift_warning(self, warning_threshold: float = 1.0) -> bool:
        """Check if drift exceeds warning threshold.

        Args:
            warning_threshold: Drift percentage threshold for warning alert

        Returns:
            True if drift >= warning_threshold
        """
        if self.drift_percentage is None:
            return False
        return float(self.drift_percentage) >= warning_threshold

    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds.

        Returns:
            Duration in seconds, or None if not completed
        """
        if self.completed_at is None:
            return None
        delta = self.completed_at - self.started_at
        return delta.total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation of job
        """
        return {
            "job_id": str(self.job_id),
            "table_name": self.table_name,
            "job_type": self.job_type.value,
            "validation_strategy": self.validation_strategy.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "cassandra_row_count": self.cassandra_row_count,
            "postgres_row_count": self.postgres_row_count,
            "mismatch_count": self.mismatch_count,
            "drift_percentage": float(self.drift_percentage) if self.drift_percentage else None,
            "validation_errors": self.validation_errors,
            "alert_fired": self.alert_fired,
            "created_at": self.created_at.isoformat(),
            "duration_seconds": self.duration_seconds(),
            "mismatches": [m.to_dict() for m in self.mismatches]
        }


# Forward reference resolution
from src.models.reconciliation_mismatch import ReconciliationMismatch  # noqa: E402
ReconciliationJob.model_rebuild()
