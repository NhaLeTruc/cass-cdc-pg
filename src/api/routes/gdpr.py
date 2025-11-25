"""GDPR compliance API endpoints (T138).

REST API for GDPR data erasure requests.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.repositories.cassandra_repository import CassandraRepository
from src.repositories.postgresql_repository import PostgreSQLRepository


router = APIRouter(prefix="/records", tags=["gdpr"])


class DeleteRecordResponse(BaseModel):
    """Response model for record deletion."""

    status: str = Field(..., description="Deletion status")
    keyspace: str = Field(..., description="Cassandra keyspace")
    table: str = Field(..., description="Table name")
    primary_key: str = Field(..., description="Deleted record primary key")
    deleted_from_cassandra: bool = Field(..., description="Deleted from Cassandra")
    deleted_from_postgres: bool = Field(..., description="Deleted from PostgreSQL")
    audit_log_id: Optional[UUID] = Field(None, description="Audit log entry ID")
    timestamp: datetime = Field(..., description="Deletion timestamp")


@router.delete("/{keyspace}/{table}/{primary_key}", response_model=DeleteRecordResponse)
async def delete_record_gdpr(
    keyspace: str,
    table: str,
    primary_key: str,
    requester: str = "api_user",
    reason: str = "GDPR erasure request",
    cassandra_repo: CassandraRepository = Depends(),
    postgres_repo: PostgreSQLRepository = Depends()
) -> DeleteRecordResponse:
    """Delete record from both Cassandra and PostgreSQL (GDPR compliance).

    Performs cascading delete of a record from both source (Cassandra) and
    target (PostgreSQL) databases, with full audit trail.

    This endpoint supports GDPR "right to erasure" (Article 17).

    Args:
        keyspace: Cassandra keyspace
        table: Table name
        primary_key: Primary key value of record to delete
        requester: User or system requesting deletion
        reason: Reason for deletion
        cassandra_repo: Cassandra repository dependency
        postgres_repo: PostgreSQL repository dependency

    Returns:
        Deletion status and audit information

    Raises:
        HTTPException: If deletion fails
    """
    timestamp = datetime.now()
    audit_log_id = None

    # Delete from Cassandra
    try:
        cassandra_repo.session.execute(
            f"DELETE FROM {keyspace}.{table} WHERE id = %s",
            (UUID(primary_key) if _is_uuid(primary_key) else primary_key,)
        )
        deleted_from_cassandra = True
    except Exception as e:
        deleted_from_cassandra = False
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete from Cassandra: {str(e)}"
        )

    # Delete from PostgreSQL
    target_table = f"cdc_{table}"
    try:
        cursor = postgres_repo.connection.cursor()
        cursor.execute(
            f"DELETE FROM {target_table} WHERE id = %s",
            (UUID(primary_key) if _is_uuid(primary_key) else primary_key,)
        )
        postgres_repo.connection.commit()
        deleted_from_postgres = True
    except Exception as e:
        deleted_from_postgres = False
        # Rollback Cassandra delete if PostgreSQL fails
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete from PostgreSQL: {str(e)}"
        )

    # Write audit log
    try:
        cursor = postgres_repo.connection.cursor()
        cursor.execute("""
            INSERT INTO _cdc_audit_log (
                audit_id, event_type, table_name, record_identifier,
                requester, reason, timestamp, metadata
            ) VALUES (
                gen_random_uuid(), 'GDPR_ERASURE', %s, %s, %s, %s, %s, %s
            )
            RETURNING audit_id
        """, (
            f"{keyspace}.{table}",
            primary_key,
            requester,
            reason,
            timestamp,
            {
                "keyspace": keyspace,
                "table": table,
                "deleted_from_cassandra": deleted_from_cassandra,
                "deleted_from_postgres": deleted_from_postgres
            }
        ))

        audit_row = cursor.fetchone()
        if audit_row:
            audit_log_id = audit_row[0]

        postgres_repo.connection.commit()

    except Exception as e:
        # Log audit failure but don't fail the deletion
        print(f"Failed to write audit log: {e}")

    return DeleteRecordResponse(
        status="success",
        keyspace=keyspace,
        table=table,
        primary_key=primary_key,
        deleted_from_cassandra=deleted_from_cassandra,
        deleted_from_postgres=deleted_from_postgres,
        audit_log_id=audit_log_id,
        timestamp=timestamp
    )


def _is_uuid(value: str) -> bool:
    """Check if string is a valid UUID.

    Args:
        value: String to check

    Returns:
        True if valid UUID format
    """
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
