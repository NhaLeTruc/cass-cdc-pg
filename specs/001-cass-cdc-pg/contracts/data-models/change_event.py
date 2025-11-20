"""
Pydantic data models for CDC pipeline core entities.
These models provide type-safe validation, JSON serialization, and OpenAPI schema generation.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OperationType(str, Enum):
    """CDC operation types"""
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class KafkaMetadata(BaseModel):
    """Kafka message metadata"""
    topic: str = Field(..., description="Kafka topic name")
    partition: int = Field(..., ge=0, description="Kafka partition number")
    offset: int = Field(..., ge=0, description="Kafka message offset")
    timestamp: int = Field(..., description="Kafka message timestamp (milliseconds since epoch)")
    key: Optional[str] = Field(None, description="Kafka message key")
    headers: Optional[Dict[str, str]] = Field(None, description="Kafka message headers")


class ChangeEvent(BaseModel):
    """
    Represents a single data change captured from Cassandra.

    Validation rules:
    - For INSERT: before_data must be None, after_data must be non-empty
    - For UPDATE: Both before_data and after_data must be non-empty
    - For DELETE: before_data must be non-empty, after_data must be None
    """
    event_id: UUID = Field(..., description="Unique identifier for this event")
    source_table: str = Field(..., description="Fully qualified table name (keyspace.table)")
    operation: OperationType = Field(..., description="Operation type")
    primary_key: Dict[str, Any] = Field(..., description="Cassandra primary key columns and values")
    before_data: Optional[Dict[str, Any]] = Field(None, description="Column values before change (null for INSERT)")
    after_data: Optional[Dict[str, Any]] = Field(None, description="Column values after change (null for DELETE)")
    timestamp: int = Field(..., description="Cassandra write timestamp (microseconds since epoch)")
    cassandra_node: str = Field(..., description="Cassandra node hostname")
    kafka_metadata: KafkaMetadata = Field(..., description="Kafka topic, partition, offset information")
    schema_version: int = Field(..., ge=1, description="Schema version number")
    trace_id: str = Field(..., description="Distributed tracing correlation ID")

    @field_validator("source_table")
    @classmethod
    def validate_table_name(cls, v: str) -> str:
        """Ensure table name is in keyspace.table format"""
        if "." not in v:
            raise ValueError("source_table must be in format 'keyspace.table'")
        parts = v.split(".")
        if len(parts) != 2 or not all(parts):
            raise ValueError("source_table must have exactly one keyspace and one table name")
        return v

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure primary key is non-empty"""
        if not v:
            raise ValueError("primary_key cannot be empty")
        return v

    def validate_operation_data_consistency(self) -> None:
        """
        Validate that before_data and after_data align with operation type.
        Should be called after model instantiation.
        """
        if self.operation == OperationType.INSERT:
            if self.before_data is not None:
                raise ValueError("INSERT operation must have before_data=None")
            if not self.after_data:
                raise ValueError("INSERT operation must have non-empty after_data")
        elif self.operation == OperationType.UPDATE:
            if not self.before_data:
                raise ValueError("UPDATE operation must have non-empty before_data")
            if not self.after_data:
                raise ValueError("UPDATE operation must have non-empty after_data")
        elif self.operation == OperationType.DELETE:
            if not self.before_data:
                raise ValueError("DELETE operation must have non-empty before_data")
            if self.after_data is not None:
                raise ValueError("DELETE operation must have after_data=None")

    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
                "source_table": "prod_keyspace.users",
                "operation": "UPDATE",
                "primary_key": {"user_id": "e5f6g7h8-9012-34ij-klmn-5678901234op"},
                "before_data": {"email": "old@example.com", "name": "John Doe", "age": 29},
                "after_data": {"email": "new@example.com", "name": "John Doe", "age": 30},
                "timestamp": 1700500000123456,
                "cassandra_node": "cass-node-01.example.com",
                "kafka_metadata": {
                    "topic": "cassandra.prod_keyspace.users",
                    "partition": 3,
                    "offset": 123456,
                    "timestamp": 1700500000500,
                    "key": "user-12345",
                    "headers": {"trace_id": "trace-abc123", "schema_version": "2"}
                },
                "schema_version": 2,
                "trace_id": "trace-abc123xyz"
            }
        }


# Example usage:
# event = ChangeEvent(**json_data)
# event.validate_operation_data_consistency()  # Raises ValueError if inconsistent
# event_json = event.model_dump_json()  # Serialize to JSON
