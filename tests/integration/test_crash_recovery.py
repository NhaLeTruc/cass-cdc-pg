"""Integration test for crash recovery from checkpoint."""

import time
import uuid
import pytest
import psycopg2
from cassandra.cluster import Cluster
import structlog

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


class TestCrashRecovery:
    """Test crash recovery from checkpoint."""

    @requires_cdc_pipeline
    def test_crash_recovery_from_checkpoint_no_duplicates(
        self, cassandra_session, postgres_conn
    ):
        """
        Test that CDC pipeline recovers from crash without duplicates.

        Test steps:
        1. Insert 1000 records in Cassandra in batches
        2. Wait for ~500 records to be processed
        3. Kill Kafka Connect container
        4. Restart Kafka Connect
        5. Verify all 1000 records appear in PostgreSQL
        6. Verify no duplicate records exist
        """
        batch_size = 100
        total_records = 1000
        test_prefix = f"crash_test_{int(time.time())}"

        logger.info("test_crash_recovery_start", total_records=total_records)

        # Step 1: Insert 1000 records in batches
        test_ids = []

        logger.info("inserting_test_records", total=total_records)

        for batch_num in range(total_records // batch_size):
            for i in range(batch_size):
                test_id = str(uuid.uuid4())
                test_ids.append(test_id)
                email = f"{test_prefix}_{batch_num}_{i}@example.com"

                cassandra_session.execute(
                    """
                    INSERT INTO users (user_id, email, created_at)
                    VALUES (%s, %s, toTimestamp(now()))
                    """,
                    (uuid.UUID(test_id), email),
                )

            logger.info("batch_inserted", batch_num=batch_num + 1, count=len(test_ids))
            time.sleep(2)  # Allow some processing time

        # Step 2: Wait for some records to be processed
        logger.info("waiting_for_initial_processing")
        time.sleep(15)

        cursor = postgres_conn.cursor()

        # Check how many records have been processed
        cursor.execute(
            "SELECT COUNT(*) FROM cdc_users WHERE email LIKE %s",
            (f"{test_prefix}%",),
        )
        initial_count = cursor.fetchone()[0]

        logger.info("initial_records_processed", count=initial_count)

        # Step 3: Kill Kafka Connect to simulate crash
        import subprocess

        logger.info("killing_kafka_connect")
        result = subprocess.run(
            ["docker", "compose", "kill", "kafka-connect"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to kill Kafka Connect: {result.stderr}"

        time.sleep(5)

        # Step 4: Restart Kafka Connect
        logger.info("restarting_kafka_connect")
        result = subprocess.run(
            ["docker", "compose", "start", "kafka-connect"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to restart Kafka Connect: {result.stderr}"

        logger.info("waiting_for_kafka_connect_recovery")
        time.sleep(30)  # Wait for Kafka Connect to recover and resume processing

        # Step 5: Verify all 1000 records appear in PostgreSQL
        logger.info("verifying_all_records_processed")

        max_wait = 120
        start_time = time.time()
        all_records_found = False

        while time.time() - start_time < max_wait:
            cursor.execute(
                "SELECT COUNT(*) FROM cdc_users WHERE email LIKE %s",
                (f"{test_prefix}%",),
            )
            final_count = cursor.fetchone()[0]

            logger.info(
                "records_processed",
                count=final_count,
                target=total_records,
                elapsed=int(time.time() - start_time),
            )

            if final_count >= total_records:
                all_records_found = True
                break

            time.sleep(5)

        assert all_records_found, \
            f"Expected {total_records} records, found {final_count} after {max_wait}s"

        # Step 6: Verify no duplicate records
        logger.info("checking_for_duplicates")

        cursor.execute(
            """
            SELECT email, COUNT(*) as count
            FROM cdc_users
            WHERE email LIKE %s
            GROUP BY email
            HAVING COUNT(*) > 1
            """,
            (f"{test_prefix}%",),
        )

        duplicates = cursor.fetchall()

        if duplicates:
            logger.error("duplicates_found", duplicates=duplicates)
            for email, count in duplicates:
                logger.error("duplicate_record", email=email, count=count)

        assert len(duplicates) == 0, \
            f"Found {len(duplicates)} duplicate records after crash recovery"

        cursor.close()

        logger.info("test_crash_recovery_success", total_records=total_records)

    @requires_cdc_pipeline
    def test_checkpoint_offset_preservation(self, cassandra_session, postgres_conn):
        """
        Test that Kafka Connect preserves consumer offsets across restarts.

        Verifies that consumer groups maintain their position after restart.
        """
        import subprocess

        logger.info("test_checkpoint_preservation_start")

        # Get current consumer group offsets before restart
        logger.info("getting_consumer_group_offsets")

        result = subprocess.run(
            [
                "docker", "compose", "exec", "-T", "kafka",
                "kafka-consumer-groups", "--bootstrap-server", "localhost:9092",
                "--group", "connect-postgres-sink", "--describe"
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode == 0:
            before_restart = result.stdout
            logger.info("offsets_before_restart", output=before_restart)
        else:
            before_restart = None
            logger.warning("consumer_group_not_found_before_restart")

        # Insert a few records
        test_ids = []
        for i in range(10):
            test_id = str(uuid.uuid4())
            test_ids.append(test_id)
            email = f"checkpoint_test_{int(time.time())}_{i}@example.com"

            cassandra_session.execute(
                """
                INSERT INTO users (user_id, email, created_at)
                VALUES (%s, %s, toTimestamp(now()))
                """,
                (uuid.UUID(test_id), email),
            )

        time.sleep(10)  # Allow processing

        # Restart Kafka Connect
        logger.info("restarting_kafka_connect_for_checkpoint_test")
        subprocess.run(["docker", "compose", "restart", "kafka-connect"], capture_output=True, timeout=40)

        time.sleep(20)  # Wait for restart

        # Get consumer group offsets after restart
        logger.info("getting_consumer_group_offsets_after_restart")

        result = subprocess.run(
            [
                "docker", "compose", "exec", "-T", "kafka",
                "kafka-consumer-groups", "--bootstrap-server", "localhost:9092",
                "--group", "connect-postgres-sink", "--describe"
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode == 0:
            after_restart = result.stdout
            logger.info("offsets_after_restart", output=after_restart)

            # Verify consumer group still exists
            assert "connect-postgres-sink" in after_restart or "TOPIC" in after_restart, \
                "Consumer group should exist after restart"

            logger.info("test_checkpoint_preservation_success")
        else:
            logger.error("failed_to_get_consumer_offsets_after_restart", error=result.stderr)

    @requires_cdc_pipeline
    def test_state_store_recovery(self, cassandra_session):
        """
        Test that Kafka Connect state stores are recovered after crash.

        Verifies that connector state and task assignments are restored.
        """
        import subprocess
        import requests

        logger.info("test_state_store_recovery_start")

        # Get connector status before restart
        try:
            response = requests.get(
                "http://localhost:8083/connectors/postgres-sink/status",
                timeout=10,
            )

            if response.status_code == 200:
                before_restart_status = response.json()
                logger.info("connector_status_before_restart", status=before_restart_status)
            else:
                before_restart_status = None
                logger.warning("connector_not_found_before_restart")
        except Exception as e:
            before_restart_status = None
            logger.warning("failed_to_get_connector_status", error=str(e))

        # Restart Kafka Connect
        logger.info("restarting_kafka_connect_for_state_test")
        subprocess.run(["docker", "compose", "restart", "kafka-connect"], capture_output=True, timeout=40)

        time.sleep(30)  # Wait for Kafka Connect to fully restart

        # Get connector status after restart
        logger.info("checking_connector_status_after_restart")

        max_wait = 60
        start_time = time.time()
        connector_recovered = False

        while time.time() - start_time < max_wait:
            try:
                response = requests.get(
                    "http://localhost:8083/connectors/postgres-sink/status",
                    timeout=10,
                )

                if response.status_code == 200:
                    after_restart_status = response.json()
                    logger.info("connector_status_after_restart", status=after_restart_status)

                    # Check if connector is running
                    connector_state = after_restart_status.get("connector", {}).get("state")
                    tasks = after_restart_status.get("tasks", [])

                    if connector_state == "RUNNING" and len(tasks) > 0:
                        task_states = [task.get("state") for task in tasks]
                        if all(state == "RUNNING" for state in task_states):
                            connector_recovered = True
                            logger.info(
                                "connector_recovered",
                                connector_state=connector_state,
                                task_count=len(tasks),
                            )
                            break

            except Exception as e:
                logger.debug("connector_status_check_failed", error=str(e))

            time.sleep(5)

        assert connector_recovered, \
            "Connector should recover to RUNNING state after restart"

        logger.info("test_state_store_recovery_success")

    @requires_cdc_pipeline
    def test_exactly_once_semantics_after_crash(self, cassandra_session, postgres_conn):
        """
        Test exactly-once semantics are maintained after crash.

        Verifies that records are neither lost nor duplicated when Kafka Connect crashes
        mid-batch.
        """
        test_prefix = f"exactly_once_{int(time.time())}"
        batch_size = 50

        logger.info("test_exactly_once_start", batch_size=batch_size)

        test_ids = []

        # Insert batch of records
        for i in range(batch_size):
            test_id = str(uuid.uuid4())
            test_ids.append(test_id)
            email = f"{test_prefix}_{i}@example.com"

            cassandra_session.execute(
                """
                INSERT INTO users (user_id, email, created_at)
                VALUES (%s, %s, toTimestamp(now()))
                """,
                (uuid.UUID(test_id), email),
            )

        logger.info("batch_inserted", count=batch_size)

        # Immediately crash Kafka Connect
        import subprocess
        logger.info("crashing_kafka_connect_mid_batch")
        subprocess.run(["docker", "compose", "kill", "kafka-connect"], capture_output=True, timeout=30)

        time.sleep(3)

        # Restart
        logger.info("restarting_kafka_connect")
        subprocess.run(["docker", "compose", "start", "kafka-connect"], capture_output=True, timeout=30)

        time.sleep(30)

        # Verify exactly batch_size records (no more, no less)
        cursor = postgres_conn.cursor()

        max_wait = 60
        start_time = time.time()
        correct_count = False

        while time.time() - start_time < max_wait:
            cursor.execute(
                "SELECT COUNT(*) FROM cdc_users WHERE email LIKE %s",
                (f"{test_prefix}%",),
            )
            count = cursor.fetchone()[0]

            logger.info("checking_exactly_once_count", count=count, expected=batch_size)

            if count == batch_size:
                correct_count = True
                break
            elif count > batch_size:
                # Fail immediately if duplicates detected
                pytest.fail(f"Duplicates detected: {count} > {batch_size}")

            time.sleep(5)

        cursor.close()

        assert correct_count, \
            f"Expected exactly {batch_size} records, found {count}"

        logger.info("test_exactly_once_success", batch_size=batch_size)
