import pytest
import uuid
import time
from typing import Generator
from datetime import datetime, timedelta
from cassandra.cluster import Cluster, Session
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from .conftest import requires_cdc_pipeline


@pytest.fixture(scope="module")
def cassandra_session() -> Generator[Session, None, None]:
    """Provide Cassandra session with TTL-enabled table."""
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
        CREATE TABLE IF NOT EXISTS warehouse.sessions (
            session_id UUID PRIMARY KEY,
            user_id UUID,
            token TEXT,
            created_at TIMESTAMP
        )
        """
    )

    session.execute("ALTER TABLE warehouse.sessions WITH cdc = true")
    session.execute("ALTER TABLE warehouse.sessions WITH default_time_to_live = 0")

    yield session

    session.execute("DROP TABLE IF EXISTS warehouse.sessions")
    session.execute("DROP KEYSPACE IF EXISTS warehouse")
    cluster.shutdown()


@pytest.fixture(scope="module")
def postgres_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Provide PostgreSQL connection with TTL trigger."""
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
        CREATE TABLE IF NOT EXISTS cdc_sessions (
            session_id UUID PRIMARY KEY,
            user_id UUID,
            token TEXT,
            created_at TIMESTAMPTZ,
            _cdc_deleted BOOLEAN DEFAULT FALSE,
            _cdc_timestamp_micros BIGINT,
            _ttl_expiry_timestamp TIMESTAMPTZ
        )
        """
    )

    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION delete_expired_ttl_records()
        RETURNS TRIGGER AS $$
        BEGIN
            DELETE FROM cdc_sessions
            WHERE _ttl_expiry_timestamp IS NOT NULL
              AND _ttl_expiry_timestamp < NOW();
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    cursor.execute(
        """
        DROP TRIGGER IF EXISTS ttl_expiry_cleanup ON cdc_sessions;
        """
    )

    cursor.execute(
        """
        CREATE TRIGGER ttl_expiry_cleanup
        AFTER INSERT OR UPDATE ON cdc_sessions
        FOR EACH STATEMENT
        EXECUTE FUNCTION delete_expired_ttl_records();
        """
    )

    conn.commit()

    yield conn

    cursor.execute("DROP TRIGGER IF EXISTS ttl_expiry_cleanup ON cdc_sessions")
    cursor.execute("DROP FUNCTION IF EXISTS delete_expired_ttl_records()")
    cursor.execute("DROP TABLE IF EXISTS cdc_sessions")
    conn.commit()
    conn.close()


class TestTTLPreservation:
    """
    Integration test for TTL (Time-To-Live) preservation from Cassandra to PostgreSQL.

    Validates that:
    1. Records with TTL have _ttl_expiry_timestamp set correctly
    2. Records without TTL have NULL _ttl_expiry_timestamp
    3. Expired records are automatically deleted by PostgreSQL trigger
    """

    @requires_cdc_pipeline
    def test_record_with_ttl_has_expiry_timestamp(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that Cassandra record with TTL sets _ttl_expiry_timestamp in PostgreSQL."""
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = f"token_{int(time.time())}"
        ttl_seconds = 3600

        cassandra_session.execute(
            """
            INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            USING TTL %s
            """,
            (session_id, user_id, token, datetime.utcnow(), ttl_seconds),
        )

        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should be replicated to PostgreSQL"
        assert (
            row["_ttl_expiry_timestamp"] is not None
        ), "TTL expiry timestamp should be set"

        expected_expiry = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        time_diff = abs(
            (row["_ttl_expiry_timestamp"] - expected_expiry).total_seconds()
        )

        assert (
            time_diff < 60
        ), f"TTL expiry timestamp should be approximately {expected_expiry}, but difference is {time_diff}s"

    @requires_cdc_pipeline
    def test_record_without_ttl_has_null_expiry_timestamp(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that Cassandra record without TTL has NULL _ttl_expiry_timestamp."""
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = f"token_{int(time.time())}"

        cassandra_session.execute(
            """
            INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, user_id, token, datetime.utcnow()),
        )

        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should be replicated to PostgreSQL"
        assert (
            row["_ttl_expiry_timestamp"] is None
        ), "TTL expiry timestamp should be NULL for records without TTL"

    @requires_cdc_pipeline
    def test_expired_ttl_record_is_auto_deleted(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that records with expired TTL are automatically deleted by trigger."""
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = f"token_{int(time.time())}"
        ttl_seconds = 2

        cassandra_session.execute(
            """
            INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            USING TTL %s
            """,
            (session_id, user_id, token, datetime.utcnow(), ttl_seconds),
        )

        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should initially exist in PostgreSQL"

        print(f"Waiting {ttl_seconds + 2} seconds for TTL expiration...")
        time.sleep(ttl_seconds + 2)

        dummy_session_id = uuid.uuid4()
        cursor.execute(
            """
            INSERT INTO cdc_sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (dummy_session_id, user_id, "dummy", datetime.utcnow()),
        )
        postgres_connection.commit()

        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert (
            row is None
        ), "Record with expired TTL should be deleted by trigger after any INSERT/UPDATE"

    @requires_cdc_pipeline
    def test_ttl_expiry_timestamp_calculation_accuracy(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that TTL expiry timestamp is calculated accurately."""
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = f"token_{int(time.time())}"
        ttl_seconds = 7200

        insert_time = datetime.utcnow()

        cassandra_session.execute(
            """
            INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            USING TTL %s
            """,
            (session_id, user_id, token, insert_time, ttl_seconds),
        )

        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should be replicated"

        expected_expiry = insert_time + timedelta(seconds=ttl_seconds)
        actual_expiry = row["_ttl_expiry_timestamp"]

        time_diff = abs((actual_expiry - expected_expiry).total_seconds())

        assert (
            time_diff < 10
        ), f"TTL expiry calculation should be accurate within 10s, but difference is {time_diff}s"

    @requires_cdc_pipeline
    def test_ttl_update_changes_expiry_timestamp(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that updating a record with new TTL changes the expiry timestamp."""
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = f"token_{int(time.time())}"
        initial_ttl = 3600

        cassandra_session.execute(
            """
            INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            USING TTL %s
            """,
            (session_id, user_id, token, datetime.utcnow(), initial_ttl),
        )

        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should exist"
        initial_expiry = row["_ttl_expiry_timestamp"]

        time.sleep(1)

        new_ttl = 7200
        new_token = f"updated_{token}"

        cassandra_session.execute(
            """
            UPDATE warehouse.sessions
            USING TTL %s
            SET token = %s
            WHERE session_id = %s
            """,
            (new_ttl, new_token, session_id),
        )

        time.sleep(5)

        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should still exist after update"
        updated_expiry = row["_ttl_expiry_timestamp"]

        assert (
            updated_expiry > initial_expiry
        ), "Updated TTL should result in later expiry timestamp"

        expected_diff = new_ttl - initial_ttl
        actual_diff = (updated_expiry - initial_expiry).total_seconds()

        assert (
            abs(actual_diff - expected_diff) < 60
        ), f"Expiry timestamp difference should be approximately {expected_diff}s"

    @requires_cdc_pipeline
    def test_multiple_records_with_different_ttls(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """Test that multiple records with different TTLs have correct expiry timestamps."""
        session_ids = []
        ttls = [60, 300, 3600, 7200, 0]

        for ttl in ttls:
            session_id = uuid.uuid4()
            session_ids.append((session_id, ttl))
            user_id = uuid.uuid4()
            token = f"token_{ttl}_{int(time.time())}"

            if ttl == 0:
                cassandra_session.execute(
                    """
                    INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (session_id, user_id, token, datetime.utcnow()),
                )
            else:
                cassandra_session.execute(
                    """
                    INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
                    VALUES (%s, %s, %s, %s)
                    USING TTL %s
                    """,
                    (session_id, user_id, token, datetime.utcnow(), ttl),
                )

        time.sleep(10)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)

        for session_id, ttl in session_ids:
            cursor.execute(
                "SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,)
            )
            row = cursor.fetchone()

            assert row is not None, f"Record with TTL {ttl} should be replicated"

            if ttl == 0:
                assert (
                    row["_ttl_expiry_timestamp"] is None
                ), f"Record without TTL should have NULL expiry"
            else:
                assert (
                    row["_ttl_expiry_timestamp"] is not None
                ), f"Record with TTL {ttl} should have expiry timestamp"

                expected_expiry = datetime.utcnow() + timedelta(seconds=ttl)
                time_diff = abs(
                    (row["_ttl_expiry_timestamp"] - expected_expiry).total_seconds()
                )

                assert (
                    time_diff < 120
                ), f"TTL {ttl} expiry should be accurate within 2 minutes"

    @pytest.mark.slow
    def test_ttl_expiration_after_1_hour(
        self,
        cassandra_session: Session,
        postgres_connection: psycopg2.extensions.connection,
    ) -> None:
        """
        SLOW TEST: Test that record with 1-hour TTL is deleted after 1 hour.

        This test is marked as slow and should only be run in comprehensive test suites.
        """
        pytest.skip("Skipping 1-hour TTL test - too slow for standard test runs")

        session_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = f"token_{int(time.time())}"
        ttl_seconds = 3600

        cassandra_session.execute(
            """
            INSERT INTO warehouse.sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            USING TTL %s
            """,
            (session_id, user_id, token, datetime.utcnow(), ttl_seconds),
        )

        time.sleep(5)

        cursor = postgres_connection.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is not None, "Record should exist initially"

        print("Waiting 1 hour for TTL expiration...")
        time.sleep(3600 + 10)

        cursor.execute(
            """
            INSERT INTO cdc_sessions (session_id, user_id, token, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (uuid.uuid4(), user_id, "trigger", datetime.utcnow()),
        )
        postgres_connection.commit()

        cursor.execute("SELECT * FROM cdc_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()

        assert row is None, "Record should be deleted after 1-hour TTL expiration"
