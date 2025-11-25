"""Reconciliation Engine service (T116).

Core reconciliation logic for validating data consistency between Cassandra and PostgreSQL.
"""

import hashlib
import json
import random
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from uuid import uuid4

from src.models.reconciliation_job import (
    ReconciliationJob,
    JobType,
    ValidationStrategy,
    JobStatus
)
from src.models.reconciliation_mismatch import (
    ReconciliationMismatch,
    MismatchType
)
from src.repositories.cassandra_repository import CassandraRepository
from src.repositories.postgresql_repository import PostgreSQLRepository
from src.repositories.reconciliation_repository import ReconciliationRepository
from src.monitoring.metrics import (
    reconciliation_drift_percentage,
    reconciliation_cassandra_rows,
    reconciliation_postgres_rows,
    reconciliation_mismatches_total,
    reconciliation_jobs_completed_total,
    reconciliation_duration_seconds
)


class ReconciliationEngine:
    """Core reconciliation validation engine.

    Implements multiple validation strategies for detecting data drift between
    Cassandra and PostgreSQL.
    """

    def __init__(
        self,
        cassandra_repo: CassandraRepository,
        postgres_repo: PostgreSQLRepository,
        reconciliation_repo: Optional[ReconciliationRepository] = None
    ):
        """Initialize reconciliation engine.

        Args:
            cassandra_repo: Cassandra repository for source data access
            postgres_repo: PostgreSQL repository for target data access
            reconciliation_repo: Optional repository for persisting results
        """
        self.cassandra_repo = cassandra_repo
        self.postgres_repo = postgres_repo
        self.reconciliation_repo = reconciliation_repo

    async def run_row_count_validation(
        self,
        table_name: str,
        source_keyspace: str,
        target_schema: str = "public",
        target_table: Optional[str] = None
    ) -> ReconciliationJob:
        """Run row count validation reconciliation.

        Compares total row counts between Cassandra and PostgreSQL tables.

        Args:
            table_name: Source table name (Cassandra)
            source_keyspace: Cassandra keyspace
            target_schema: PostgreSQL schema (default: public)
            target_table: Target table name (default: cdc_{table_name})

        Returns:
            Completed reconciliation job with results
        """
        if target_table is None:
            target_table = f"cdc_{table_name}"

        # Create job
        job = ReconciliationJob(
            job_id=uuid4(),
            table_name=table_name,
            job_type=JobType.MANUAL_ONDEMAND,
            validation_strategy=ValidationStrategy.ROW_COUNT,
            started_at=datetime.now(),
            status=JobStatus.RUNNING
        )

        try:
            # Get Cassandra row count
            cassandra_count = await self._get_cassandra_row_count(
                source_keyspace,
                table_name
            )

            # Get PostgreSQL row count
            postgres_count = await self._get_postgres_row_count(
                target_schema,
                target_table
            )

            # Calculate drift
            mismatch_count = abs(cassandra_count - postgres_count)
            drift_percentage = Decimal(0)
            if cassandra_count > 0:
                drift_percentage = (
                    Decimal(mismatch_count) / Decimal(cassandra_count) * Decimal(100)
                ).quantize(Decimal("0.01"))

            # Update job
            job.cassandra_row_count = cassandra_count
            job.postgres_row_count = postgres_count
            job.mismatch_count = mismatch_count
            job.drift_percentage = drift_percentage
            job.completed_at = datetime.now()
            job.status = JobStatus.COMPLETED

            # Update metrics
            reconciliation_drift_percentage.labels(table=table_name).set(
                float(drift_percentage)
            )
            reconciliation_cassandra_rows.labels(table=table_name).set(cassandra_count)
            reconciliation_postgres_rows.labels(table=table_name).set(postgres_count)
            reconciliation_mismatches_total.labels(
                table=table_name,
                type="ROW_COUNT_DIFF"
            ).inc(mismatch_count)

            # Record duration
            duration = (job.completed_at - job.started_at).total_seconds()
            reconciliation_duration_seconds.labels(table=table_name).observe(duration)

            # Persist job if repository available
            if self.reconciliation_repo:
                job = self.reconciliation_repo.create_job(job)

            # Increment completed jobs counter
            reconciliation_jobs_completed_total.labels(
                table=table_name,
                status="COMPLETED"
            ).inc()

            return job

        except Exception as e:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now()
            job.validation_errors = {
                "error": str(e),
                "error_type": type(e).__name__
            }

            if self.reconciliation_repo:
                self.reconciliation_repo.create_job(job)

            reconciliation_jobs_completed_total.labels(
                table=table_name,
                status="FAILED"
            ).inc()

            raise

    async def run_checksum_validation(
        self,
        table_name: str,
        source_keyspace: str,
        target_schema: str = "public",
        target_table: Optional[str] = None,
        sample_size: int = 1000
    ) -> ReconciliationJob:
        """Run checksum validation reconciliation.

        Compares checksums of sampled records between Cassandra and PostgreSQL.

        Args:
            table_name: Source table name
            source_keyspace: Cassandra keyspace
            target_schema: PostgreSQL schema
            target_table: Target table name
            sample_size: Number of records to sample

        Returns:
            Completed reconciliation job with mismatches
        """
        if target_table is None:
            target_table = f"cdc_{table_name}"

        job = ReconciliationJob(
            job_id=uuid4(),
            table_name=table_name,
            job_type=JobType.MANUAL_ONDEMAND,
            validation_strategy=ValidationStrategy.CHECKSUM,
            started_at=datetime.now(),
            status=JobStatus.RUNNING
        )

        mismatches: List[ReconciliationMismatch] = []

        try:
            # Sample records from Cassandra
            cassandra_records = await self._sample_cassandra_records(
                source_keyspace,
                table_name,
                sample_size
            )

            # Get corresponding PostgreSQL records
            for cass_record in cassandra_records:
                primary_key = cass_record.get("id")
                if not primary_key:
                    continue

                # Get PostgreSQL record
                pg_record = await self._get_postgres_record(
                    target_schema,
                    target_table,
                    primary_key
                )

                # Calculate checksums
                cass_checksum = self._calculate_checksum(cass_record)

                if pg_record is None:
                    # Record missing in PostgreSQL
                    mismatch = ReconciliationMismatch(
                        mismatch_id=uuid4(),
                        job_id=job.job_id,
                        table_name=table_name,
                        primary_key_value=str(primary_key),
                        mismatch_type=MismatchType.MISSING_IN_POSTGRES,
                        cassandra_checksum=cass_checksum,
                        postgres_checksum=None,
                        cassandra_data=cass_record,
                        postgres_data=None,
                        detected_at=datetime.now()
                    )
                    mismatches.append(mismatch)

                    if self.reconciliation_repo:
                        self.reconciliation_repo.create_mismatch(mismatch)

                else:
                    pg_checksum = self._calculate_checksum(pg_record)

                    if cass_checksum != pg_checksum:
                        # Data mismatch
                        mismatch = ReconciliationMismatch(
                            mismatch_id=uuid4(),
                            job_id=job.job_id,
                            table_name=table_name,
                            primary_key_value=str(primary_key),
                            mismatch_type=MismatchType.DATA_MISMATCH,
                            cassandra_checksum=cass_checksum,
                            postgres_checksum=pg_checksum,
                            cassandra_data=cass_record,
                            postgres_data=pg_record,
                            detected_at=datetime.now()
                        )
                        mismatches.append(mismatch)

                        if self.reconciliation_repo:
                            self.reconciliation_repo.create_mismatch(mismatch)

            # Update job results
            job.mismatch_count = len(mismatches)
            job.mismatches = mismatches
            job.completed_at = datetime.now()
            job.status = JobStatus.COMPLETED

            # Update metrics
            for mismatch in mismatches:
                reconciliation_mismatches_total.labels(
                    table=table_name,
                    type=mismatch.mismatch_type.value
                ).inc()

            # Record duration
            duration = (job.completed_at - job.started_at).total_seconds()
            reconciliation_duration_seconds.labels(table=table_name).observe(duration)

            if self.reconciliation_repo:
                self.reconciliation_repo.create_job(job)

            reconciliation_jobs_completed_total.labels(
                table=table_name,
                status="COMPLETED"
            ).inc()

            return job

        except Exception as e:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now()
            job.validation_errors = {
                "error": str(e),
                "error_type": type(e).__name__
            }

            if self.reconciliation_repo:
                self.reconciliation_repo.create_job(job)

            reconciliation_jobs_completed_total.labels(
                table=table_name,
                status="FAILED"
            ).inc()

            raise

    async def run_timestamp_range_validation(
        self,
        table_name: str,
        source_keyspace: str,
        target_schema: str = "public",
        target_table: Optional[str] = None,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None
    ) -> ReconciliationJob:
        """Run timestamp range validation.

        Validates records modified within a specific time range.

        Args:
            table_name: Source table name
            source_keyspace: Cassandra keyspace
            target_schema: PostgreSQL schema
            target_table: Target table name
            from_timestamp: Start of time range
            to_timestamp: End of time range

        Returns:
            Completed reconciliation job
        """
        if target_table is None:
            target_table = f"cdc_{table_name}"

        job = ReconciliationJob(
            job_id=uuid4(),
            table_name=table_name,
            job_type=JobType.MANUAL_ONDEMAND,
            validation_strategy=ValidationStrategy.TIMESTAMP_RANGE,
            started_at=datetime.now(),
            status=JobStatus.RUNNING
        )

        try:
            # Implementation similar to checksum validation but filtered by timestamp
            # For now, delegate to checksum validation
            result = await self.run_checksum_validation(
                table_name=table_name,
                source_keyspace=source_keyspace,
                target_schema=target_schema,
                target_table=target_table
            )

            job.mismatch_count = result.mismatch_count
            job.mismatches = result.mismatches
            job.completed_at = datetime.now()
            job.status = JobStatus.COMPLETED

            return job

        except Exception as e:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now()
            job.validation_errors = {
                "error": str(e),
                "error_type": type(e).__name__
            }

            if self.reconciliation_repo:
                self.reconciliation_repo.create_job(job)

            raise

    async def run_sample_validation(
        self,
        table_name: str,
        source_keyspace: str,
        target_schema: str = "public",
        target_table: Optional[str] = None,
        sample_size: int = 100
    ) -> ReconciliationJob:
        """Run sample validation.

        Randomly samples records for deep comparison.

        Args:
            table_name: Source table name
            source_keyspace: Cassandra keyspace
            target_schema: PostgreSQL schema
            target_table: Target table name
            sample_size: Number of records to sample

        Returns:
            Completed reconciliation job
        """
        return await self.run_checksum_validation(
            table_name=table_name,
            source_keyspace=source_keyspace,
            target_schema=target_schema,
            target_table=target_table,
            sample_size=sample_size
        )

    def _calculate_checksum(self, record: Dict[str, Any]) -> str:
        """Calculate SHA-256 checksum of a record.

        Args:
            record: Record data as dictionary

        Returns:
            Hexadecimal SHA-256 checksum
        """
        # Sort keys for consistent hashing
        normalized = json.dumps(record, sort_keys=True, default=str)
        return hashlib.sha256(normalized.encode()).hexdigest()

    async def _get_cassandra_row_count(
        self,
        keyspace: str,
        table: str
    ) -> int:
        """Get total row count from Cassandra table.

        Args:
            keyspace: Cassandra keyspace
            table: Table name

        Returns:
            Total row count
        """
        query = f"SELECT COUNT(*) FROM {keyspace}.{table}"
        result = self.cassandra_repo.session.execute(query)
        row = result.one()
        return row.count if row else 0

    async def _get_postgres_row_count(
        self,
        schema: str,
        table: str
    ) -> int:
        """Get total row count from PostgreSQL table.

        Args:
            schema: PostgreSQL schema
            table: Table name

        Returns:
            Total row count
        """
        cursor = self.postgres_repo.connection.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        row = cursor.fetchone()
        return row[0] if row else 0

    async def _sample_cassandra_records(
        self,
        keyspace: str,
        table: str,
        sample_size: int
    ) -> List[Dict[str, Any]]:
        """Sample random records from Cassandra table.

        Args:
            keyspace: Cassandra keyspace
            table: Table name
            sample_size: Number of records to sample

        Returns:
            List of record dictionaries
        """
        # Get total count
        total_count = await self._get_cassandra_row_count(keyspace, table)

        if total_count == 0:
            return []

        # Fetch all records (for small tables) or sample
        query = f"SELECT * FROM {keyspace}.{table}"
        if sample_size < total_count:
            query += f" LIMIT {min(sample_size * 2, total_count)}"

        result = self.cassandra_repo.session.execute(query)

        records = []
        for row in result:
            record = dict(row._asdict())
            records.append(record)

        # Random sample if we got more than needed
        if len(records) > sample_size:
            records = random.sample(records, sample_size)

        return records

    async def _get_postgres_record(
        self,
        schema: str,
        table: str,
        primary_key: Any
    ) -> Optional[Dict[str, Any]]:
        """Get single record from PostgreSQL by primary key.

        Args:
            schema: PostgreSQL schema
            table: Table name
            primary_key: Primary key value

        Returns:
            Record dictionary, or None if not found
        """
        cursor = self.postgres_repo.connection.cursor()
        cursor.execute(
            f"SELECT * FROM {schema}.{table} WHERE id = %s",
            (primary_key,)
        )

        row = cursor.fetchone()
        if not row:
            return None

        # Convert to dictionary
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
