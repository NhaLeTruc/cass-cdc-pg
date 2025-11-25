"""Integration test for hourly scheduled reconciliation (T110).

Tests the reconciliation scheduler's ability to trigger automated hourly
reconciliation jobs.
"""

import pytest
from .conftest import requires_reconciliation
import asyncio
from datetime import datetime, timedelta, UTC
from src.services.reconciliation_scheduler import ReconciliationScheduler
from src.models.reconciliation_job import JobType, JobStatus
from src.repositories.reconciliation_repository import ReconciliationRepository


@pytest.mark.skip(reason="Reconciliation tests incomplete - missing fixtures")
@pytest.mark.integration
class TestReconciliationScheduled:
    """Test scheduled reconciliation functionality."""

    @pytest.fixture
    def reconciliation_repo(self, postgres_connection):
        """Create reconciliation repository."""
        return ReconciliationRepository(connection=postgres_connection)

    @pytest.fixture
    def scheduler(self, reconciliation_repo, cassandra_repo, postgres_repo):
        """Create reconciliation scheduler."""
        return ReconciliationScheduler(
            reconciliation_repo=reconciliation_repo,
            cassandra_repo=cassandra_repo,
            postgres_repo=postgres_repo,
            enabled=True,
            interval_minutes=1,  # Use 1 minute for testing
            tables=["test_users"]
        )

    @pytest.fixture(autouse=True)
    def setup_control_tables(self, postgres_connection):
        """Create reconciliation control tables."""
        cursor = postgres_connection.cursor()

        # Create reconciliation_jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS _cdc_reconciliation_jobs (
                job_id UUID PRIMARY KEY,
                table_name VARCHAR(255) NOT NULL,
                job_type VARCHAR(50) NOT NULL,
                validation_strategy VARCHAR(50) NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                completed_at TIMESTAMPTZ,
                status VARCHAR(50) NOT NULL,
                cassandra_row_count BIGINT,
                postgres_row_count BIGINT,
                mismatch_count INTEGER,
                drift_percentage DECIMAL(5,2),
                validation_errors JSONB,
                alert_fired BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

        postgres_connection.commit()

        yield

        # Cleanup
        cursor.execute("DROP TABLE IF EXISTS _cdc_reconciliation_jobs")
        postgres_connection.commit()

    async def test_scheduler_triggers_hourly_reconciliation(
        self,
        scheduler,
        reconciliation_repo
    ):
        """Test that scheduler creates HOURLY_SCHEDULED reconciliation jobs."""
        # Start scheduler
        await scheduler.start()

        # Wait for scheduled job to run (1 minute + buffer)
        await asyncio.sleep(70)

        # Query for reconciliation jobs
        jobs = await reconciliation_repo.list_jobs(
            job_type=JobType.HOURLY_SCHEDULED,
            limit=10
        )

        # Verify at least one scheduled job was created
        assert len(jobs) >= 1

        scheduled_job = jobs[0]
        assert scheduled_job.job_type == JobType.HOURLY_SCHEDULED
        assert scheduled_job.table_name == "test_users"
        assert scheduled_job.status in [JobStatus.RUNNING, JobStatus.COMPLETED]

        # Stop scheduler
        await scheduler.stop()

    async def test_scheduler_respects_interval_setting(self, scheduler):
        """Test that scheduler respects the configured interval."""
        # Start scheduler with 1 minute interval
        await scheduler.start()

        # Wait for first job
        await asyncio.sleep(70)

        # Record time of first job
        first_job_time = datetime.now(UTC)

        # Wait for second job (should trigger after ~1 minute)
        await asyncio.sleep(70)

        # Query jobs
        jobs = await scheduler.reconciliation_repo.list_jobs(
            job_type=JobType.HOURLY_SCHEDULED,
            limit=10
        )

        # Should have at least 2 jobs
        assert len(jobs) >= 2

        # Verify second job started ~1 minute after first
        if len(jobs) >= 2:
            time_diff = jobs[1].started_at - jobs[0].started_at
            assert abs(time_diff.total_seconds() - 60) < 10  # Within 10 seconds tolerance

        await scheduler.stop()

    async def test_scheduler_handles_multiple_tables(self, postgres_connection):
        """Test that scheduler reconciles multiple configured tables."""
        # Create second test table
        cursor = postgres_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cdc_test_orders (
                id UUID PRIMARY KEY,
                user_id UUID,
                amount DECIMAL(10,2)
            )
        """)
        postgres_connection.commit()

        # Create scheduler with multiple tables
        scheduler = ReconciliationScheduler(
            reconciliation_repo=self.reconciliation_repo,
            cassandra_repo=self.cassandra_repo,
            postgres_repo=self.postgres_repo,
            enabled=True,
            interval_minutes=1,
            tables=["test_users", "test_orders"]
        )

        await scheduler.start()

        # Wait for scheduled jobs
        await asyncio.sleep(70)

        # Query jobs
        jobs = await scheduler.reconciliation_repo.list_jobs(
            job_type=JobType.HOURLY_SCHEDULED,
            limit=10
        )

        # Should have jobs for both tables
        table_names = {job.table_name for job in jobs}
        assert "test_users" in table_names
        assert "test_orders" in table_names

        await scheduler.stop()

        # Cleanup
        cursor.execute("DROP TABLE IF EXISTS cdc_test_orders")
        postgres_connection.commit()

    async def test_scheduler_disabled_does_not_run(self):
        """Test that scheduler does not run when disabled."""
        # Create disabled scheduler
        scheduler = ReconciliationScheduler(
            reconciliation_repo=self.reconciliation_repo,
            cassandra_repo=self.cassandra_repo,
            postgres_repo=self.postgres_repo,
            enabled=False,  # Disabled
            interval_minutes=1,
            tables=["test_users"]
        )

        await scheduler.start()

        # Wait for potential job
        await asyncio.sleep(70)

        # Query jobs
        jobs = await scheduler.reconciliation_repo.list_jobs(
            job_type=JobType.HOURLY_SCHEDULED,
            limit=10
        )

        # Should have no jobs (scheduler disabled)
        assert len(jobs) == 0

        await scheduler.stop()

    async def test_scheduler_persists_jobs_to_postgresql(
        self,
        scheduler,
        postgres_connection
    ):
        """Test that scheduler persists jobs to _cdc_reconciliation_jobs table."""
        await scheduler.start()

        # Wait for scheduled job
        await asyncio.sleep(70)

        # Query PostgreSQL directly
        cursor = postgres_connection.cursor()
        cursor.execute("""
            SELECT job_id, table_name, job_type, status
            FROM _cdc_reconciliation_jobs
            WHERE job_type = 'HOURLY_SCHEDULED'
            ORDER BY created_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()

        # Verify job persisted
        assert row is not None
        assert row[1] == "test_users"  # table_name
        assert row[2] == "HOURLY_SCHEDULED"  # job_type
        assert row[3] in ["RUNNING", "COMPLETED"]  # status

        await scheduler.stop()
