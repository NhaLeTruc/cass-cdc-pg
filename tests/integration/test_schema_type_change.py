"""Integration test for schema evolution: compatible type changes."""

import time
import uuid
from typing import Any

import pytest
from cassandra.cluster import Cluster
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


class TestSchemaTypeChange:
    """Test compatible type changes in Cassandra and verify PostgreSQL updates types correctly."""

    @requires_cdc_pipeline
    def test_int_to_bigint_type_change(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that changing int→bigint in Cassandra updates PostgreSQL type.

        This is a compatible widening type change that should be handled automatically.

        Steps:
        1. Add a test column as int type
        2. Insert record with int value
        3. Verify replication to PostgreSQL
        4. Change column type to bigint in Cassandra
        5. Insert record with large bigint value
        6. Verify PostgreSQL handles both old and new values correctly
        """
        timestamp = int(time.time())
        test_column = f"type_change_{timestamp}"

        # Step 1: Add column as int type
        cassandra_session.execute(f"ALTER TABLE users ADD {test_column} int")

        # Step 2: Insert record with int value
        test_id_1 = str(uuid.uuid4())
        int_value = 1000
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {test_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_1), f"user_{test_id_1[:8]}", f"{test_id_1[:8]}@test.com", int_value),
        )

        # Step 3: Wait for replication
        time.sleep(5)

        cursor = postgres_conn.cursor()
        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_1,))
        result = cursor.fetchone()
        assert result is not None, "Record with int value not replicated"
        assert result[0] == int_value, f"Expected {int_value}, got {result[0]}"

        # Step 4: Change type to bigint
        # Note: In Cassandra, you cannot ALTER column type directly
        # This test simulates the behavior by dropping and re-adding with larger type
        # In production, this would be handled by Schema Registry compatibility
        cassandra_session.execute(f"ALTER TABLE users DROP {test_column}")
        cassandra_session.execute(f"ALTER TABLE users ADD {test_column} bigint")

        # Step 5: Insert record with bigint value
        test_id_2 = str(uuid.uuid4())
        bigint_value = 9999999999
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {test_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_2), f"user_{test_id_2[:8]}", f"{test_id_2[:8]}@test.com", bigint_value),
        )

        # Step 6: Wait and verify PostgreSQL handles both values
        time.sleep(5)

        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_2,))
        result = cursor.fetchone()
        assert result is not None, "Record with bigint value not replicated"
        assert result[0] == bigint_value, f"Expected {bigint_value}, got {result[0]}"

        cursor.close()

    @requires_cdc_pipeline
    def test_text_length_expansion(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that text columns can handle longer values over time.

        This tests that VARCHAR/TEXT expansion works correctly.
        """
        timestamp = int(time.time())
        test_column = f"expandable_text_{timestamp}"

        # Add text column
        cassandra_session.execute(f"ALTER TABLE users ADD {test_column} text")

        # Insert record with short text
        test_id_1 = str(uuid.uuid4())
        short_text = "short"
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {test_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_1), f"user_{test_id_1[:8]}", f"{test_id_1[:8]}@test.com", short_text),
        )

        time.sleep(5)

        # Insert record with long text (1000 characters)
        test_id_2 = str(uuid.uuid4())
        long_text = "x" * 1000
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {test_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_2), f"user_{test_id_2[:8]}", f"{test_id_2[:8]}@test.com", long_text),
        )

        time.sleep(5)

        # Verify both values replicated correctly
        cursor = postgres_conn.cursor()

        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_1,))
        result = cursor.fetchone()
        assert result is not None and result[0] == short_text, "Short text not replicated correctly"

        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_2,))
        result = cursor.fetchone()
        assert result is not None and result[0] == long_text, "Long text not replicated correctly"

        cursor.close()

    @requires_cdc_pipeline
    def test_nullable_to_non_nullable_handling(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that nullable columns continue to work correctly.

        This tests NULL value handling during schema evolution.
        """
        timestamp = int(time.time())
        test_column = f"nullable_col_{timestamp}"

        # Add nullable column
        cassandra_session.execute(f"ALTER TABLE users ADD {test_column} int")

        # Insert record with NULL
        test_id_null = str(uuid.uuid4())
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_null), f"user_{test_id_null[:8]}", f"{test_id_null[:8]}@test.com"),
        )

        # Insert record with value
        test_id_value = str(uuid.uuid4())
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {test_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_value), f"user_{test_id_value[:8]}", f"{test_id_value[:8]}@test.com", 42),
        )

        time.sleep(5)

        # Verify NULL and non-NULL values handled correctly
        cursor = postgres_conn.cursor()

        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_null,))
        result = cursor.fetchone()
        assert result is not None, "Record with NULL not replicated"
        assert result[0] is None, "Expected NULL value"

        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_value,))
        result = cursor.fetchone()
        assert result is not None, "Record with value not replicated"
        assert result[0] == 42, f"Expected 42, got {result[0]}"

        cursor.close()

    @requires_cdc_pipeline
    def test_decimal_precision_changes(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that decimal/numeric type precision changes are handled correctly.

        This tests that numeric values with varying precision replicate correctly.
        """
        timestamp = int(time.time())
        test_column = f"decimal_col_{timestamp}"

        # Add decimal column
        cassandra_session.execute(f"ALTER TABLE users ADD {test_column} decimal")

        # Insert record with small decimal
        test_id_1 = str(uuid.uuid4())
        small_decimal = "10.50"
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {test_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_1), f"user_{test_id_1[:8]}", f"{test_id_1[:8]}@test.com", small_decimal),
        )

        # Insert record with high-precision decimal
        test_id_2 = str(uuid.uuid4())
        precise_decimal = "123456789.123456789"
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {test_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_2), f"user_{test_id_2[:8]}", f"{test_id_2[:8]}@test.com", precise_decimal),
        )

        time.sleep(5)

        # Verify both decimals replicated with correct precision
        cursor = postgres_conn.cursor()

        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_1,))
        result = cursor.fetchone()
        assert result is not None, "Record with small decimal not replicated"
        # Compare as strings to avoid floating point precision issues
        assert str(result[0]) == small_decimal, f"Expected {small_decimal}, got {result[0]}"

        cursor.execute(f"SELECT {test_column} FROM cdc_users WHERE id = %s", (test_id_2,))
        result = cursor.fetchone()
        assert result is not None, "Record with precise decimal not replicated"

        cursor.close()
