import pytest
import uuid
import time
import json
from typing import Generator
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
            "client.id": "test-out-of-order-events",
        }
    )

    yield producer

    producer.flush()


@pytest.fixture(scope="module")
def postgres_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Provide PostgreSQL connection for verifying event handling."""
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


class TestOutOfOrderEventHandling:
    """
    Integration test for out-of-order event handling with Last-Write-Wins (LWW) strategy.

    Tests that:
    1. Newer events (higher timestamp_micros) overwrite older events
    2. Older events (lower timestamp_micros) are rejected when newer data exists
    3. Events with equal timestamp_micros use event_id as tiebreaker
    4. Conflict resolution preserves data consistency
    """

    def test_newer_event_overwrites_older_event(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that event with higher timestamp_micros overwrites existing record."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        old_email = f"old_{username}@example.com"
        new_email = f"new_{username}@example.com"

        older_timestamp = int(time.time() * 1_000_000) - 10_000_000
        newer_timestamp = int(time.time() * 1_000_000)

        older_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": older_timestamp,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": old_email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=older_event["event_id"].encode("utf-8"),
            value=json.dumps(older_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        newer_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "UPDATE",
            "timestamp_micros": newer_timestamp,
            "before": {
                "id": str(user_id),
                "email": old_email,
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
            key=newer_event["event_id"].encode("utf-8"),
            value=json.dumps(newer_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should exist in PostgreSQL"
        assert (
            row["email"] == new_email
        ), "Newer event should overwrite older event"
        assert (
            row["_cdc_timestamp_micros"] == newer_timestamp
        ), "Timestamp should reflect newer event"

    def test_older_event_rejected_when_newer_exists(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that event with lower timestamp_micros is rejected when newer data exists."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        new_email = f"new_{username}@example.com"
        old_email = f"old_{username}@example.com"

        newer_timestamp = int(time.time() * 1_000_000)
        older_timestamp = newer_timestamp - 10_000_000

        newer_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": newer_timestamp,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": new_email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=newer_event["event_id"].encode("utf-8"),
            value=json.dumps(newer_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()
        assert row is not None, "Newer event should be inserted"
        assert row["email"] == new_email, "Newer email should be present"

        older_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "UPDATE",
            "timestamp_micros": older_timestamp,
            "before": {
                "id": str(user_id),
                "email": new_email,
            },
            "after": {
                "id": str(user_id),
                "username": username,
                "email": old_email,
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=older_event["event_id"].encode("utf-8"),
            value=json.dumps(older_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should still exist"
        assert (
            row["email"] == new_email
        ), "Older event should NOT overwrite newer data - email should remain unchanged"
        assert (
            row["_cdc_timestamp_micros"] == newer_timestamp
        ), "Timestamp should remain at newer value"

    def test_equal_timestamps_use_event_id_tiebreaker(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that events with equal timestamp_micros use event_id as tiebreaker."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email1 = f"email1_{username}@example.com"
        email2 = f"email2_{username}@example.com"

        same_timestamp = int(time.time() * 1_000_000)

        event_id_1 = str(uuid.uuid4())
        event_id_2 = str(uuid.uuid4())

        lexicographically_first_id = min(event_id_1, event_id_2)
        lexicographically_second_id = max(event_id_1, event_id_2)

        winning_email = email1 if event_id_1 == lexicographically_second_id else email2
        losing_email = email2 if event_id_1 == lexicographically_second_id else email1

        event1 = {
            "event_id": event_id_1,
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": same_timestamp,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": email1,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        event2 = {
            "event_id": event_id_2,
            "source_table": "users",
            "operation_type": "UPDATE",
            "timestamp_micros": same_timestamp,
            "before": {
                "id": str(user_id),
                "email": email1,
            },
            "after": {
                "id": str(user_id),
                "username": username,
                "email": email2,
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=event1["event_id"].encode("utf-8"),
            value=json.dumps(event1).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(3)

        kafka_producer.produce(
            topic="cdc-events-users",
            key=event2["event_id"].encode("utf-8"),
            value=json.dumps(event2).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should exist"
        assert (
            row["email"] == winning_email
        ), f"Event with lexicographically greater event_id ({lexicographically_second_id}) should win tiebreaker"

    def test_out_of_order_sequence_maintains_consistency(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that out-of-order sequence of events maintains data consistency."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"

        base_timestamp = int(time.time() * 1_000_000)

        event_t3 = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "UPDATE",
            "timestamp_micros": base_timestamp + 3_000_000,
            "before": {"id": str(user_id), "email": "v2@example.com"},
            "after": {
                "id": str(user_id),
                "username": username,
                "email": "v3@example.com",
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        event_t1 = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": base_timestamp + 1_000_000,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": "v1@example.com",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        event_t2 = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "UPDATE",
            "timestamp_micros": base_timestamp + 2_000_000,
            "before": {"id": str(user_id), "email": "v1@example.com"},
            "after": {
                "id": str(user_id),
                "username": username,
                "email": "v2@example.com",
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        for event in [event_t3, event_t1, event_t2]:
            kafka_producer.produce(
                topic="cdc-events-users",
                key=event["event_id"].encode("utf-8"),
                value=json.dumps(event).encode("utf-8"),
            )
            time.sleep(0.5)

        kafka_producer.flush()
        time.sleep(10)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should exist"
        assert (
            row["email"] == "v3@example.com"
        ), "Latest event (t3) should win despite out-of-order arrival"
        assert (
            row["_cdc_timestamp_micros"] == base_timestamp + 3_000_000
        ), "Timestamp should reflect latest event"

    def test_conflict_resolution_with_deletes(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test conflict resolution when DELETE events arrive out of order."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"

        base_timestamp = int(time.time() * 1_000_000)

        delete_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "DELETE",
            "timestamp_micros": base_timestamp + 2_000_000,
            "before": {"id": str(user_id), "email": email},
            "after": None,
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": True,
        }

        create_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": base_timestamp,
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
            key=delete_event["event_id"].encode("utf-8"),
            value=json.dumps(delete_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        kafka_producer.produce(
            topic="cdc-events-users",
            key=create_event["event_id"].encode("utf-8"),
            value=json.dumps(create_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row is not None, "Record should exist"
        assert (
            row["_cdc_deleted"] is True
        ), "DELETE event (newer) should win over CREATE (older)"
        assert (
            row["_cdc_timestamp_micros"] == base_timestamp + 2_000_000
        ), "Timestamp should reflect DELETE event"

    def test_metrics_track_rejected_events(
        self, kafka_producer: Producer, postgres_connection: psycopg2.extensions.connection
    ) -> None:
        """Test that metrics track rejected out-of-order events."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        new_email = f"new_{username}@example.com"
        old_email = f"old_{username}@example.com"

        newer_timestamp = int(time.time() * 1_000_000)
        older_timestamp = newer_timestamp - 5_000_000

        newer_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "CREATE",
            "timestamp_micros": newer_timestamp,
            "before": None,
            "after": {
                "id": str(user_id),
                "username": username,
                "email": new_email,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=newer_event["event_id"].encode("utf-8"),
            value=json.dumps(newer_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        older_event = {
            "event_id": str(uuid.uuid4()),
            "source_table": "users",
            "operation_type": "UPDATE",
            "timestamp_micros": older_timestamp,
            "before": {"id": str(user_id)},
            "after": {
                "id": str(user_id),
                "username": username,
                "email": old_email,
                "updated_at": datetime.utcnow().isoformat(),
            },
            "schema_version": 1,
            "ttl_seconds": None,
            "is_tombstone": False,
        }

        kafka_producer.produce(
            topic="cdc-events-users",
            key=older_event["event_id"].encode("utf-8"),
            value=json.dumps(older_event).encode("utf-8"),
        )
        kafka_producer.flush()
        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (str(user_id),))
        row = cursor.fetchone()

        assert row["email"] == new_email, "Older event should be rejected"
