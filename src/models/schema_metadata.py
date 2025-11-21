from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class SchemaChangeType(str, Enum):
    """Type of schema change."""

    ADD_COLUMN = "ADD_COLUMN"
    DROP_COLUMN = "DROP_COLUMN"
    MODIFY_COLUMN = "MODIFY_COLUMN"
    ADD_TABLE = "ADD_TABLE"
    DROP_TABLE = "DROP_TABLE"
    INITIAL = "INITIAL"


class CompatibilityMode(str, Enum):
    """Schema Registry compatibility modes."""

    BACKWARD = "BACKWARD"
    FORWARD = "FORWARD"
    FULL = "FULL"
    NONE = "NONE"


class ColumnMetadata(BaseModel):
    """Metadata for a single column."""

    name: str = Field(..., description="Column name")
    cassandra_type: str = Field(..., description="Cassandra data type (e.g., 'text', 'uuid', 'int')")
    postgres_type: str = Field(..., description="Mapped PostgreSQL data type")
    is_nullable: bool = Field(default=True, description="Whether column allows NULL values")
    is_primary_key: bool = Field(default=False, description="Whether column is part of primary key")
    default_value: Optional[Any] = Field(default=None, description="Default value if any")


class SchemaMetadata(BaseModel):
    """
    Schema metadata model for tracking table schema versions.

    Stores schema information for both Cassandra source and PostgreSQL target,
    tracks schema evolution, and manages Avro schema registration.
    """

    schema_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this schema version",
    )

    source_table: str = Field(
        ...,
        description="Source Cassandra table name",
    )

    version: int = Field(
        ...,
        description="Schema version number (incremented on each change)",
        ge=1,
    )

    columns: List[ColumnMetadata] = Field(
        ...,
        description="List of column definitions",
    )

    primary_key: List[str] = Field(
        ...,
        description="List of column names forming the primary key",
    )

    avro_schema: Dict[str, Any] = Field(
        ...,
        description="Avro schema JSON for Schema Registry",
    )

    avro_schema_id: Optional[int] = Field(
        default=None,
        description="Schema Registry schema ID (NULL before registration)",
    )

    effective_from: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when this schema version became effective",
    )

    effective_to: Optional[datetime] = Field(
        default=None,
        description="Timestamp when this schema version was superseded (NULL for current)",
    )

    compatibility_mode: CompatibilityMode = Field(
        default=CompatibilityMode.BACKWARD,
        description="Schema Registry compatibility mode",
    )

    change_type: SchemaChangeType = Field(
        ...,
        description="Type of schema change that created this version",
    )

    @property
    def is_current(self) -> bool:
        """Check if this is the current active schema version."""
        return self.effective_to is None

    @property
    def column_names(self) -> List[str]:
        """Get list of all column names."""
        return [col.name for col in self.columns]

    @property
    def nullable_columns(self) -> List[str]:
        """Get list of nullable column names."""
        return [col.name for col in self.columns if col.is_nullable]

    @property
    def required_columns(self) -> List[str]:
        """Get list of required (non-nullable) column names."""
        return [col.name for col in self.columns if not col.is_nullable]

    def get_column(self, name: str) -> Optional[ColumnMetadata]:
        """Get column metadata by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def has_column(self, name: str) -> bool:
        """Check if schema has a column with given name."""
        return name in self.column_names

    def supersede(self) -> None:
        """Mark this schema version as superseded."""
        self.effective_to = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "schema_id": self.schema_id,
            "source_table": self.source_table,
            "version": self.version,
            "columns": [
                {
                    "name": col.name,
                    "cassandra_type": col.cassandra_type,
                    "postgres_type": col.postgres_type,
                    "is_nullable": col.is_nullable,
                    "is_primary_key": col.is_primary_key,
                    "default_value": col.default_value,
                }
                for col in self.columns
            ],
            "primary_key": self.primary_key,
            "avro_schema": self.avro_schema,
            "avro_schema_id": self.avro_schema_id,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "compatibility_mode": self.compatibility_mode.value,
            "change_type": self.change_type.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SchemaMetadata":
        """Create SchemaMetadata from dictionary (e.g., from database row)."""
        if "columns" in data and isinstance(data["columns"], list):
            data["columns"] = [
                ColumnMetadata(**col) if isinstance(col, dict) else col
                for col in data["columns"]
            ]

        if "compatibility_mode" in data and isinstance(data["compatibility_mode"], str):
            data["compatibility_mode"] = CompatibilityMode(data["compatibility_mode"])

        if "change_type" in data and isinstance(data["change_type"], str):
            data["change_type"] = SchemaChangeType(data["change_type"])

        return cls(**data)

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"SchemaMetadata(table={self.source_table}, "
            f"version={self.version}, "
            f"columns={len(self.columns)}, "
            f"current={self.is_current})"
        )

    class Config:
        """Pydantic configuration."""

        use_enum_values = False
        validate_assignment = True
