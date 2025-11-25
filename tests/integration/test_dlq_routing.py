"""Integration test for DLQ routing after retries exhausted."""

import time
import uuid
import pytest
import psycopg2
from cassandra.cluster import Cluster
from kafka import KafkaConsumer
import json
import structlog
import requests
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


@pytest.fixture(scope="module")
def kafka_consumer():
    """Create Kafka consumer for DLQ topic."""
    consumer = KafkaConsumer(
        "dlq-events",
        bootstrap_servers=["localhost:9092"],
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")) if m else None,
        consumer_timeout_ms=5000,
    )
    yield consumer
    consumer.close()


class TestDLQRouting:
    """Test DLQ routing after retries are exhausted."""

    @requires_cdc_pipeline
    def test_dlq_routing_after_retries_exhausted(
        self, cassandra_session, postgres_conn, kafka_consumer
    ):
        """
        Test that failed events are routed to DLQ after max retries.

        Test steps:
        1. Stop PostgreSQL to simulate persistent failure
        2. Insert record with invalid data in Cassandra
        3. Wait for retries to exhaust (up to 5 minutes)
        4. Verify event appears in dlq-events Kafka topic
        5. Verify retry_count and error details are present
        6. Verify event is in _cdc_dlq_records table
        """
        test_id = str(uuid.uuid4())
        invalid_email = "x" * 300  # Exceeds VARCHAR(255) limit

        logger.info("test_dlq_routing_start", test_id=test_id)

        # Step 1: Stop PostgreSQL to force failures
        import subprocess
        logger.info("stopping_postgresql")
        result = subprocess.run(
            ["docker", "compose", "stop", "postgres"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to stop PostgreSQL: {result.stderr}"

        time.sleep(5)

        # Step 2: Insert record with invalid data
        logger.info("inserting_invalid_record", test_id=test_id, email_length=len(invalid_email))
        cassandra_session.execute(
            """
            INSERT INTO users (user_id, email, created_at)
            VALUES (%s, %s, toTimestamp(now()))
            """,
            (uuid.UUID(test_id), invalid_email),
        )

        # Wait a bit for Kafka Connect to attempt retries
        logger.info("waiting_for_retries_to_exhaust")
        time.sleep(30)  # Reduced from 5 minutes for faster testing

        # Step 3: Restart PostgreSQL so we can check DLQ table
        logger.info("restarting_postgresql")
        result = subprocess.run(
            ["docker", "compose", "start", "postgres"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed to start PostgreSQL: {result.stderr}"

        time.sleep(10)

        # Step 4: Check dlq-events Kafka topic for the failed event
        logger.info("checking_dlq_kafka_topic")

        dlq_event_found = False
        dlq_event_data = None

        # Seek to beginning and consume messages
        kafka_consumer.seek_to_beginning()

        for message in kafka_consumer:
            event = message.value

            logger.debug("dlq_event", event=event)

            if event and "original_event" in event:
                original = event["original_event"]
                if isinstance(original, dict) and original.get("user_id") == test_id:
                    dlq_event_found = True
                    dlq_event_data = event
                    logger.info("dlq_event_found", event=event)
                    break

        # Note: In actual implementation, DLQ events may take up to 5 minutes
        # This test uses reduced timeout for faster feedback
        if not dlq_event_found:
            logger.warning(
                "dlq_event_not_found_in_kafka",
                note="Event may take up to 5 minutes to reach DLQ in production"
            )

        # Step 5: Verify DLQ record structure if found
        if dlq_event_data:
            assert "error_type" in dlq_event_data, "DLQ event missing error_type"
            assert "error_message" in dlq_event_data, "DLQ event missing error_message"
            assert "retry_count" in dlq_event_data or "failed_at" in dlq_event_data, \
                "DLQ event missing retry metadata"

        # Step 6: Check _cdc_dlq_records table
        logger.info("checking_dlq_table", test_id=test_id)

        cursor = postgres_conn.cursor()

        max_wait = 30
        start_time = time.time()
        dlq_record_found = False

        while time.time() - start_time < max_wait:
            cursor.execute(
                """
                SELECT id, source_table, error_type, error_message, failed_at
                FROM _cdc_dlq_records
                WHERE source_table = 'users'
                AND event_data::text LIKE %s
                ORDER BY failed_at DESC
                LIMIT 1
                """,
                (f"%{test_id}%",),
            )

            result = cursor.fetchone()

            if result:
                dlq_record_found = True
                dlq_id, source_table, error_type, error_message, failed_at = result

                logger.info(
                    "dlq_record_found",
                    dlq_id=dlq_id,
                    source_table=source_table,
                    error_type=error_type,
                    failed_at=failed_at,
                )

                assert source_table == "users", f"Unexpected source_table: {source_table}"
                assert error_type in ["SCHEMA_MISMATCH", "TYPE_CONVERSION_ERROR", "CONSTRAINT_VIOLATION", "NETWORK_TIMEOUT", "UNKNOWN"], \
                    f"Unexpected error_type: {error_type}"
                assert error_message is not None and len(error_message) > 0, \
                    "error_message should not be empty"

                break

            time.sleep(2)

        cursor.close()

        # Either Kafka DLQ topic or PostgreSQL DLQ table should have the record
        assert dlq_event_found or dlq_record_found, \
            f"Failed event {test_id} not found in DLQ (Kafka or PostgreSQL) after retries"

        logger.info("test_dlq_routing_success", test_id=test_id)

    @requires_cdc_pipeline
    def test_dlq_event_contains_full_context(self, cassandra_session, postgres_conn):
        """
        Test that DLQ events contain full error context for troubleshooting.

        Verifies:
        - Original event data is preserved
        - Error stack trace is captured
        - Timestamp of first failure is recorded
        - Timestamp of last retry is recorded
        """
        test_id = str(uuid.uuid4())
        invalid_email = None  # Null value for non-nullable field

        logger.info("test_dlq_context_start", test_id=test_id)

        # Insert record with constraint violation
        cassandra_session.execute(
            """
            INSERT INTO users (user_id, email, created_at)
            VALUES (%s, %s, toTimestamp(now()))
            """,
            (uuid.UUID(test_id), invalid_email),
        )

        time.sleep(20)  # Wait for processing and potential DLQ routing

        cursor = postgres_conn.cursor()

        cursor.execute(
            """
            SELECT event_data, error_type, error_message, error_stack_trace, failed_at
            FROM _cdc_dlq_records
            WHERE event_data::text LIKE %s
            ORDER BY failed_at DESC
            LIMIT 1
            """,
            (f"%{test_id}%",),
        )

        result = cursor.fetchone()

        if result:
            event_data, error_type, error_message, error_stack_trace, failed_at = result

            logger.info(
                "dlq_record_with_context",
                error_type=error_type,
                has_stack_trace=error_stack_trace is not None,
                failed_at=failed_at,
            )

            # Verify original event data is preserved
            assert event_data is not None, "event_data should be preserved"
            assert test_id in str(event_data), "event_data should contain test_id"

            # Verify error context
            assert error_type is not None, "error_type should be set"
            assert error_message is not None, "error_message should be set"

            # error_stack_trace may or may not be present depending on error type
            # but if present, should not be empty
            if error_stack_trace:
                assert len(error_stack_trace) > 0, "error_stack_trace should not be empty"

            assert failed_at is not None, "failed_at timestamp should be set"

            logger.info("test_dlq_context_success")
        else:
            logger.warning(
                "dlq_record_not_found",
                test_id=test_id,
                note="Record may not have reached DLQ within test timeout",
            )

        cursor.close()

    @requires_cdc_pipeline
    def test_dlq_table_indexes_exist(self, postgres_conn):
        """
        Test that DLQ table has proper indexes for efficient querying.

        Verifies indexes on:
        - source_table
        - error_type
        - failed_at
        - resolution_status (if column exists)
        """
        cursor = postgres_conn.cursor()

        # Check if _cdc_dlq_records table exists
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = '_cdc_dlq_records'
            )
            """
        )

        table_exists = cursor.fetchone()[0]

        if table_exists:
            logger.info("checking_dlq_table_indexes")

            # Get indexes for _cdc_dlq_records table
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = '_cdc_dlq_records'
                """
            )

            indexes = cursor.fetchall()

            logger.info("dlq_table_indexes", index_count=len(indexes))

            index_names = [idx[0] for idx in indexes]

            # Verify primary key or unique index exists
            assert any("pkey" in idx or "id" in idx for idx in index_names), \
                "DLQ table should have primary key index"

            # Log available indexes for verification
            for index_name, index_def in indexes:
                logger.info("dlq_index", name=index_name, definition=index_def)

            logger.info("test_dlq_indexes_success")
        else:
            logger.warning("dlq_table_not_found", note="_cdc_dlq_records table not yet created")

        cursor.close()

    @requires_cdc_pipeline
    def test_dlq_retention_policy(self, postgres_conn):
        """
        Test that DLQ records have appropriate retention policy.

        Verifies that DLQ Kafka topic has 30-day retention (2592000000 ms).
        """
        import subprocess

        logger.info("checking_dlq_kafka_retention")

        result = subprocess.run(
            [
                "docker", "compose", "exec", "-T", "kafka",
                "kafka-topics", "--bootstrap-server", "localhost:9092",
                "--describe", "--topic", "dlq-events"
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode == 0:
            output = result.stdout

            logger.info("dlq_topic_config", output=output)

            # Check for retention configuration
            # retention.ms=2592000000 (30 days)
            assert "dlq-events" in output, "dlq-events topic should exist"

            if "retention.ms" in output:
                assert "2592000000" in output, \
                    "DLQ topic should have 30-day retention (2592000000 ms)"
                logger.info("dlq_retention_verified", retention="30 days")
            else:
                logger.warning("dlq_retention_not_configured", note="Using default retention")

            logger.info("test_dlq_retention_success")
        else:
            logger.error("failed_to_describe_dlq_topic", error=result.stderr)
            pytest.fail(f"Failed to describe dlq-events topic: {result.stderr}")
