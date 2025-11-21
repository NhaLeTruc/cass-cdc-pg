"""Data model for Dead Letter Queue records."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import uuid


class ErrorType(Enum):
    """Enumeration of error types for DLQ records."""

    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    TYPE_CONVERSION_ERROR = "TYPE_CONVERSION_ERROR"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    UNKNOWN = "UNKNOWN"


class ResolutionStatus(Enum):
    """Status of DLQ record resolution."""

    PENDING = "PENDING"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    MANUAL_RESOLVED = "MANUAL_RESOLVED"
    IGNORED = "IGNORED"


@dataclass
class DLQRecord:
    """
    Model representing a Dead Letter Queue record.

    Attributes:
        dlq_id: Unique identifier for the DLQ record
        source_table: Name of the source table where the event originated
        original_event: Original event data that failed processing
        error_type: Type of error encountered
        error_message: Human-readable error message
        error_stack_trace: Full stack trace of the error
        retry_count: Number of times processing was retried
        first_failed_at: Timestamp when the event first failed
        last_retry_at: Timestamp of the last retry attempt
        dlq_timestamp: Timestamp when the record was added to DLQ
        source_component: Component that generated the error
        resolution_status: Current status of the DLQ record
        resolution_notes: Notes about resolution (if resolved)
        resolved_at: Timestamp when the record was resolved
    """

    dlq_id: uuid.UUID
    source_table: str
    original_event: Dict[str, Any]
    error_type: ErrorType
    error_message: str
    dlq_timestamp: datetime
    source_component: str = "kafka-connect"
    error_stack_trace: Optional[str] = None
    retry_count: int = 0
    first_failed_at: Optional[datetime] = None
    last_retry_at: Optional[datetime] = None
    resolution_status: ResolutionStatus = ResolutionStatus.PENDING
    resolution_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert DLQRecord to dictionary representation.

        Returns:
            Dictionary with all DLQ record fields
        """
        return {
            "dlq_id": str(self.dlq_id),
            "source_table": self.source_table,
            "original_event": self.original_event,
            "error_type": self.error_type.value,
            "error_message": self.error_message,
            "error_stack_trace": self.error_stack_trace,
            "retry_count": self.retry_count,
            "first_failed_at": self.first_failed_at.isoformat() if self.first_failed_at else None,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "dlq_timestamp": self.dlq_timestamp.isoformat(),
            "source_component": self.source_component,
            "resolution_status": self.resolution_status.value,
            "resolution_notes": self.resolution_notes,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DLQRecord":
        """
        Create DLQRecord from dictionary.

        Args:
            data: Dictionary with DLQ record data

        Returns:
            DLQRecord instance
        """
        return cls(
            dlq_id=uuid.UUID(data["dlq_id"]) if isinstance(data["dlq_id"], str) else data["dlq_id"],
            source_table=data["source_table"],
            original_event=data["original_event"],
            error_type=ErrorType(data["error_type"]) if isinstance(data["error_type"], str) else data["error_type"],
            error_message=data["error_message"],
            error_stack_trace=data.get("error_stack_trace"),
            retry_count=data.get("retry_count", 0),
            first_failed_at=datetime.fromisoformat(data["first_failed_at"]) if data.get("first_failed_at") else None,
            last_retry_at=datetime.fromisoformat(data["last_retry_at"]) if data.get("last_retry_at") else None,
            dlq_timestamp=datetime.fromisoformat(data["dlq_timestamp"]) if isinstance(data["dlq_timestamp"], str) else data["dlq_timestamp"],
            source_component=data.get("source_component", "kafka-connect"),
            resolution_status=ResolutionStatus(data.get("resolution_status", "PENDING")) if isinstance(data.get("resolution_status"), str) else data.get("resolution_status", ResolutionStatus.PENDING),
            resolution_notes=data.get("resolution_notes"),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None,
        )

    def is_resolved(self) -> bool:
        """
        Check if the DLQ record has been resolved.

        Returns:
            True if resolved, False otherwise
        """
        return self.resolution_status in [
            ResolutionStatus.AUTO_RESOLVED,
            ResolutionStatus.MANUAL_RESOLVED,
            ResolutionStatus.IGNORED,
        ]

    def mark_resolved(
        self,
        status: ResolutionStatus,
        notes: Optional[str] = None,
    ) -> None:
        """
        Mark the DLQ record as resolved.

        Args:
            status: Resolution status (AUTO_RESOLVED or MANUAL_RESOLVED)
            notes: Optional resolution notes
        """
        self.resolution_status = status
        self.resolution_notes = notes
        self.resolved_at = datetime.utcnow()

    def increment_retry_count(self) -> None:
        """Increment the retry count and update last_retry_at."""
        self.retry_count += 1
        self.last_retry_at = datetime.utcnow()
        if self.first_failed_at is None:
            self.first_failed_at = datetime.utcnow()
