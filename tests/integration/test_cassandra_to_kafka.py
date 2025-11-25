import pytest
import uuid
import time
import requests
from typing import Generator, Dict, Any
from datetime import datetime
from cassandra.cluster import Cluster, Session
from confluent_kafka import Consumer, KafkaException
import json


def check_cassandra_connector() -> bool:
    """Check if Cassandra source connector is deployed."""
    try:
        response = requests.get("http://localhost:8083/connectors", timeout=5)
        connectors = response.json()
        return "cassandra-source" in connectors
    except Exception:
        return False


@pytest.fixture(scope="module")
def cassandra_session() -> Generator[Session, None, None]:
    """Provide Cassandra session using testcontainers."""
    cluster = Cluster(
        contact_points=["localhost"],
        port=9042,
        connect_timeout=10,
        control_connection_timeout=10,
    )
    session = cluster.connect()

    session.execute(
        """
        CREATE KEYSPACE IF NOT EXISTS warehouse
        WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
        """
    )

    session.execute(
        """
        CREATE TABLE IF NOT EXISTS warehouse.users (
            id UUID PRIMARY KEY,
            username TEXT,
            email TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )

    session.execute("ALTER TABLE warehouse.users WITH cdc = true")

    yield session

    session.execute("DROP TABLE IF EXISTS warehouse.users")
    session.execute("DROP KEYSPACE IF EXISTS warehouse")
    cluster.shutdown()


@pytest.fixture(scope="module")
def kafka_consumer() -> Generator[Consumer, None, None]:
    """Provide Kafka consumer for cdc-events-users topic."""
    consumer = Consumer(
        {
            "bootstrap.servers": "localhost:9092",
            "group.id": "test-cassandra-kafka-flow",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )

    consumer.subscribe(["cdc-events-users"])

    yield consumer

    consumer.close()


class TestCassandraToKafkaFlow:
    """
    Integration test for Cassandra→Kafka CDC flow.

    Tests that data changes in Cassandra are captured by Debezium
    and published to the correct Kafka topic.
    """

    @pytest.mark.skipif(
        not check_cassandra_connector(),
        reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
    )
    def test_insert_in_cassandra_produces_create_event_in_kafka(
        self, cassandra_session: Session, kafka_consumer: Consumer
    ) -> None:
        """Test INSERT in Cassandra produces CREATE event in Kafka topic."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        event = self._consume_event_with_timeout(kafka_consumer, timeout_seconds=10)

        assert event is not None, "No event received from Kafka within timeout"
        assert event["operation_type"] == "CREATE", "Event should be CREATE operation"
        assert event["source_table"] == "users", "Event should be from users table"
        assert event["after"] is not None, "CREATE event should have 'after' data"
        assert event["after"]["id"] == str(user_id), "Event should contain inserted user_id"
        assert event["after"]["username"] == username, "Event should contain username"
        assert event["after"]["email"] == email, "Event should contain email"

    @pytest.mark.skipif(
        not check_cassandra_connector(),
        reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
    )
    def test_update_in_cassandra_produces_update_event_in_kafka(
        self, cassandra_session: Session, kafka_consumer: Consumer
    ) -> None:
        """Test UPDATE in Cassandra produces UPDATE event in Kafka topic."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        self._consume_event_with_timeout(kafka_consumer, timeout_seconds=5)

        new_email = f"updated_{email}"
        cassandra_session.execute(
            """
            UPDATE warehouse.users
            SET email = %s, updated_at = %s
            WHERE id = %s
            """,
            (new_email, datetime.utcnow(), user_id),
        )

        event = self._consume_event_with_timeout(kafka_consumer, timeout_seconds=10)

        assert event is not None, "No UPDATE event received from Kafka"
        assert event["operation_type"] == "UPDATE", "Event should be UPDATE operation"
        assert event["after"]["email"] == new_email, "Event should contain updated email"
        assert event["before"] is not None, "UPDATE event should have 'before' data"
        assert event["before"]["email"] == email, "Before data should have old email"

    @pytest.mark.skipif(
        not check_cassandra_connector(),
        reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
    )
    def test_delete_in_cassandra_produces_delete_event_in_kafka(
        self, cassandra_session: Session, kafka_consumer: Consumer
    ) -> None:
        """Test DELETE in Cassandra produces DELETE event with tombstone in Kafka topic."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        self._consume_event_with_timeout(kafka_consumer, timeout_seconds=5)

        cassandra_session.execute(
            """
            DELETE FROM warehouse.users WHERE id = %s
            """,
            (user_id,),
        )

        event = self._consume_event_with_timeout(kafka_consumer, timeout_seconds=10)

        assert event is not None, "No DELETE event received from Kafka"
        assert event["operation_type"] == "DELETE", "Event should be DELETE operation"
        assert event["before"] is not None, "DELETE event should have 'before' data"
        assert event["before"]["id"] == str(user_id), "Before data should contain user_id"
        assert event["after"] is None, "DELETE event should have null 'after' data"

    @pytest.mark.skipif(
        not check_cassandra_connector(),
        reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
    )
    def test_event_contains_timestamp_micros(
        self, cassandra_session: Session, kafka_consumer: Consumer
    ) -> None:
        """Test that CDC events contain timestamp_micros for ordering."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        before_insert_micros = int(time.time() * 1_000_000)

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        event = self._consume_event_with_timeout(kafka_consumer, timeout_seconds=10)

        after_insert_micros = int(time.time() * 1_000_000)

        assert event is not None, "No event received from Kafka"
        assert "timestamp_micros" in event, "Event must contain timestamp_micros field"
        assert isinstance(
            event["timestamp_micros"], int
        ), "timestamp_micros must be integer"
        assert (
            before_insert_micros <= event["timestamp_micros"] <= after_insert_micros
        ), "timestamp_micros should be within test execution timeframe"

    @pytest.mark.skipif(
        not check_cassandra_connector(),
        reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
    )
    def test_event_contains_schema_version(
        self, cassandra_session: Session, kafka_consumer: Consumer
    ) -> None:
        """Test that CDC events contain schema_version for evolution tracking."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        event = self._consume_event_with_timeout(kafka_consumer, timeout_seconds=10)

        assert event is not None, "No event received from Kafka"
        assert "schema_version" in event, "Event must contain schema_version field"
        assert isinstance(event["schema_version"], int), "schema_version must be integer"
        assert event["schema_version"] >= 1, "schema_version must be at least 1"

    @pytest.mark.skipif(
        not check_cassandra_connector(),
        reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
    )
    def test_event_contains_event_id(
        self, cassandra_session: Session, kafka_consumer: Consumer
    ) -> None:
        """Test that CDC events contain unique event_id for deduplication."""
        user_id = uuid.uuid4()
        username = f"testuser_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        event = self._consume_event_with_timeout(kafka_consumer, timeout_seconds=10)

        assert event is not None, "No event received from Kafka"
        assert "event_id" in event, "Event must contain event_id field"
        assert isinstance(event["event_id"], str), "event_id must be string"
        assert len(event["event_id"]) > 0, "event_id must not be empty"

    @pytest.mark.skipif(
        not check_cassandra_connector(),
        reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
    )
    def test_multiple_inserts_produce_events_in_order(
        self, cassandra_session: Session, kafka_consumer: Consumer
    ) -> None:
        """Test that multiple INSERT operations produce events in timestamp order."""
        user_ids = []
        timestamps = []

        for i in range(3):
            user_id = uuid.uuid4()
            user_ids.append(user_id)
            username = f"testuser_{int(time.time())}_{i}"
            email = f"{username}@example.com"
            now = datetime.utcnow()

            cassandra_session.execute(
                """
                INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, username, email, now, now),
            )

            time.sleep(0.1)

        events = []
        for _ in range(3):
            event = self._consume_event_with_timeout(kafka_consumer, timeout_seconds=10)
            assert event is not None, f"Expected 3 events but got {len(events)}"
            events.append(event)

        for i in range(len(events) - 1):
            assert (
                events[i]["timestamp_micros"] <= events[i + 1]["timestamp_micros"]
            ), "Events should be ordered by timestamp_micros"

    def _consume_event_with_timeout(
        self, consumer: Consumer, timeout_seconds: int = 10
    ) -> Dict[str, Any]:
        """
        Consume a single event from Kafka with timeout.

        Returns None if no event received within timeout.
        """
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                continue

            if msg.error():
                raise KafkaException(msg.error())

            value = json.loads(msg.value().decode("utf-8"))
            consumer.commit()
            return value

        return None
