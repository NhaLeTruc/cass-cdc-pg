"""Integration test for row count reconciliation (T108).

Tests the reconciliation engine's ability to detect row count drift between
Cassandra and PostgreSQL by comparing total record counts.
"""

import pytest
from uuid import uuid4
from datetime import datetime, UTC
from src.services.reconciliation_engine import ReconciliationEngine
from src.models.reconciliation_job import ReconciliationJob, JobType, ValidationStrategy, JobStatus
from src.repositories.cassandra_repository import CassandraRepository
from src.repositories.postgresql_repository import PostgreSQLRepository


@pytest.mark.integration
class TestReconciliationRowCount:
    """Test row count reconciliation validation."""

    @pytest.fixture
    def cassandra_repo(self, cassandra_session):
        """Create Cassandra repository."""
        return CassandraRepository(session=cassandra_session)

    @pytest.fixture
    def postgres_repo(self, postgres_connection):
        """Create PostgreSQL repository."""
        return PostgreSQLRepository(connection=postgres_connection)

    @pytest.fixture
    def reconciliation_engine(self, cassandra_repo, postgres_repo):
        """Create reconciliation engine."""
        return ReconciliationEngine(
            cassandra_repo=cassandra_repo,
            postgres_repo=postgres_repo
        )

    @pytest.fixture(autouse=True)
    def setup_test_data(self, cassandra_session, postgres_connection):
        """Insert test data in both Cassandra and PostgreSQL."""
        # Create test table in Cassandra
        cassandra_session.execute("""
            CREATE KEYSPACE IF NOT EXISTS test_warehouse
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
        """)
        cassandra_session.execute("""
            CREATE TABLE IF NOT EXISTS test_warehouse.test_users (
                id UUID PRIMARY KEY,
                username TEXT,
                email TEXT
            )
        """)

        # Insert 1000 records in Cassandra
        for i in range(1000):
            user_id = uuid4()
            cassandra_session.execute(
                "INSERT INTO test_warehouse.test_users (id, username, email) VALUES (%s, %s, %s)",
                (user_id, f"user_{i}", f"user_{i}@example.com")
            )

        # Create test table in PostgreSQL
        cursor = postgres_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cdc_test_users (
                id UUID PRIMARY KEY,
                username VARCHAR(255),
                email VARCHAR(255)
            )
        """)

        # Insert 950 records in PostgreSQL (50 missing = 5% drift)
        cassandra_rows = list(cassandra_session.execute(
            "SELECT id, username, email FROM test_warehouse.test_users LIMIT 950"
        ))
        for row in cassandra_rows:
            cursor.execute(
                "INSERT INTO cdc_test_users (id, username, email) VALUES (%s, %s, %s)",
                (row.id, row.username, row.email)
            )
        postgres_connection.commit()

        yield

        # Cleanup
        cassandra_session.execute("DROP TABLE IF EXISTS test_warehouse.test_users")
        cursor.execute("DROP TABLE IF EXISTS cdc_test_users")
        postgres_connection.commit()

    async def test_row_count_reconciliation_detects_drift(self, reconciliation_engine):
        """Test that reconciliation detects 5% drift in row counts."""
        # Run row count reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="test_users",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_test_users"
        )

        # Verify job created
        assert job is not None
        assert job.table_name == "test_users"
        assert job.job_type == JobType.MANUAL_ONDEMAND
        assert job.validation_strategy == ValidationStrategy.ROW_COUNT
        assert job.status == JobStatus.COMPLETED

        # Verify row counts
        assert job.cassandra_row_count == 1000
        assert job.postgres_row_count == 950
        assert job.mismatch_count == 50

        # Verify drift percentage (5%)
        assert job.drift_percentage == pytest.approx(5.0, rel=0.1)

        # Verify alert fired for >5% drift
        assert job.alert_fired is False  # 5% is at threshold, not over

    async def test_row_count_reconciliation_no_drift(self, reconciliation_engine, postgres_connection):
        """Test that reconciliation reports 0% drift when counts match."""
        # Insert remaining 50 records to match Cassandra
        cursor = postgres_connection.cursor()
        cassandra_rows = list(
            self.cassandra_repo.session.execute(
                "SELECT id, username, email FROM test_warehouse.test_users"
            )
        )

        # Get IDs already in PostgreSQL
        cursor.execute("SELECT id FROM cdc_test_users")
        existing_ids = set(row[0] for row in cursor.fetchall())

        # Insert missing records
        for row in cassandra_rows:
            if row.id not in existing_ids:
                cursor.execute(
                    "INSERT INTO cdc_test_users (id, username, email) VALUES (%s, %s, %s)",
                    (row.id, row.username, row.email)
                )
        postgres_connection.commit()

        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="test_users",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_test_users"
        )

        # Verify no drift
        assert job.cassandra_row_count == 1000
        assert job.postgres_row_count == 1000
        assert job.mismatch_count == 0
        assert job.drift_percentage == 0.0
        assert job.alert_fired is False

    async def test_row_count_reconciliation_critical_drift(self, reconciliation_engine, postgres_connection):
        """Test that reconciliation detects critical drift >5%."""
        # Delete 100 more records from PostgreSQL (total 150 missing = 15% drift)
        cursor = postgres_connection.cursor()
        cursor.execute("DELETE FROM cdc_test_users WHERE id IN (SELECT id FROM cdc_test_users LIMIT 100)")
        postgres_connection.commit()

        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="test_users",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_test_users"
        )

        # Verify critical drift detected
        assert job.cassandra_row_count == 1000
        assert job.postgres_row_count == 850
        assert job.mismatch_count == 150
        assert job.drift_percentage == pytest.approx(15.0, rel=0.1)

        # Verify alert fired for >5% critical drift
        assert job.alert_fired is True
