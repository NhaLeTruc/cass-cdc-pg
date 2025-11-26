"""GDPR compliance API endpoints (T138).

REST API for GDPR data erasure requests.
"""

import logging
import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.repositories.cassandra_repository import CassandraRepository
from src.repositories.postgresql_repository import PostgreSQLRepository

logger = logging.getLogger(__name__)


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
    # Validate identifiers to prevent SQL injection
    validated_keyspace = _validate_identifier(keyspace, "keyspace")
    validated_table = _validate_identifier(table, "table")

    timestamp = datetime.now()
    audit_log_id = None
    deleted_from_cassandra = False
    deleted_from_postgres = False

    # Backup the record before deletion (for compensating transaction)
    cassandra_backup = None
    postgres_backup = None

    # Start transaction-like operation with compensating transaction support
    try:
        # Step 1: Backup Cassandra record before deletion
        try:
            result = cassandra_repo.session.execute(
                f"SELECT * FROM {validated_keyspace}.{validated_table} WHERE id = %s",
                (UUID(primary_key) if _is_uuid(primary_key) else primary_key,)
            )
            cassandra_backup = result.one()
            if not cassandra_backup:
                raise HTTPException(
                    status_code=404,
                    detail=f"Record {primary_key} not found in Cassandra {validated_keyspace}.{validated_table}"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to read Cassandra record for backup: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read record from Cassandra: {str(e)}"
            )

        # Step 2: Delete from Cassandra
        try:
            cassandra_repo.session.execute(
                f"DELETE FROM {validated_keyspace}.{validated_table} WHERE id = %s",
                (UUID(primary_key) if _is_uuid(primary_key) else primary_key,)
            )
            deleted_from_cassandra = True
            logger.info(f"Deleted record {primary_key} from Cassandra {validated_keyspace}.{validated_table}")
        except Exception as e:
            logger.error(f"Failed to delete from Cassandra: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete from Cassandra: {str(e)}"
            )

        # Step 3: Delete from PostgreSQL (with compensating transaction on failure)
        validated_target_table = _validate_identifier(f"cdc_{validated_table}", "target table")
        try:
            cursor = postgres_repo.connection.cursor()
            cursor.execute(
                f"DELETE FROM {validated_target_table} WHERE id = %s",
                (UUID(primary_key) if _is_uuid(primary_key) else primary_key,)
            )
            postgres_repo.connection.commit()
            deleted_from_postgres = True
            logger.info(f"Deleted record {primary_key} from PostgreSQL {validated_target_table}")
        except Exception as e:
            logger.error(f"Failed to delete from PostgreSQL: {e}")

            # Compensating transaction: Restore Cassandra record
            if deleted_from_cassandra and cassandra_backup:
                try:
                    # Build INSERT statement from backup data
                    columns = cassandra_backup._fields
                    placeholders = ', '.join(['%s'] * len(columns))
                    column_names = ', '.join(columns)
                    values = tuple(getattr(cassandra_backup, col) for col in columns)

                    cassandra_repo.session.execute(
                        f"INSERT INTO {validated_keyspace}.{validated_table} ({column_names}) VALUES ({placeholders})",
                        values
                    )
                    logger.warning(
                        f"Compensating transaction: Restored record {primary_key} to Cassandra after PostgreSQL deletion failed"
                    )
                    deleted_from_cassandra = False  # Reset flag since we restored
                except Exception as restore_error:
                    logger.critical(
                        f"CRITICAL: Failed to restore Cassandra record {primary_key} after PostgreSQL deletion failed. "
                        f"Manual intervention required. Error: {restore_error}"
                    )

            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete from PostgreSQL: {str(e)}. Attempted compensating transaction."
            )

        # Write audit log
        try:
            cursor = postgres_repo.connection.cursor()
            cursor.execute("""
                INSERT INTO _cdc_audit_log (
                    audit_id, event_type, table_name, record_identifier,
                    requester, reason, timestamp, metadata
                ) VALUES (
                    gen_random_uuid(), 'GDPR_ERASURE', %s, %s, %s, %s, %s, %s::jsonb
                )
                RETURNING audit_id
            """, (
                f"{validated_keyspace}.{validated_table}",
                primary_key,
                requester,
                reason,
                timestamp,
                str({
                    "keyspace": validated_keyspace,
                    "table": validated_table,
                    "deleted_from_cassandra": deleted_from_cassandra,
                    "deleted_from_postgres": deleted_from_postgres
                })
            ))

            audit_row = cursor.fetchone()
            if audit_row:
                audit_log_id = audit_row[0]

            postgres_repo.connection.commit()
            logger.info(f"GDPR deletion audit logged: {audit_log_id}")

        except Exception as e:
            # Log audit failure but don't fail the deletion
            logger.error(f"Failed to write audit log: {e}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during GDPR deletion: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during deletion: {str(e)}"
        )

    return DeleteRecordResponse(
        status="success",
        keyspace=validated_keyspace,
        table=validated_table,
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


def _validate_identifier(identifier: str, identifier_type: str = "identifier") -> str:
    """Validate and sanitize SQL identifiers to prevent SQL injection.

    Args:
        identifier: The identifier to validate (keyspace, table name, etc.)
        identifier_type: Type of identifier for error messages

    Returns:
        The validated identifier

    Raises:
        HTTPException: If identifier contains invalid characters
    """
    # Allow only alphanumeric characters and underscores
    if not re.match(r'^[a-zA-Z0-9_]+$', identifier):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {identifier_type}: must contain only alphanumeric characters and underscores"
        )
    return identifier
