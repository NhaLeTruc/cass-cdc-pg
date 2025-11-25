import pytest
import uuid
import time
import requests
from typing import Generator
from datetime import datetime
from cassandra.cluster import Cluster, Session
import psycopg2
from psycopg2.extras import RealDictCursor


def check_cdc_pipeline_ready() -> bool:
    """Check if full CDC pipeline is deployed and ready."""
    try:
        response = requests.get("http://localhost:8083/connectors", timeout=5)
        connectors = response.json()
        # Need both cassandra-source and postgres-sink for end-to-end tests
        return "cassandra-source" in connectors and "postgres-sink" in connectors
    except Exception:
        return False


@pytest.fixture(scope="module")
def cassandra_session() -> Generator[Session, None, None]:
    """Provide Cassandra session for source data operations."""
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
def postgres_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Provide PostgreSQL connection for verifying replicated data."""
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="warehouse",
        user="cdc_user",
        password="cdc_password",
        connect_timeout=10,
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


class TestEndToEndReplication:
    """
    End-to-end integration test for complete CDC pipeline.

    Tests that INSERT, UPDATE, DELETE operations in Cassandra are replicated
    to PostgreSQL within 5 seconds through the complete pipeline:
    Cassandra → Debezium → Kafka → JDBC Sink → PostgreSQL
    """

    @pytest.mark.skipif(
        not check_cdc_pipeline_ready(),
        reason="CDC pipeline connectors not deployed - run 'make deploy-connectors' first"
    )
    def test_insert_operation_replicates_within_5_seconds(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that INSERT in Cassandra replicates to PostgreSQL within 5 seconds."""
        user_id = uuid.uuid4()
        username = f"e2e_insert_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        start_time = time.time()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        self._wait_for_replication(postgres_connection, user_id, timeout_seconds=5)

        elapsed_time = time.time() - start_time

        assert elapsed_time < 5, f"Replication took {elapsed_time:.2f}s, expected <5s"

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (user_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should exist in PostgreSQL"
        assert row["id"] == user_id, "User ID should match"
        assert row["username"] == username, "Username should match"
        assert row["email"] == email, "Email should match"
        assert row["_cdc_deleted"] is False, "Record should not be marked as deleted"

    @pytest.mark.skipif(
        not check_cdc_pipeline_ready(),
        reason="CDC pipeline connectors not deployed - run 'make deploy-connectors' first"
    )
    def test_update_operation_replicates_within_5_seconds(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that UPDATE in Cassandra replicates to PostgreSQL within 5 seconds."""
        user_id = uuid.uuid4()
        username = f"e2e_update_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        self._wait_for_replication(postgres_connection, user_id, timeout_seconds=5)

        new_email = f"updated_{email}"
        start_time = time.time()

        cassandra_session.execute(
            """
            UPDATE warehouse.users
            SET email = %s, updated_at = %s
            WHERE id = %s
            """,
            (new_email, datetime.utcnow(), user_id),
        )

        self._wait_for_email_update(postgres_connection, user_id, new_email, timeout_seconds=5)

        elapsed_time = time.time() - start_time

        assert elapsed_time < 5, f"Update replication took {elapsed_time:.2f}s, expected <5s"

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (user_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should exist in PostgreSQL"
        assert row["email"] == new_email, "Email should be updated"

    @pytest.mark.skipif(
        not check_cdc_pipeline_ready(),
        reason="CDC pipeline connectors not deployed - run 'make deploy-connectors' first"
    )
    def test_delete_operation_replicates_within_5_seconds(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that DELETE in Cassandra replicates to PostgreSQL within 5 seconds."""
        user_id = uuid.uuid4()
        username = f"e2e_delete_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        self._wait_for_replication(postgres_connection, user_id, timeout_seconds=5)

        start_time = time.time()

        cassandra_session.execute(
            """
            DELETE FROM warehouse.users WHERE id = %s
            """,
            (user_id,),
        )

        self._wait_for_deletion(postgres_connection, user_id, timeout_seconds=5)

        elapsed_time = time.time() - start_time

        assert elapsed_time < 5, f"Delete replication took {elapsed_time:.2f}s, expected <5s"

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (user_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should still exist (soft delete)"
        assert row["_cdc_deleted"] is True, "Record should be marked as deleted"

    @pytest.mark.skipif(
        not check_cdc_pipeline_ready(),
        reason="CDC pipeline connectors not deployed - run 'make deploy-connectors' first"
    )
    def test_sequence_of_operations_all_replicate_correctly(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that a sequence of INSERT→UPDATE→DELETE all replicate correctly."""
        user_id = uuid.uuid4()
        username = f"e2e_sequence_{int(time.time())}"
        email = f"{username}@example.com"
        now = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, email, now, now),
        )

        self._wait_for_replication(postgres_connection, user_id, timeout_seconds=5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        assert row is not None, "INSERT should replicate"
        assert row["email"] == email, "Original email should be present"
        initial_timestamp = row["_cdc_timestamp_micros"]

        time.sleep(0.1)

        new_email = f"updated_{email}"
        cassandra_session.execute(
            """
            UPDATE warehouse.users
            SET email = %s, updated_at = %s
            WHERE id = %s
            """,
            (new_email, datetime.utcnow(), user_id),
        )

        self._wait_for_email_update(postgres_connection, user_id, new_email, timeout_seconds=5)

        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        assert row is not None, "UPDATE should replicate"
        assert row["email"] == new_email, "Email should be updated"
        update_timestamp = row["_cdc_timestamp_micros"]
        assert (
            update_timestamp > initial_timestamp
        ), "Update timestamp should be greater than initial"

        time.sleep(0.1)

        cassandra_session.execute(
            """
            DELETE FROM warehouse.users WHERE id = %s
            """,
            (user_id,),
        )

        self._wait_for_deletion(postgres_connection, user_id, timeout_seconds=5)

        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        assert row is not None, "DELETE should replicate as soft delete"
        assert row["_cdc_deleted"] is True, "Record should be marked as deleted"
        delete_timestamp = row["_cdc_timestamp_micros"]
        assert (
            delete_timestamp > update_timestamp
        ), "Delete timestamp should be greater than update timestamp"

    @pytest.mark.skipif(
        not check_cdc_pipeline_ready(),
        reason="CDC pipeline connectors not deployed - run 'make deploy-connectors' first"
    )
    def test_bulk_insert_replicates_all_records(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that bulk INSERT operations replicate all records correctly."""
        user_ids = []
        num_records = 100

        start_time = time.time()

        for i in range(num_records):
            user_id = uuid.uuid4()
            user_ids.append(user_id)
            username = f"bulk_{int(time.time())}_{i}"
            email = f"{username}@example.com"
            now = datetime.utcnow()

            cassandra_session.execute(
                """
                INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, username, email, now, now),
            )

        max_wait = 10
        while time.time() - start_time < max_wait:
            cursor = postgres_connection.cursor()
            placeholders = ",".join(["%s"] * len(user_ids))
            cursor.execute(
                f"SELECT COUNT(*) FROM cdc_users WHERE id IN ({placeholders})",
                user_ids,
            )
            count = cursor.fetchone()[0]

            if count == num_records:
                break

            time.sleep(0.5)

        elapsed_time = time.time() - start_time

        cursor = postgres_connection.cursor()
        placeholders = ",".join(["%s"] * len(user_ids))
        cursor.execute(
            f"SELECT COUNT(*) FROM cdc_users WHERE id IN ({placeholders})",
            user_ids,
        )
        final_count = cursor.fetchone()[0]

        assert (
            final_count == num_records
        ), f"Expected {num_records} records, found {final_count}"
        assert elapsed_time < max_wait, f"Bulk replication took {elapsed_time:.2f}s"

    @pytest.mark.skipif(
        not check_cdc_pipeline_ready(),
        reason="CDC pipeline connectors not deployed - run 'make deploy-connectors' first"
    )
    def test_latency_meets_p95_requirement(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that P95 latency for replication is under 2 seconds."""
        latencies = []
        num_samples = 20

        for i in range(num_samples):
            user_id = uuid.uuid4()
            username = f"latency_{int(time.time())}_{i}"
            email = f"{username}@example.com"
            now = datetime.utcnow()

            start_time = time.time()

            cassandra_session.execute(
                """
                INSERT INTO warehouse.users (id, username, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, username, email, now, now),
            )

            self._wait_for_replication(postgres_connection, user_id, timeout_seconds=10)

            elapsed_time = time.time() - start_time
            latencies.append(elapsed_time)

            time.sleep(0.1)

        latencies.sort()
        p95_index = int(len(latencies) * 0.95)
        p95_latency = latencies[p95_index]

        assert (
            p95_latency < 2.0
        ), f"P95 latency is {p95_latency:.2f}s, expected <2s (FR-023 requirement)"

    def _wait_for_replication(
        self,
        conn: psycopg2.extensions.connection,
        user_id: uuid.UUID,
        timeout_seconds: int = 5,
    ) -> None:
        """Wait for record to appear in PostgreSQL."""
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM cdc_users WHERE id = %s", (user_id,))
            result = cursor.fetchone()

            if result is not None:
                return

            time.sleep(0.1)

        raise TimeoutError(
            f"Record {user_id} did not replicate to PostgreSQL within {timeout_seconds}s"
        )

    def _wait_for_email_update(
        self,
        conn: psycopg2.extensions.connection,
        user_id: uuid.UUID,
        expected_email: str,
        timeout_seconds: int = 5,
    ) -> None:
        """Wait for email to be updated in PostgreSQL."""
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM cdc_users WHERE id = %s", (user_id,))
            result = cursor.fetchone()

            if result is not None and result[0] == expected_email:
                return

            time.sleep(0.1)

        raise TimeoutError(
            f"Email for {user_id} did not update to {expected_email} within {timeout_seconds}s"
        )

    def _wait_for_deletion(
        self,
        conn: psycopg2.extensions.connection,
        user_id: uuid.UUID,
        timeout_seconds: int = 5,
    ) -> None:
        """Wait for record to be marked as deleted in PostgreSQL."""
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT _cdc_deleted FROM cdc_users WHERE id = %s", (user_id,)
            )
            result = cursor.fetchone()

            if result is not None and result[0] is True:
                return

            time.sleep(0.1)

        raise TimeoutError(
            f"Record {user_id} was not marked as deleted within {timeout_seconds}s"
        )
