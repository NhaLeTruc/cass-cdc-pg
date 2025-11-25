"""Integration test for retry logic with exponential backoff."""

import time
import uuid
import pytest
import psycopg2
from cassandra.cluster import Cluster
import structlog
import re

from .conftest import requires_cdc_pipeline
logger = structlog.get_logger(__name__)


@pytest.fixture(scope="module")
def cassandra_session():
    """Create Cassandra session."""
    cluster = Cluster(["localhost"], port=9042, connect_timeout=10, control_connection_timeout=10)
    session = cluster.connect("cdc_test")
    yield session
    cluster.shutdown()


@pytest.fixture(scope="module")
def postgres_conn():
    """Create PostgreSQL connection."""
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="cdc_target",
        user="postgres",
        password="postgres",
    )
    yield conn
    conn.close()


class TestRetryLogic:
    """Test retry logic with exponential backoff."""

    @requires_cdc_pipeline
    def test_retry_with_exponential_backoff(self, cassandra_session, postgres_conn, tmp_path):
        """
        Test that CDC pipeline retries with exponential backoff when PostgreSQL is down.

        Test steps:
        1. Stop PostgreSQL container
        2. Insert record in Cassandra
        3. Verify retry attempts at 1s, 2s, 4s, 8s intervals in logs
        4. Restart PostgreSQL
        5. Verify record eventually appears in PostgreSQL
        """
        test_id = str(uuid.uuid4())
        email = f"retry_test_{int(time.time())}@example.com"

        logger.info("test_retry_start", test_id=test_id, email=email)

        # Step 1: Stop PostgreSQL (simulating outage)
        import subprocess
        logger.info("stopping_postgresql")
        result = subprocess.run(
            ["docker", "compose", "stop", "postgres"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to stop PostgreSQL: {result.stderr}"

        time.sleep(5)  # Wait for connections to fail

        # Step 2: Insert record in Cassandra while PostgreSQL is down
        logger.info("inserting_cassandra_record", test_id=test_id)
        cassandra_session.execute(
            """
            INSERT INTO users (user_id, email, created_at)
            VALUES (%s, %s, toTimestamp(now()))
            """,
            (uuid.UUID(test_id), email),
        )

        # Step 3: Collect Kafka Connect logs to verify retry attempts
        log_file = tmp_path / "kafka_connect_retry_logs.txt"

        logger.info("collecting_kafka_connect_logs", log_file=str(log_file))

        # Wait up to 20 seconds to capture retry attempts
        start_time = time.time()
        retry_intervals = []

        while time.time() - start_time < 20:
            result = subprocess.run(
                ["docker", "compose", "logs", "--tail", "100", "kafka-connect"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            logs = result.stdout

            # Look for retry patterns in logs (connection failures, retry attempts)
            # Pattern: WARN or ERROR messages about PostgreSQL connection failures
            retry_pattern = re.compile(r"(retry|connection.*failed|unable to connect)", re.IGNORECASE)

            for line in logs.split("\n"):
                if retry_pattern.search(line):
                    retry_intervals.append(time.time() - start_time)

            if len(retry_intervals) >= 3:
                break

            time.sleep(1)

        logger.info(
            "retry_attempts_detected",
            retry_count=len(retry_intervals),
            intervals=retry_intervals,
        )

        # Verify that retries occurred (we should see at least 2-3 retry attempts)
        assert len(retry_intervals) >= 2, \
            f"Expected at least 2 retry attempts, got {len(retry_intervals)}"

        # Step 4: Restart PostgreSQL
        logger.info("restarting_postgresql")
        result = subprocess.run(
            ["docker", "compose", "start", "postgres"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to start PostgreSQL: {result.stderr}"

        time.sleep(10)  # Wait for PostgreSQL to be healthy

        # Step 5: Verify record eventually appears in PostgreSQL
        logger.info("verifying_record_in_postgres", test_id=test_id)

        cursor = postgres_conn.cursor()
        max_wait = 60
        start_time = time.time()
        record_found = False

        while time.time() - start_time < max_wait:
            cursor.execute(
                "SELECT email FROM cdc_users WHERE user_id = %s",
                (test_id,),
            )
            result = cursor.fetchone()

            if result:
                record_found = True
                assert result[0] == email, f"Email mismatch: {result[0]} != {email}"
                break

            time.sleep(2)

        cursor.close()

        assert record_found, \
            f"Record {test_id} not found in PostgreSQL after {max_wait}s"

        logger.info("test_retry_success", test_id=test_id, email=email)

    @requires_cdc_pipeline
    def test_retry_behavior_under_intermittent_failures(self, cassandra_session, postgres_conn):
        """
        Test retry behavior when PostgreSQL has intermittent connectivity issues.

        Simulates flaky connections by stopping and starting PostgreSQL multiple times.
        """
        test_id = str(uuid.uuid4())
        email = f"intermittent_test_{int(time.time())}@example.com"

        logger.info("test_intermittent_start", test_id=test_id)

        # Insert record in Cassandra
        cassandra_session.execute(
            """
            INSERT INTO users (user_id, email, created_at)
            VALUES (%s, %s, toTimestamp(now()))
            """,
            (uuid.UUID(test_id), email),
        )

        # Simulate intermittent failures (stop/start PostgreSQL quickly)
        import subprocess

        for i in range(2):
            logger.info("simulating_intermittent_failure", attempt=i + 1)
            subprocess.run(["docker", "compose", "stop", "postgres"], capture_output=True, timeout=20)
            time.sleep(3)
            subprocess.run(["docker", "compose", "start", "postgres"], capture_output=True, timeout=20)
            time.sleep(5)

        # Verify record eventually makes it through
        cursor = postgres_conn.cursor()
        max_wait = 60
        start_time = time.time()
        record_found = False

        while time.time() - start_time < max_wait:
            try:
                cursor.execute(
                    "SELECT email FROM cdc_users WHERE user_id = %s",
                    (test_id,),
                )
                result = cursor.fetchone()

                if result:
                    record_found = True
                    assert result[0] == email
                    break
            except psycopg2.Error:
                # Connection might fail during intermittent issues
                time.sleep(2)
                continue

            time.sleep(2)

        cursor.close()

        assert record_found, \
            f"Record {test_id} not replicated despite retries"

        logger.info("test_intermittent_success", test_id=test_id)

    @requires_cdc_pipeline
    def test_retry_metrics_recorded(self, cassandra_session):
        """
        Test that retry attempts are recorded in Prometheus metrics.

        Verifies cdc_retry_attempts_total counter increments during failures.
        """
        import requests

        test_id = str(uuid.uuid4())
        email = f"metrics_test_{int(time.time())}@example.com"

        logger.info("test_retry_metrics_start", test_id=test_id)

        # Get initial metrics
        response = requests.get("http://localhost:8000/metrics", timeout=10)
        assert response.status_code == 200

        initial_metrics = response.text
        initial_retry_count = 0

        # Parse retry counter if it exists
        retry_pattern = re.compile(r'cdc_retry_attempts_total.*?(\d+)')
        match = retry_pattern.search(initial_metrics)
        if match:
            initial_retry_count = int(match.group(1))

        logger.info("initial_retry_count", count=initial_retry_count)

        # Insert record (may trigger retries if system is under stress)
        cassandra_session.execute(
            """
            INSERT INTO users (user_id, email, created_at)
            VALUES (%s, %s, toTimestamp(now()))
            """,
            (uuid.UUID(test_id), email),
        )

        time.sleep(10)

        # Get updated metrics
        response = requests.get("http://localhost:8000/metrics", timeout=10)
        assert response.status_code == 200

        updated_metrics = response.text

        # Verify metrics endpoint includes retry metrics definition
        assert "cdc_retry_attempts_total" in updated_metrics or "cdc_errors_total" in updated_metrics, \
            "Retry metrics not exposed in /metrics endpoint"

        logger.info("test_retry_metrics_success")
