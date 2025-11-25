"""Reconciliation Scheduler service (T118).

Scheduler for automated hourly reconciliation jobs using APScheduler.
"""

import asyncio
from typing import List, Optional
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from src.models.reconciliation_job import JobType
from src.repositories.cassandra_repository import CassandraRepository
from src.repositories.postgresql_repository import PostgreSQLRepository
from src.repositories.reconciliation_repository import ReconciliationRepository
from src.services.reconciliation_engine import ReconciliationEngine
from src.services.alert_service import AlertService


class ReconciliationScheduler:
    """Scheduler for automated reconciliation jobs.

    Uses APScheduler to trigger hourly reconciliation jobs for configured tables.
    """

    def __init__(
        self,
        reconciliation_repo: ReconciliationRepository,
        cassandra_repo: CassandraRepository,
        postgres_repo: PostgreSQLRepository,
        enabled: bool = True,
        interval_minutes: int = 60,
        tables: Optional[List[str]] = None,
        alert_service: Optional[AlertService] = None,
        database_url: Optional[str] = None
    ):
        """Initialize reconciliation scheduler.

        Args:
            reconciliation_repo: Repository for persisting reconciliation results
            cassandra_repo: Cassandra repository for source data access
            postgres_repo: PostgreSQL repository for target data access
            enabled: Whether scheduler is enabled
            interval_minutes: Interval between reconciliation runs (default: 60)
            tables: List of table names to reconcile (empty = all tables)
            alert_service: Optional alert service for drift notifications
            database_url: Optional database URL for APScheduler job store
        """
        self.reconciliation_repo = reconciliation_repo
        self.cassandra_repo = cassandra_repo
        self.postgres_repo = postgres_repo
        self.enabled = enabled
        self.interval_minutes = interval_minutes
        self.tables = tables or []
        self.alert_service = alert_service

        # Initialize reconciliation engine
        self.engine = ReconciliationEngine(
            cassandra_repo=cassandra_repo,
            postgres_repo=postgres_repo,
            reconciliation_repo=reconciliation_repo
        )

        # Configure APScheduler
        jobstores = {}
        if database_url:
            jobstores["default"] = SQLAlchemyJobStore(url=database_url)

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone="UTC"
        )

        self._running = False

    async def start(self) -> None:
        """Start the reconciliation scheduler."""
        if not self.enabled:
            print("Reconciliation scheduler is disabled")
            return

        if self._running:
            print("Reconciliation scheduler already running")
            return

        # Schedule reconciliation jobs
        for table in self.tables:
            self.scheduler.add_job(
                func=self._run_scheduled_reconciliation,
                trigger=IntervalTrigger(minutes=self.interval_minutes),
                args=[table],
                id=f"reconciliation_{table}",
                replace_existing=True,
                max_instances=1
            )

        # Start scheduler
        self.scheduler.start()
        self._running = True

        print(
            f"Reconciliation scheduler started: "
            f"interval={self.interval_minutes}m, "
            f"tables={len(self.tables)}"
        )

    async def stop(self) -> None:
        """Stop the reconciliation scheduler."""
        if not self._running:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False

        print("Reconciliation scheduler stopped")

    async def manual_trigger_reconciliation(
        self,
        table_name: str,
        source_keyspace: str = "warehouse",
        target_schema: str = "public"
    ) -> None:
        """Manually trigger reconciliation for a specific table.

        Args:
            table_name: Table to reconcile
            source_keyspace: Cassandra keyspace (default: warehouse)
            target_schema: PostgreSQL schema (default: public)
        """
        await self._run_reconciliation(
            table_name=table_name,
            source_keyspace=source_keyspace,
            target_schema=target_schema,
            job_type=JobType.MANUAL_ONDEMAND
        )

    async def schedule_reconciliation_for_all_tables(self) -> None:
        """Schedule reconciliation for all configured tables immediately."""
        for table in self.tables:
            await self._run_scheduled_reconciliation(table)

    async def _run_scheduled_reconciliation(self, table_name: str) -> None:
        """Run scheduled reconciliation job for a table.

        Args:
            table_name: Table to reconcile
        """
        await self._run_reconciliation(
            table_name=table_name,
            source_keyspace="warehouse",
            target_schema="public",
            job_type=JobType.HOURLY_SCHEDULED
        )

    async def _run_reconciliation(
        self,
        table_name: str,
        source_keyspace: str,
        target_schema: str,
        job_type: JobType
    ) -> None:
        """Run reconciliation job.

        Args:
            table_name: Table to reconcile
            source_keyspace: Cassandra keyspace
            target_schema: PostgreSQL schema
            job_type: Job type (scheduled or manual)
        """
        try:
            print(
                f"Running {job_type.value} reconciliation for {table_name} "
                f"at {datetime.now()}"
            )

            # Run row count validation
            job = await self.engine.run_row_count_validation(
                table_name=table_name,
                source_keyspace=source_keyspace,
                target_schema=target_schema
            )

            # Update job type
            if self.reconciliation_repo:
                self.reconciliation_repo.update_job(
                    job_id=job.job_id,
                    job_type=job_type.value
                )

            # Send alert if drift detected and alert service configured
            if self.alert_service and job.drift_percentage:
                drift = float(job.drift_percentage)
                if drift >= self.alert_service.warning_threshold:
                    await self.alert_service.send_reconciliation_alert(job)

            print(
                f"Reconciliation completed for {table_name}: "
                f"drift={job.drift_percentage}%, "
                f"mismatches={job.mismatch_count}"
            )

        except Exception as e:
            print(
                f"Reconciliation failed for {table_name}: {e}"
            )

    def is_running(self) -> bool:
        """Check if scheduler is running.

        Returns:
            True if scheduler is running
        """
        return self._running

    def get_scheduled_jobs(self) -> List[dict]:
        """Get list of scheduled reconciliation jobs.

        Returns:
            List of job information dictionaries
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "next_run_time": job.next_run_time,
                "trigger": str(job.trigger)
            })
        return jobs

    async def pause_table_reconciliation(self, table_name: str) -> None:
        """Pause reconciliation for a specific table.

        Args:
            table_name: Table to pause reconciliation for
        """
        job_id = f"reconciliation_{table_name}"
        self.scheduler.pause_job(job_id)
        print(f"Paused reconciliation for {table_name}")

    async def resume_table_reconciliation(self, table_name: str) -> None:
        """Resume reconciliation for a specific table.

        Args:
            table_name: Table to resume reconciliation for
        """
        job_id = f"reconciliation_{table_name}"
        self.scheduler.resume_job(job_id)
        print(f"Resumed reconciliation for {table_name}")
