"""Reconciliation Mismatch model (T114).

Represents a single data mismatch detected during reconciliation between
Cassandra and PostgreSQL.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class MismatchType(str, Enum):
    """Type of data mismatch."""

    MISSING_IN_POSTGRES = "MISSING_IN_POSTGRES"
    MISSING_IN_CASSANDRA = "MISSING_IN_CASSANDRA"
    DATA_MISMATCH = "DATA_MISMATCH"


class ResolutionStatus(str, Enum):
    """Status of mismatch resolution."""

    PENDING = "PENDING"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    MANUAL_RESOLVED = "MANUAL_RESOLVED"
    IGNORED = "IGNORED"


class ReconciliationMismatch(BaseModel):
    """Reconciliation mismatch entity.

    Tracks a specific data inconsistency detected between Cassandra and PostgreSQL.
    """

    mismatch_id: UUID = Field(
        default_factory=uuid4,
        description="Unique mismatch identifier"
    )
    job_id: UUID = Field(..., description="Reference to reconciliation job")
    table_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Table with mismatch"
    )
    primary_key_value: str = Field(..., description="Primary key of mismatched record")
    mismatch_type: MismatchType = Field(..., description="Category of mismatch")
    cassandra_checksum: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description="SHA-256 checksum of Cassandra record"
    )
    postgres_checksum: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description="SHA-256 checksum of PostgreSQL record"
    )
    cassandra_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Full Cassandra record data (JSON)"
    )
    postgres_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Full PostgreSQL record data (JSON)"
    )
    detected_at: datetime = Field(..., description="When mismatch was detected")
    resolution_status: ResolutionStatus = Field(
        ResolutionStatus.PENDING,
        description="Current resolution state"
    )
    resolution_notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Human notes on resolution attempt"
    )
    resolved_at: Optional[datetime] = Field(None, description="When issue was resolved")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="Record creation timestamp"
    )

    class Config:
        """Pydantic configuration."""

        from_attributes = True
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat()
        }

    @field_validator("resolved_at")
    @classmethod
    def validate_resolution_time(cls, v: Optional[datetime], info) -> Optional[datetime]:
        """Validate that resolved_at is after detected_at."""
        if v is not None and "detected_at" in info.data:
            detected_at = info.data["detected_at"]
            if v < detected_at:
                raise ValueError("resolved_at must be after detected_at")
        return v

    @field_validator("cassandra_checksum", "postgres_checksum")
    @classmethod
    def validate_checksum_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate checksum is valid SHA-256 hex string."""
        if v is not None:
            # Verify it's a valid hex string
            try:
                int(v, 16)
            except ValueError:
                raise ValueError("Checksum must be a valid hexadecimal string")
        return v

    def is_resolved(self) -> bool:
        """Check if mismatch has been resolved.

        Returns:
            True if resolution_status is not PENDING
        """
        return self.resolution_status != ResolutionStatus.PENDING

    def needs_attention(self) -> bool:
        """Check if mismatch requires manual intervention.

        Returns:
            True if status is PENDING
        """
        return self.resolution_status == ResolutionStatus.PENDING

    def get_data_diff(self) -> Dict[str, Dict[str, Any]]:
        """Get differences between Cassandra and PostgreSQL data.

        Returns:
            Dictionary with 'cassandra_only', 'postgres_only', and 'different' keys
        """
        if self.cassandra_data is None or self.postgres_data is None:
            return {"cassandra_only": {}, "postgres_only": {}, "different": {}}

        cass_keys = set(self.cassandra_data.keys())
        pg_keys = set(self.postgres_data.keys())

        cassandra_only = {
            k: self.cassandra_data[k]
            for k in cass_keys - pg_keys
        }

        postgres_only = {
            k: self.postgres_data[k]
            for k in pg_keys - cass_keys
        }

        different = {
            k: {
                "cassandra": self.cassandra_data[k],
                "postgres": self.postgres_data[k]
            }
            for k in cass_keys & pg_keys
            if self.cassandra_data[k] != self.postgres_data[k]
        }

        return {
            "cassandra_only": cassandra_only,
            "postgres_only": postgres_only,
            "different": different
        }

    def resolve(
        self,
        resolution_status: ResolutionStatus,
        resolution_notes: Optional[str] = None
    ) -> None:
        """Mark mismatch as resolved.

        Args:
            resolution_status: Resolution status to set
            resolution_notes: Optional notes about the resolution
        """
        self.resolution_status = resolution_status
        self.resolution_notes = resolution_notes
        self.resolved_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation of mismatch
        """
        return {
            "mismatch_id": str(self.mismatch_id),
            "job_id": str(self.job_id),
            "table_name": self.table_name,
            "primary_key_value": self.primary_key_value,
            "mismatch_type": self.mismatch_type.value,
            "cassandra_checksum": self.cassandra_checksum,
            "postgres_checksum": self.postgres_checksum,
            "cassandra_data": self.cassandra_data,
            "postgres_data": self.postgres_data,
            "detected_at": self.detected_at.isoformat(),
            "resolution_status": self.resolution_status.value,
            "resolution_notes": self.resolution_notes,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat(),
            "data_diff": self.get_data_diff()
        }
