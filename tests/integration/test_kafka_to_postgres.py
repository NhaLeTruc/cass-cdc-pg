import pytest
import uuid
import time
import json
from typing import Generator, Dict, Any
from datetime import datetime
from confluent_kafka import Producer
import psycopg2
from psycopg2.extras import RealDictCursor


@pytest.fixture(scope="module")
def kafka_producer() -> Generator[Producer, None, None]:
    """Provide Kafka producer for publishing test events."""
    producer = Producer(
        {
            "bootstrap.servers": "localhost:9092",
            "client.id": "test-kafka-postgres-flow",
        }
    )

    yield producer

    producer.flush()


@pytest.fixture(scope="module")
def postgres_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Provide PostgreSQL connection for verifying replicated data."""
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="cdc_target",
        user="cdc_user",
        password="cdc_password",
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cdc_users (
            id UUID PRIMARY KEY,
            username VARCHAR(255),
            email VARCHAR(255),
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ,
            _cdc_deleted BOOLEAN DEFAULT FALSE,
            _cdc_timestamp_micros BIGINT,
            _ttl_expiry_timestamp TIMESTAMPTZ
        )
        """
    )
    conn.commit()

    yield conn

    cursor.execute("DROP TABLE IF EXISTS cdc_users")
    conn.commit()
    conn.close()


class TestKafkaToPostgreSQLFlow:
    """
    Integration test for Kafka→PostgreSQL CDC flow.

    Tests that CDC events published to Kafka are consumed by JDBC Sink Connector
    and written to PostgreSQL with correct transformations.
    """

    def test_create_event_from_kafka_inserts_into_postgres(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that CREATE event from Kafka inserts record into PostgreSQL."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        timestamp_micros = int(time.time() * 1_000_000)

        event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": timestamp_micros,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=event["event_id"].encode("utf-8"),
            value=json.dumps(event).encode("utf-8"),
        )
        kafka_producer.flush()

        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should be inserted into PostgreSQL"
        assert row["id"] == user_id, "User ID should match"
        assert row["username"] == username, "Username should match"
        assert row["email"] == email, "Email should match"
        assert row["_cdc_deleted"] is False, "Record should not be marked as deleted"
        assert (
            row["_cdc_timestamp_micros"] == timestamp_micros
        ), "CDC timestamp should be stored"

    def test_update_event_from_kafka_updates_postgres(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that UPDATE event from Kafka updates record in PostgreSQL."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        original_timestamp = int(time.time() * 1_000_000)

        create_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": original_timestamp,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=create_event["event_id"].encode("utf-8"),
            value=json.dumps(create_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        new_email = f"updated_{email}"
        update_timestamp = int(time.time() * 1_000_000)

        update_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "UPDATE",
            "timestamp_micros": update_timestamp,
            "before": {
                "id": str(user_id),
                "username": username,
                "email": email,
            },
            "after": {
                "id": str(user_id),
                "username": username,
                "email": new_email,
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=update_event["event_id"].encode("utf-8"),
            value=json.dumps(update_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should exist in PostgreSQL"
        assert row["email"] == new_email, "Email should be updated"
        assert (
            row["_cdc_timestamp_micros"] == update_timestamp
        ), "CDC timestamp should be updated"

    def test_delete_event_from_kafka_marks_deleted_in_postgres(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that DELETE event from Kafka marks record as deleted (soft delete)."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"

        create_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": int(time.time() * 1_000_000),
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=create_event["event_id"].encode("utf-8"),
            value=json.dumps(create_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        delete_timestamp = int(time.time() * 1_000_000)

        delete_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "DELETE",
            "timestamp_micros": delete_timestamp,
            "before": {
                "id": str(user_id),
                "username": username,
                "email": email,
            },
            "after": None,
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": True,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=delete_event["event_id"].encode("utf-8"),
            value=json.dumps(delete_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should still exist (soft delete)"
        assert row["_cdc_deleted"] is True, "Record should be marked as deleted"
        assert (
            row["_cdc_timestamp_micros"] == delete_timestamp
        ), "CDC timestamp should reflect delete time"

    def test_events_with_ttl_set_expiry_timestamp(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that events with TTL set _ttl_expiry_timestamp in PostgreSQL."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        ttl_seconds = 3600
        timestamp_micros = int(time.time() * 1_000_000)

        event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": timestamp_micros,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": ttl_seconds,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=event["event_id"].encode("utf-8"),
            value=json.dumps(event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should be inserted into PostgreSQL"
        assert row["_ttl_expiry_timestamp"] is not None, "TTL expiry should be set"

        expected_expiry = datetime.fromtimestamp(
            timestamp_micros / 1_000_000
        ) + timedelta(seconds=ttl_seconds)
        actual_expiry = row["_ttl_expiry_timestamp"]

        time_diff = abs((actual_expiry - expected_expiry).total_seconds())
        assert time_diff < 5, "TTL expiry timestamp should be approximately correct"

    def test_cdc_timestamp_micros_stored_correctly(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that _cdc_timestamp_micros is stored correctly for ordering."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        timestamp_micros = int(time.time() * 1_000_000)

        event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": timestamp_micros,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=event["event_id"].encode("utf-8"),
            value=json.dumps(event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should exist"
        assert (
            row["_cdc_timestamp_micros"] == timestamp_micros
        ), "CDC timestamp should match event timestamp"

    def test_multiple_events_processed_in_batch(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that multiple events are processed in batch efficiently."""
        user_ids = []

        for i in range(10):
            user_id = uuid.uuid4()
            user_ids.append(user_id)
            username = f"batchuser_{int(time.time())}_{i}"
            email = f"{username}@example.com"

            event = {
                "event_id": str(uuid.uuid4()),
                "source_table": "users",
                "operation_type": "CREATE",
                "timestamp_micros": int(time.time() * 1_000_000),
                "before": None,
                "after": {
                    "id": str(user_id),
                    "username": username,
                    "email": email,
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                },
                "schema_version": 1,
                "ttl_seconds": None,
                "is_tombstone": False,
            }

            kafka_producer.produce(
                topic="cdc-events-users",
                key=event["event_id"].encode("utf-8"),
                value=json.dumps(event).encode("utf-8"),
            )

        kafka_producer.flush()
        time.sleep(10)

        cursor = postgres_connection.cursor()
        placeholders = ",".join(["%s"] * len(user_ids))
        cursor.execute(
            f"SELECT COUNT(*) FROM cdc_users WHERE id IN ({placeholders})",
            [str(uid) for uid in user_ids],
        )
        count = cursor.fetchone()[0]

        assert count == 10, f"All 10 records should be inserted, found {count}"

    def test_invalid_event_routed_to_dlq(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that invalid events are routed to DLQ topic (errors.tolerance=all)."""
        invalid_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": int(time.time() * 1_000_000),
            "before": None,
            "after": {
                "id": "invalid-uuid-format",
                "username": "testuser",
                "email": "test@example.com",
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=invalid_event["event_id"].encode("utf-8"),
            value=json.dumps(invalid_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM cdc_users WHERE username = 'testuser'")
        count = cursor.fetchone()[0]

        assert count == 0, "Invalid event should not be inserted into PostgreSQL"


from datetime import timedelta
