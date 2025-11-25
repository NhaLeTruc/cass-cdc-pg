"""Reconciliation Repository (T115).

Repository for accessing reconciliation jobs and mismatches in PostgreSQL.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

import psycopg2
from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor

from src.models.reconciliation_job import (
    ReconciliationJob,
    JobType,
    ValidationStrategy,
    JobStatus
)
from src.models.reconciliation_mismatch import (
    ReconciliationMismatch,
    MismatchType,
    ResolutionStatus
)
from src.repositories.base import AbstractRepository


class ReconciliationRepository(AbstractRepository):
    """Repository for reconciliation data access.

    Handles CRUD operations for reconciliation jobs and mismatches in PostgreSQL.
    """

    def __init__(self, connection: Connection):
        """Initialize repository.

        Args:
            connection: PostgreSQL database connection
        """
        self.connection = connection

    def health_check(self) -> bool:
        """Check if repository is healthy.

        Returns:
            True if connection is alive
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return True
        except Exception:
            return False

    def create_job(self, job: ReconciliationJob) -> ReconciliationJob:
        """Create new reconciliation job.

        Args:
            job: Reconciliation job to create

        Returns:
            Created job with database-generated fields
        """
        cursor = self.connection.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            INSERT INTO _cdc_reconciliation_jobs (
                job_id, table_name, job_type, validation_strategy,
                started_at, completed_at, status,
                cassandra_row_count, postgres_row_count, mismatch_count,
                drift_percentage, validation_errors, alert_fired
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
        """, (
            job.job_id,
            job.table_name,
            job.job_type.value,
            job.validation_strategy.value,
            job.started_at,
            job.completed_at,
            job.status.value,
            job.cassandra_row_count,
            job.postgres_row_count,
            job.mismatch_count,
            job.drift_percentage,
            psycopg2.extras.Json(job.validation_errors) if job.validation_errors else None,
            job.alert_fired
        ))

        row = cursor.fetchone()
        self.connection.commit()

        return ReconciliationJob(**row)

    def update_job(
        self,
        job_id: UUID,
        **updates
    ) -> Optional[ReconciliationJob]:
        """Update reconciliation job.

        Args:
            job_id: Job ID to update
            **updates: Fields to update

        Returns:
            Updated job, or None if not found
        """
        if not updates:
            return self.get_job(job_id)

        # Build SET clause dynamically
        set_clauses = []
        values = []

        for key, value in updates.items():
            set_clauses.append(f"{key} = %s")
            # Handle enums and special types
            if isinstance(value, (JobType, ValidationStrategy, JobStatus)):
                values.append(value.value)
            elif key == "validation_errors" and value is not None:
                values.append(psycopg2.extras.Json(value))
            else:
                values.append(value)

        values.append(job_id)

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(f"""
            UPDATE _cdc_reconciliation_jobs
            SET {', '.join(set_clauses)}
            WHERE job_id = %s
            RETURNING *
        """, values)

        row = cursor.fetchone()
        self.connection.commit()

        return ReconciliationJob(**row) if row else None

    def get_job(self, job_id: UUID) -> Optional[ReconciliationJob]:
        """Get reconciliation job by ID.

        Args:
            job_id: Job ID to retrieve

        Returns:
            Job if found, None otherwise
        """
        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT * FROM _cdc_reconciliation_jobs
            WHERE job_id = %s
        """, (job_id,))

        row = cursor.fetchone()

        if not row:
            return None

        # Load mismatches
        job = ReconciliationJob(**row)
        job.mismatches = self.list_mismatches(job_id=job_id)

        return job

    def list_jobs(
        self,
        table_name: Optional[str] = None,
        job_type: Optional[JobType] = None,
        status: Optional[JobStatus] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ReconciliationJob]:
        """List reconciliation jobs with filters.

        Args:
            table_name: Filter by table name
            job_type: Filter by job type
            status: Filter by job status
            from_date: Filter by started_at >= from_date
            to_date: Filter by started_at <= to_date
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of matching jobs
        """
        conditions = []
        values = []

        if table_name:
            conditions.append("table_name = %s")
            values.append(table_name)

        if job_type:
            conditions.append("job_type = %s")
            values.append(job_type.value)

        if status:
            conditions.append("status = %s")
            values.append(status.value)

        if from_date:
            conditions.append("started_at >= %s")
            values.append(from_date)

        if to_date:
            conditions.append("started_at <= %s")
            values.append(to_date)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(f"""
            SELECT * FROM _cdc_reconciliation_jobs
            {where_clause}
            ORDER BY started_at DESC
            LIMIT %s OFFSET %s
        """, values + [limit, offset])

        rows = cursor.fetchall()

        return [ReconciliationJob(**row) for row in rows]

    def create_mismatch(
        self,
        mismatch: ReconciliationMismatch
    ) -> ReconciliationMismatch:
        """Create new reconciliation mismatch.

        Args:
            mismatch: Mismatch to create

        Returns:
            Created mismatch with database-generated fields
        """
        cursor = self.connection.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            INSERT INTO _cdc_reconciliation_mismatches (
                mismatch_id, job_id, table_name, primary_key_value,
                mismatch_type, cassandra_checksum, postgres_checksum,
                cassandra_data, postgres_data, detected_at,
                resolution_status, resolution_notes, resolved_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
        """, (
            mismatch.mismatch_id,
            mismatch.job_id,
            mismatch.table_name,
            mismatch.primary_key_value,
            mismatch.mismatch_type.value,
            mismatch.cassandra_checksum,
            mismatch.postgres_checksum,
            psycopg2.extras.Json(mismatch.cassandra_data) if mismatch.cassandra_data else None,
            psycopg2.extras.Json(mismatch.postgres_data) if mismatch.postgres_data else None,
            mismatch.detected_at,
            mismatch.resolution_status.value,
            mismatch.resolution_notes,
            mismatch.resolved_at
        ))

        row = cursor.fetchone()
        self.connection.commit()

        return ReconciliationMismatch(**row)

    def list_mismatches(
        self,
        job_id: Optional[UUID] = None,
        table_name: Optional[str] = None,
        mismatch_type: Optional[MismatchType] = None,
        resolution_status: Optional[ResolutionStatus] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[ReconciliationMismatch]:
        """List reconciliation mismatches with filters.

        Args:
            job_id: Filter by job ID
            table_name: Filter by table name
            mismatch_type: Filter by mismatch type
            resolution_status: Filter by resolution status
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of matching mismatches
        """
        conditions = []
        values = []

        if job_id:
            conditions.append("job_id = %s")
            values.append(job_id)

        if table_name:
            conditions.append("table_name = %s")
            values.append(table_name)

        if mismatch_type:
            conditions.append("mismatch_type = %s")
            values.append(mismatch_type.value)

        if resolution_status:
            conditions.append("resolution_status = %s")
            values.append(resolution_status.value)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(f"""
            SELECT * FROM _cdc_reconciliation_mismatches
            {where_clause}
            ORDER BY detected_at DESC
            LIMIT %s OFFSET %s
        """, values + [limit, offset])

        rows = cursor.fetchall()

        return [ReconciliationMismatch(**row) for row in rows]

    def resolve_mismatch(
        self,
        mismatch_id: UUID,
        resolution_status: ResolutionStatus,
        resolution_notes: Optional[str] = None
    ) -> Optional[ReconciliationMismatch]:
        """Mark mismatch as resolved.

        Args:
            mismatch_id: Mismatch ID to resolve
            resolution_status: Resolution status to set
            resolution_notes: Optional resolution notes

        Returns:
            Updated mismatch, or None if not found
        """
        cursor = self.connection.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            UPDATE _cdc_reconciliation_mismatches
            SET resolution_status = %s,
                resolution_notes = %s,
                resolved_at = %s
            WHERE mismatch_id = %s
            RETURNING *
        """, (
            resolution_status.value,
            resolution_notes,
            datetime.now(),
            mismatch_id
        ))

        row = cursor.fetchone()
        self.connection.commit()

        return ReconciliationMismatch(**row) if row else None

    def get_job_statistics(
        self,
        table_name: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> dict:
        """Get reconciliation job statistics.

        Args:
            table_name: Filter by table name
            from_date: Filter by started_at >= from_date
            to_date: Filter by started_at <= to_date

        Returns:
            Dictionary with statistics (total_jobs, avg_drift, max_drift, etc.)
        """
        conditions = []
        values = []

        if table_name:
            conditions.append("table_name = %s")
            values.append(table_name)

        if from_date:
            conditions.append("started_at >= %s")
            values.append(from_date)

        if to_date:
            conditions.append("started_at <= %s")
            values.append(to_date)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute(f"""
            SELECT
                COUNT(*) as total_jobs,
                AVG(drift_percentage) as avg_drift,
                MAX(drift_percentage) as max_drift,
                SUM(mismatch_count) as total_mismatches,
                SUM(CASE WHEN alert_fired THEN 1 ELSE 0 END) as alerts_fired
            FROM _cdc_reconciliation_jobs
            {where_clause}
        """, values)

        row = cursor.fetchone()

        return dict(row) if row else {}
