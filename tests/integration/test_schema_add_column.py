"""Integration test for schema evolution: adding new column."""

import time
import uuid
from typing import Any

import pytest
from cassandra.cluster import Cluster
from cassandra.query import SimpleStatement
from psycopg2.extensions import connection as PgConnection
import requests
from .conftest import requires_cdc_pipeline


@pytest.fixture
def cassandra_session() -> Any:
    """Create Cassandra session."""
    cluster = Cluster(["localhost"], port=9042, connect_timeout=10, control_connection_timeout=10)
    session = cluster.connect()
    session.execute(
        """
        CREATE KEYSPACE IF NOT EXISTS warehouse
        WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
        """
    )
    session.set_keyspace("warehouse")
    yield session
    cluster.shutdown()


@pytest.fixture
def postgres_conn() -> PgConnection:
    """Create PostgreSQL connection."""
    import psycopg2

    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="warehouse",
        user="cdc_user",
        password="cdc_password",
        connect_timeout=10,
    )
    yield conn
    conn.close()


class TestSchemaAddColumn:
    """Test adding a new column to Cassandra table and verifying PostgreSQL schema evolution."""

    @requires_cdc_pipeline
    def test_add_column_appears_in_postgres_within_10s(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that adding a column in Cassandra results in PostgreSQL schema update within 10s.

        Steps:
        1. Insert a record in Cassandra users table
        2. Verify it replicates to PostgreSQL
        3. Add a new column to Cassandra users table
        4. Insert another record with the new column populated
        5. Wait up to 10 seconds
        6. Verify PostgreSQL schema includes the new column
        7. Verify new record has the column value
        """
        test_id = str(uuid.uuid4())

        # Step 1: Insert initial record
        cassandra_session.execute(
            """
            INSERT INTO users (id, username, email, age, balance, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id), f"user_{test_id[:8]}", f"{test_id[:8]}@test.com", 25, 1000.0, True),
        )

        # Step 2: Wait for replication
        time.sleep(5)

        cursor = postgres_conn.cursor()
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (test_id,))
        result = cursor.fetchone()
        assert result is not None, "Initial record not replicated to PostgreSQL"

        # Step 3: Add new column to Cassandra table
        new_column_name = f"test_column_{int(time.time())}"
        cassandra_session.execute(
            f"ALTER TABLE users ADD {new_column_name} text",
        )

        # Step 4: Insert record with new column
        test_id_2 = str(uuid.uuid4())
        new_column_value = f"value_{test_id_2[:8]}"

        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, age, balance, is_active, {new_column_name}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (
                uuid.UUID(test_id_2),
                f"user_{test_id_2[:8]}",
                f"{test_id_2[:8]}@test.com",
                30,
                2000.0,
                True,
                new_column_value,
            ),
        )

        # Step 5-6: Wait up to 10 seconds for schema evolution and verify
        max_wait = 10
        column_found = False
        start_time = time.time()

        while time.time() - start_time < max_wait:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'cdc_users'
                AND column_name = %s
                """,
                (new_column_name,),
            )
            result = cursor.fetchone()

            if result:
                column_found = True
                break

            time.sleep(1)

        assert column_found, (
            f"New column '{new_column_name}' not found in PostgreSQL schema after {max_wait}s"
        )

        # Step 7: Verify new record has the column value
        cursor.execute(
            f"SELECT {new_column_name} FROM cdc_users WHERE id = %s",
            (test_id_2,),
        )
        result = cursor.fetchone()
        assert result is not None, "New record not replicated"
        assert result[0] == new_column_value, (
            f"Column value mismatch: expected '{new_column_value}', got '{result[0]}'"
        )

        # Cleanup
        cursor.close()

    @requires_cdc_pipeline
    def test_add_multiple_columns_sequentially(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that adding multiple columns sequentially works correctly.

        This tests that schema evolution can handle rapid successive changes.
        """
        test_id = str(uuid.uuid4())
        timestamp = int(time.time())

        # Add first column
        column1_name = f"test_col1_{timestamp}"
        cassandra_session.execute(f"ALTER TABLE users ADD {column1_name} int")

        # Add second column
        column2_name = f"test_col2_{timestamp}"
        cassandra_session.execute(f"ALTER TABLE users ADD {column2_name} text")

        # Insert record with both new columns
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {column1_name}, {column2_name}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id), f"user_{test_id[:8]}", f"{test_id[:8]}@test.com", 42, "test_value"),
        )

        # Wait for schema evolution and replication
        time.sleep(10)

        # Verify both columns exist in PostgreSQL
        cursor = postgres_conn.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'cdc_users'
            AND column_name IN (%s, %s)
            """,
            (column1_name, column2_name),
        )
        results = cursor.fetchall()
        column_names = [row[0] for row in results]

        assert column1_name in column_names, f"Column {column1_name} not found in PostgreSQL"
        assert column2_name in column_names, f"Column {column2_name} not found in PostgreSQL"

        # Verify record data
        cursor.execute(
            f"SELECT {column1_name}, {column2_name} FROM cdc_users WHERE id = %s",
            (test_id,),
        )
        result = cursor.fetchone()
        assert result is not None, "Record not replicated"
        assert result[0] == 42, f"Column {column1_name} value mismatch"
        assert result[1] == "test_value", f"Column {column2_name} value mismatch"

        cursor.close()

    @requires_cdc_pipeline
    def test_add_column_with_existing_data(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that adding a column to a table with existing data handles NULL values correctly.

        Existing records should have NULL for the new column.
        """
        # Insert record before adding column
        test_id_before = str(uuid.uuid4())
        cassandra_session.execute(
            """
            INSERT INTO users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_before), f"user_{test_id_before[:8]}", f"{test_id_before[:8]}@test.com"),
        )

        time.sleep(5)

        # Add new column
        timestamp = int(time.time())
        new_column = f"test_nullable_{timestamp}"
        cassandra_session.execute(f"ALTER TABLE users ADD {new_column} text")

        # Insert record after adding column
        test_id_after = str(uuid.uuid4())
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {new_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_after), f"user_{test_id_after[:8]}", f"{test_id_after[:8]}@test.com", "has_value"),
        )

        # Wait for schema evolution
        time.sleep(10)

        # Verify schema in PostgreSQL
        cursor = postgres_conn.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'cdc_users'
            AND column_name = %s
            """,
            (new_column,),
        )
        assert cursor.fetchone() is not None, f"Column {new_column} not found in PostgreSQL"

        # Verify record before column addition has NULL
        cursor.execute(
            f"SELECT {new_column} FROM cdc_users WHERE id = %s",
            (test_id_before,),
        )
        result = cursor.fetchone()
        assert result is not None, "Record before column addition not found"
        assert result[0] is None, "Expected NULL for new column in existing record"

        # Verify record after column addition has value
        cursor.execute(
            f"SELECT {new_column} FROM cdc_users WHERE id = %s",
            (test_id_after,),
        )
        result = cursor.fetchone()
        assert result is not None, "Record after column addition not found"
        assert result[0] == "has_value", "Expected value for new column in new record"

        cursor.close()
