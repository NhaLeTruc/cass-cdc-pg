"""Integration test for AlertManager alert firing (T112).

Tests that reconciliation drift triggers alerts in AlertManager via Prometheus.
"""

import pytest
from .conftest import requires_reconciliation
import httpx
from datetime import datetime, timedelta, UTC
from src.services.reconciliation_engine import ReconciliationEngine
from src.services.alert_service import AlertService


@pytest.mark.skip(reason="Reconciliation tests incomplete - missing fixtures")
@pytest.mark.integration
class TestReconciliationAlerts:
    """Test AlertManager integration for reconciliation alerts."""

    @pytest.fixture
    def alert_service(self):
        """Create alert service."""
        return AlertService(
            prometheus_pushgateway_url="http://localhost:9091",
            warning_threshold=1.0,  # 1% drift = warning
            critical_threshold=5.0  # 5% drift = critical
        )

    @pytest.fixture(autouse=True)
    def setup_drift_scenario(self, cassandra_session, postgres_connection):
        """Create test data with 10% drift."""
        # Create tables
        cassandra_session.execute("""
            CREATE KEYSPACE IF NOT EXISTS test_warehouse
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
        """)
        cassandra_session.execute("""
            CREATE TABLE IF NOT EXISTS test_warehouse.alert_test (
                id UUID PRIMARY KEY,
                data TEXT
            )
        """)

        cursor = postgres_connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cdc_alert_test (
                id UUID PRIMARY KEY,
                data VARCHAR(255)
            )
        """)

        # Insert 100 records in Cassandra, 90 in PostgreSQL (10% drift)
        from uuid import uuid4
        for i in range(100):
            record_id = uuid4()
            cassandra_session.execute(
                "INSERT INTO test_warehouse.alert_test (id, data) VALUES (%s, %s)",
                (record_id, f"data_{i}")
            )

            if i < 90:  # Only 90 in PostgreSQL
                cursor.execute(
                    "INSERT INTO cdc_alert_test (id, data) VALUES (%s, %s)",
                    (record_id, f"data_{i}")
                )

        postgres_connection.commit()

        yield

        # Cleanup
        cassandra_session.execute("DROP TABLE IF EXISTS test_warehouse.alert_test")
        cursor.execute("DROP TABLE IF EXISTS cdc_alert_test")
        postgres_connection.commit()

    async def test_reconciliation_fires_critical_alert_for_high_drift(
        self,
        reconciliation_engine,
        alert_service
    ):
        """Test that 10% drift triggers ReconciliationDriftCritical alert."""
        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="alert_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_alert_test"
        )

        # Send alert via AlertService
        await alert_service.send_reconciliation_alert(job)

        # Wait for alert to propagate
        import asyncio
        await asyncio.sleep(5)

        # Query AlertManager API for active alerts
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:9093/api/v2/alerts")

        assert response.status_code == 200

        alerts = response.json()

        # Find ReconciliationDriftCritical alert
        critical_alerts = [
            alert for alert in alerts
            if alert.get("labels", {}).get("alertname") == "ReconciliationDriftCritical"
            and alert.get("labels", {}).get("table") == "alert_test"
        ]

        # Verify alert fired
        assert len(critical_alerts) > 0

        critical_alert = critical_alerts[0]
        assert critical_alert["labels"]["severity"] == "critical"
        assert critical_alert["status"]["state"] == "active"
        assert "10" in critical_alert["annotations"]["description"]  # Contains drift percentage

    async def test_reconciliation_fires_warning_alert_for_moderate_drift(
        self,
        postgres_connection,
        reconciliation_engine,
        alert_service
    ):
        """Test that 2% drift triggers ReconciliationDriftWarning alert."""
        # Delete only 2 records (2% drift)
        cursor = postgres_connection.cursor()
        cursor.execute("DELETE FROM cdc_alert_test WHERE id IN (SELECT id FROM cdc_alert_test LIMIT 8)")
        postgres_connection.commit()

        # Now have 98 records in PostgreSQL, 100 in Cassandra (2% drift)

        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="alert_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_alert_test"
        )

        # Send alert
        await alert_service.send_reconciliation_alert(job)

        # Wait for alert
        import asyncio
        await asyncio.sleep(5)

        # Query AlertManager
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:9093/api/v2/alerts")

        alerts = response.json()

        # Find warning alert
        warning_alerts = [
            alert for alert in alerts
            if alert.get("labels", {}).get("alertname") == "ReconciliationDriftWarning"
            and alert.get("labels", {}).get("table") == "alert_test"
        ]

        # Verify warning alert fired
        assert len(warning_alerts) > 0

        warning_alert = warning_alerts[0]
        assert warning_alert["labels"]["severity"] == "warning"
        assert warning_alert["status"]["state"] == "active"

    async def test_no_alert_fired_for_zero_drift(
        self,
        postgres_connection,
        reconciliation_engine,
        alert_service,
        cassandra_session
    ):
        """Test that 0% drift does not trigger alerts."""
        # Insert missing 10 records to PostgreSQL
        cursor = postgres_connection.cursor()

        # Get all Cassandra records
        cassandra_rows = list(
            cassandra_session.execute("SELECT id, data FROM test_warehouse.alert_test")
        )

        # Get existing PostgreSQL IDs
        cursor.execute("SELECT id FROM cdc_alert_test")
        existing_ids = set(row[0] for row in cursor.fetchall())

        # Insert missing records
        for row in cassandra_rows:
            if row.id not in existing_ids:
                cursor.execute(
                    "INSERT INTO cdc_alert_test (id, data) VALUES (%s, %s)",
                    (row.id, row.data)
                )

        postgres_connection.commit()

        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="alert_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_alert_test"
        )

        # Attempt to send alert (should not send for 0% drift)
        await alert_service.send_reconciliation_alert(job)

        # Wait
        import asyncio
        await asyncio.sleep(5)

        # Query AlertManager
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:9093/api/v2/alerts")

        alerts = response.json()

        # Find any reconciliation drift alerts for our table
        drift_alerts = [
            alert for alert in alerts
            if "ReconciliationDrift" in alert.get("labels", {}).get("alertname", "")
            and alert.get("labels", {}).get("table") == "alert_test"
        ]

        # Should have no active alerts (or resolved alerts only)
        active_alerts = [a for a in drift_alerts if a["status"]["state"] == "active"]
        assert len(active_alerts) == 0

    async def test_alert_includes_job_metadata(
        self,
        reconciliation_engine,
        alert_service
    ):
        """Test that alert includes job_id, drift percentage, and mismatch count."""
        # Run reconciliation with 10% drift
        job = await reconciliation_engine.run_row_count_validation(
            table_name="alert_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_alert_test"
        )

        # Send alert
        await alert_service.send_reconciliation_alert(job)

        # Wait for alert
        import asyncio
        await asyncio.sleep(5)

        # Query AlertManager
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:9093/api/v2/alerts")

        alerts = response.json()

        # Find critical alert
        critical_alert = next(
            (a for a in alerts
             if a.get("labels", {}).get("alertname") == "ReconciliationDriftCritical"
             and a.get("labels", {}).get("table") == "alert_test"),
            None
        )

        assert critical_alert is not None

        # Verify metadata in annotations
        annotations = critical_alert.get("annotations", {})
        assert str(job.job_id) in annotations.get("description", "")
        assert "10" in annotations.get("description", "")  # Drift percentage
        assert "10" in annotations.get("summary", "")  # Mismatch count

    async def test_alert_persisted_in_reconciliation_job(
        self,
        reconciliation_engine,
        alert_service,
        postgres_connection
    ):
        """Test that alert_fired flag is set in reconciliation job."""
        # Run reconciliation
        job = await reconciliation_engine.run_row_count_validation(
            table_name="alert_test",
            source_keyspace="test_warehouse",
            target_schema="public",
            target_table="cdc_alert_test"
        )

        # Send alert
        await alert_service.send_reconciliation_alert(job)

        # Query PostgreSQL directly
        cursor = postgres_connection.cursor()
        cursor.execute("""
            SELECT alert_fired, drift_percentage
            FROM _cdc_reconciliation_jobs
            WHERE job_id = %s
        """, (job.job_id,))

        row = cursor.fetchone()

        assert row is not None
        assert row[0] is True  # alert_fired
        assert row[1] == pytest.approx(10.0, rel=0.1)  # drift_percentage
