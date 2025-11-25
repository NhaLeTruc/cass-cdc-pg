"""Integration test for checksum validation reconciliation (T109).

Tests the reconciliation engine's ability to detect data mismatches using
checksum comparison of record contents.
"""

import pytest
from .conftest import requires_reconciliation
from uuid import uuid4
import hashlib
import json
from src.services.reconciliation_engine import ReconciliationEngine
from src.models.reconciliation_job import ValidationStrategy, JobStatus
from src.models.reconciliation_mismatch import MismatchType


@pytest.mark.skip(reason="Reconciliation tests incomplete - missing fixtures")
@pytest.mark.integration
class TestReconciliationChecksum:
    """Test checksum validation reconciliation."""

    @pytest.fixture
    def test_records(self):
        """Generate test record IDs."""
        return [uuid4() for _ in range(100)]

    @pytest.fixture(autouse=True)
    def setup_test_data(self, cassandra_session, postgres_connection, test_records):
        """Insert test data with some mismatches."""
        # Create tables
        cassandra_session.execute("""
            CREATE KEYSPACE IF NOT EXISTS test_warehouse
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
        """)
        cassandra_session.execute("""
            CREATE TABLE IF NOT EXISTS test_warehouse.checksum_test (
                id UUID PRIMARY KEY,
                data TEXT,
                value INT
            )
        """)

        cursor = postgres_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cdc_checksum_test (
                id UUID PRIMARY KEY,
                data VARCHAR(255),
                value INTEGER
            )
        """)

        # Insert 100 records in both databases
        for i, record_id in enumerate(test_records):
            data_value = f"data_{i}"
            int_value = i

            # Insert in Cassandra
            cassandra_session.execute(
                "INSERT INTO test_warehouse.checksum_test (id, data, value) VALUES (%s, %s, %s)",
                (record_id, data_value, int_value)
            )

            # Insert in PostgreSQL with 10 mismatched records
            if i < 10:
                # Modify data for first 10 records to create DATA_MISMATCH
                data_value = f"modified_data_{i}"
                int_value = i + 1000

            cursor.execute(
                "INSERT INTO cdc_checksum_test (id, data, value) VALUES (%s, %s, %s)",
                (record_id, data_value, int_value)
            )

        postgres_connection.commit()

        yield

        # Cleanup
        cassandra_session.execute("DROP TABLE IF EXISTS test_warehouse.checksum_test")
        cursor.execute("DROP TABLE IF EXISTS cdc_checksum_test")
        postgres_connection.commit()

    async def test_checksum_validation_detects_mismatches(
        self,
        reconciliation_engine,
        test_records
    ):
        """Test that checksum validation detects 10 data mismatches."""
        # Run checksum reconciliation
        job = await reconciliation_engine.run_checksum_validation(
            table_name="checksum_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_checksum_test",
            sample_size=100  # Check all records
        )

        # Verify job completed
        assert job.status == JobStatus.COMPLETED
        assert job.validation_strategy == ValidationStrategy.CHECKSUM

        # Verify mismatch count
        assert job.mismatch_count == 10
        assert len(job.mismatches) == 10

        # Verify all mismatches are DATA_MISMATCH type
        for mismatch in job.mismatches:
            assert mismatch.mismatch_type == MismatchType.DATA_MISMATCH
            assert mismatch.cassandra_checksum != mismatch.postgres_checksum
            assert mismatch.cassandra_data is not None
            assert mismatch.postgres_data is not None

    async def test_checksum_validation_calculates_checksums_correctly(
        self,
        reconciliation_engine,
        cassandra_session,
        postgres_connection
    ):
        """Test that checksums are calculated consistently."""
        # Get first record from Cassandra
        row = cassandra_session.execute(
            "SELECT id, data, value FROM test_warehouse.checksum_test LIMIT 1"
        ).one()

        # Calculate expected checksum
        record_data = {
            "id": str(row.id),
            "data": row.data,
            "value": row.value
        }
        expected_checksum = hashlib.sha256(
            json.dumps(record_data, sort_keys=True).encode()
        ).hexdigest()

        # Get checksum from reconciliation engine
        calculated_checksum = reconciliation_engine._calculate_checksum(record_data)

        assert calculated_checksum == expected_checksum

    async def test_checksum_validation_with_sampling(self, reconciliation_engine):
        """Test that checksum validation can sample records."""
        # Run with sample size of 20
        job = await reconciliation_engine.run_checksum_validation(
            table_name="checksum_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_checksum_test",
            sample_size=20
        )

        # Should have checked 20 records
        # Expected ~2 mismatches in sample (10% of 20)
        assert job.status == JobStatus.COMPLETED
        assert job.mismatch_count <= 10  # At most 10 mismatches total
        assert len(job.mismatches) <= 20  # Checked at most 20 records

    async def test_checksum_validation_missing_records(
        self,
        reconciliation_engine,
        postgres_connection
    ):
        """Test detection of records missing in PostgreSQL."""
        # Delete 5 records from PostgreSQL
        cursor = postgres_connection.cursor()
        cursor.execute("DELETE FROM cdc_checksum_test WHERE value < 5")
        postgres_connection.commit()

        # Run checksum reconciliation
        job = await reconciliation_engine.run_checksum_validation(
            table_name="checksum_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_checksum_test",
            sample_size=100
        )

        # Should detect 5 MISSING_IN_POSTGRES + 10 DATA_MISMATCH (on remaining records)
        missing_count = sum(
            1 for m in job.mismatches
            if m.mismatch_type == MismatchType.MISSING_IN_POSTGRES
        )
        data_mismatch_count = sum(
            1 for m in job.mismatches
            if m.mismatch_type == MismatchType.DATA_MISMATCH
        )

        assert missing_count == 5
        assert data_mismatch_count == 5  # First 10 - deleted 5 = 5 remaining mismatched
