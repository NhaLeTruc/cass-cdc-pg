from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import uuid


class OperationType(str, Enum):
    """CDC operation types."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    TRUNCATE = "TRUNCATE"


class ChangeEvent(BaseModel):
    """
    Change Data Capture event model.

    Represents a single change event captured from Cassandra and published to Kafka.
    Follows the schema contract defined in contracts/kafka-topics.md.
    """

    event_id: str = Field(
        ...,
        description="Unique identifier for this change event (UUID format)",
    )

    source_table: str = Field(
        ...,
        description="Source Cassandra table name (e.g., 'users', 'orders')",
    )

    operation_type: OperationType = Field(
        ...,
        description="Type of operation: CREATE, UPDATE, DELETE, or TRUNCATE",
    )

    timestamp_micros: int = Field(
        ...,
        description="Event timestamp in microseconds since Unix epoch for ordering and conflict resolution",
        gt=0,
    )

    before: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Row data before the change (NULL for CREATE, populated for UPDATE/DELETE)",
    )

    after: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Row data after the change (NULL for DELETE, populated for CREATE/UPDATE)",
    )

    schema_version: int = Field(
        ...,
        description="Schema version number for tracking schema evolution",
        ge=1,
    )

    ttl_seconds: Optional[int] = Field(
        default=None,
        description="Cassandra TTL in seconds if set, NULL otherwise",
        ge=0,
    )

    is_tombstone: bool = Field(
        default=False,
        description="True if this is a DELETE event with no data (tombstone)",
    )

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, v: str) -> str:
        """Validate that event_id is a valid UUID string."""
        try:
            uuid.UUID(v)
        except ValueError as e:
            raise ValueError(f"event_id must be a valid UUID string: {e}")
        return v

    @field_validator("operation_type")
    @classmethod
    def validate_operation_consistency(cls, v: OperationType) -> OperationType:
        """Validate operation type is a valid enum value."""
        if v not in OperationType:
            raise ValueError(
                f"operation_type must be one of {[op.value for op in OperationType]}"
            )
        return v

    def model_post_init(self, __context: Any) -> None:
        """Validate business rules after model initialization."""
        if self.operation_type == OperationType.CREATE:
            if self.after is None:
                raise ValueError("CREATE operation must have 'after' data")
            if self.before is not None:
                raise ValueError("CREATE operation should not have 'before' data")

        elif self.operation_type == OperationType.UPDATE:
            if self.after is None:
                raise ValueError("UPDATE operation must have 'after' data")
            if self.before is None:
                raise ValueError("UPDATE operation must have 'before' data")

        elif self.operation_type == OperationType.DELETE:
            if self.before is None:
                raise ValueError("DELETE operation must have 'before' data")
            if self.after is not None and not self.is_tombstone:
                raise ValueError(
                    "DELETE operation should not have 'after' data unless tombstone"
                )

        elif self.operation_type == OperationType.TRUNCATE:
            if self.before is not None or self.after is not None:
                raise ValueError("TRUNCATE operation should not have 'before' or 'after' data")

    @property
    def primary_key(self) -> Optional[Dict[str, Any]]:
        """Extract primary key from the event."""
        if self.after:
            return {"id": self.after.get("id")}
        elif self.before:
            return {"id": self.before.get("id")}
        return None

    @property
    def event_datetime(self) -> datetime:
        """Convert timestamp_micros to datetime object."""
        return datetime.fromtimestamp(self.timestamp_micros / 1_000_000)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization to Kafka."""
        return {
            "event_id": self.event_id,
            "source_table": self.source_table,
            "operation_type": self.operation_type.value,
            "timestamp_micros": self.timestamp_micros,
            "before": self.before,
            "after": self.after,
            "schema_version": self.schema_version,
            "ttl_seconds": self.ttl_seconds,
            "is_tombstone": self.is_tombstone,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChangeEvent":
        """Create ChangeEvent from dictionary (e.g., from Kafka message)."""
        return cls(**data)

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"ChangeEvent(event_id={self.event_id}, "
            f"table={self.source_table}, "
            f"operation={self.operation_type.value}, "
            f"timestamp={self.event_datetime.isoformat()})"
        )

    class Config:
        """Pydantic configuration."""

        use_enum_values = False
        validate_assignment = True
        arbitrary_types_allowed = True
