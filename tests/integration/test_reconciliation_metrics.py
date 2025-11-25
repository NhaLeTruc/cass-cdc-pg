"""Integration test for reconciliation Prometheus metrics (T111).

Tests that reconciliation jobs expose correct metrics to Prometheus.
"""

import pytest
from prometheus_client import REGISTRY
from src.services.reconciliation_engine import ReconciliationEngine
from src.models.reconciliation_job import ValidationStrategy


@pytest.mark.integration
class TestReconciliationMetrics:
    """Test Prometheus metrics for reconciliation."""

    @pytest.fixture(autouse=True)
    def setup_test_data(self, cassandra_session, postgres_connection):
        """Create test data with drift."""
        # Create tables
        cassandra_session.execute("""
            CREATE KEYSPACE IF NOT EXISTS test_warehouse
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
        """)
        cassandra_session.execute("""
            CREATE TABLE IF NOT EXISTS test_warehouse.metrics_test (
                id UUID PRIMARY KEY,
                data TEXT
            )
        """)

        cursor = postgres_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cdc_metrics_test (
                id UUID PRIMARY KEY,
                data VARCHAR(255)
            )
        """)

        # Insert 100 records in Cassandra, 90 in PostgreSQL (10% drift)
        from uuid import uuid4
        for i in range(100):
            record_id = uuid4()
            cassandra_session.execute(
                "INSERT INTO test_warehouse.metrics_test (id, data) VALUES (%s, %s)",
                (record_id, f"data_{i}")
            )

            if i < 90:  # Only insert 90 in PostgreSQL
                cursor.execute(
                    "INSERT INTO cdc_metrics_test (id, data) VALUES (%s, %s)",
                    (record_id, f"data_{i}")
                )

        postgres_connection.commit()

        yield

        # Cleanup
        cassandra_session.execute("DROP TABLE IF EXISTS test_warehouse.metrics_test")
        cursor.execute("DROP TABLE IF EXISTS cdc_metrics_test")
        postgres_connection.commit()

    async def test_reconciliation_exposes_drift_percentage_metric(
        self,
        reconciliation_engine
    ):
        """Test that reconciliation exposes drift_percentage gauge metric."""
        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="metrics_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_metrics_test"
        )

        # Query Prometheus registry for drift percentage metric
        metrics = [
            metric for metric in REGISTRY.collect()
            if metric.name == "cdc_reconciliation_drift_percentage"
        ]

        assert len(metrics) > 0

        # Find metric for our table
        drift_metric = None
        for metric in metrics:
            for sample in metric.samples:
                if sample.labels.get("table") == "metrics_test":
                    drift_metric = sample
                    break

        assert drift_metric is not None
        assert drift_metric.value == pytest.approx(10.0, rel=0.1)

    async def test_reconciliation_exposes_row_count_metrics(
        self,
        reconciliation_engine
    ):
        """Test that reconciliation exposes Cassandra and PostgreSQL row count gauges."""
        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="metrics_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_metrics_test"
        )

        # Query Cassandra row count metric
        cassandra_metrics = [
            metric for metric in REGISTRY.collect()
            if metric.name == "cdc_reconciliation_cassandra_rows"
        ]

        assert len(cassandra_metrics) > 0

        cassandra_sample = None
        for metric in cassandra_metrics:
            for sample in metric.samples:
                if sample.labels.get("table") == "metrics_test":
                    cassandra_sample = sample
                    break

        assert cassandra_sample is not None
        assert cassandra_sample.value == 100

        # Query PostgreSQL row count metric
        postgres_metrics = [
            metric for metric in REGISTRY.collect()
            if metric.name == "cdc_reconciliation_postgres_rows"
        ]

        assert len(postgres_metrics) > 0

        postgres_sample = None
        for metric in postgres_metrics:
            for sample in metric.samples:
                if sample.labels.get("table") == "metrics_test":
                    postgres_sample = sample
                    break

        assert postgres_sample is not None
        assert postgres_sample.value == 90

    async def test_reconciliation_exposes_mismatch_counter(
        self,
        reconciliation_engine
    ):
        """Test that reconciliation exposes mismatches_total counter."""
        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="metrics_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_metrics_test"
        )

        # Query mismatches total metric
        mismatch_metrics = [
            metric for metric in REGISTRY.collect()
            if metric.name == "cdc_reconciliation_mismatches_total"
        ]

        assert len(mismatch_metrics) > 0

        mismatch_sample = None
        for metric in mismatch_metrics:
            for sample in metric.samples:
                if sample.labels.get("table") == "metrics_test":
                    mismatch_sample = sample
                    break

        assert mismatch_sample is not None
        assert mismatch_sample.value >= 10  # Counter increments

    async def test_reconciliation_exposes_job_completed_counter(
        self,
        reconciliation_engine
    ):
        """Test that reconciliation exposes jobs_completed_total counter."""
        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="metrics_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_metrics_test"
        )

        # Query jobs completed metric
        jobs_metrics = [
            metric for metric in REGISTRY.collect()
            if metric.name == "cdc_reconciliation_jobs_completed_total"
        ]

        assert len(jobs_metrics) > 0

        # Find metric for our table with COMPLETED status
        job_sample = None
        for metric in jobs_metrics:
            for sample in metric.samples:
                if (sample.labels.get("table") == "metrics_test" and
                    sample.labels.get("status") == "COMPLETED"):
                    job_sample = sample
                    break

        assert job_sample is not None
        assert job_sample.value >= 1

    async def test_reconciliation_exposes_duration_histogram(
        self,
        reconciliation_engine
    ):
        """Test that reconciliation exposes duration_seconds histogram."""
        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="metrics_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_metrics_test"
        )

        # Query duration histogram
        duration_metrics = [
            metric for metric in REGISTRY.collect()
            if metric.name == "cdc_reconciliation_duration_seconds"
        ]

        assert len(duration_metrics) > 0

        # Find histogram samples for our table
        histogram_samples = []
        for metric in duration_metrics:
            for sample in metric.samples:
                if sample.labels.get("table") == "metrics_test":
                    histogram_samples.append(sample)

        # Histogram should have _count, _sum, and bucket samples
        assert len(histogram_samples) > 0

        # Verify _count sample exists
        count_samples = [s for s in histogram_samples if s.name.endswith("_count")]
        assert len(count_samples) > 0
        assert count_samples[0].value >= 1

    async def test_metrics_endpoint_returns_reconciliation_metrics(
        self,
        reconciliation_engine,
        test_client
    ):
        """Test that /metrics endpoint exposes reconciliation metrics."""
        # Run reconciliation first
        job = await reconciliation_engine.run_row_count_validation(
            table_name="metrics_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_metrics_test"
        )

        # Query /metrics endpoint
        response = test_client.get("/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"

        metrics_text = response.text

        # Verify reconciliation metrics present
        assert "cdc_reconciliation_drift_percentage" in metrics_text
        assert "cdc_reconciliation_cassandra_rows" in metrics_text
        assert "cdc_reconciliation_postgres_rows" in metrics_text
        assert "cdc_reconciliation_mismatches_total" in metrics_text
        assert "cdc_reconciliation_jobs_completed_total" in metrics_text
        assert "cdc_reconciliation_duration_seconds" in metrics_text

        # Verify table label present
        assert 'table="metrics_test"' in metrics_text
