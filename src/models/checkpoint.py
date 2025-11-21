from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class CheckpointStatus(str, Enum):
    """Checkpoint processing status."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Checkpoint(BaseModel):
    """
    Checkpoint model for tracking CDC processing progress.

    Used to resume processing after failures and prevent duplicate processing.
    Stored in PostgreSQL _cdc_checkpoints table.
    """

    checkpoint_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this checkpoint",
    )

    source_table: str = Field(
        ...,
        description="Source Cassandra table name",
    )

    partition_key_hash: Optional[str] = Field(
        default=None,
        description="Hash of partition key for sharding (NULL for global checkpoints)",
    )

    last_processed_event_id: str = Field(
        ...,
        description="Event ID of the last successfully processed event",
    )

    last_processed_timestamp_micros: int = Field(
        ...,
        description="Timestamp (microseconds) of the last processed event",
        gt=0,
    )

    checkpoint_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this checkpoint was created",
    )

    kafka_offset: int = Field(
        ...,
        description="Kafka consumer offset for this partition",
        ge=0,
    )

    kafka_partition: int = Field(
        ...,
        description="Kafka partition number",
        ge=0,
    )

    status: CheckpointStatus = Field(
        default=CheckpointStatus.COMPLETED,
        description="Processing status of this checkpoint",
    )

    @property
    def last_processed_datetime(self) -> datetime:
        """Convert last_processed_timestamp_micros to datetime."""
        return datetime.fromtimestamp(self.last_processed_timestamp_micros / 1_000_000)

    def mark_processing(self) -> None:
        """Mark checkpoint as being processed."""
        self.status = CheckpointStatus.PROCESSING

    def mark_completed(self) -> None:
        """Mark checkpoint as successfully completed."""
        self.status = CheckpointStatus.COMPLETED
        self.checkpoint_timestamp = datetime.utcnow()

    def mark_failed(self) -> None:
        """Mark checkpoint as failed."""
        self.status = CheckpointStatus.FAILED

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "source_table": self.source_table,
            "partition_key_hash": self.partition_key_hash,
            "last_processed_event_id": self.last_processed_event_id,
            "last_processed_timestamp_micros": self.last_processed_timestamp_micros,
            "checkpoint_timestamp": self.checkpoint_timestamp,
            "kafka_offset": self.kafka_offset,
            "kafka_partition": self.kafka_partition,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        """Create Checkpoint from dictionary (e.g., from database row)."""
        if "status" in data and isinstance(data["status"], str):
            data["status"] = CheckpointStatus(data["status"])
        return cls(**data)

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"Checkpoint(table={self.source_table}, "
            f"partition={self.kafka_partition}, "
            f"offset={self.kafka_offset}, "
            f"status={self.status.value})"
        )

    class Config:
        """Pydantic configuration."""

        use_enum_values = False
        validate_assignment = True
