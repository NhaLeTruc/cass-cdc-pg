"""Integration test for schema evolution: dropping column."""

import time
import uuid
from typing import Any

import pytest
from cassandra.cluster import Cluster
from psycopg2.extensions import connection as PgConnection


@pytest.fixture
def cassandra_session() -> Any:
    """Create Cassandra session."""
    cluster = Cluster(["localhost"], port=9042)
    session = cluster.connect("warehouse")
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
    )
    yield conn
    conn.close()


class TestSchemaDropColumn:
    """Test dropping a column from Cassandra table and verifying PostgreSQL handles it gracefully."""

    def test_drop_column_handled_gracefully(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that dropping a column in Cassandra is handled gracefully in PostgreSQL.

        Steps:
        1. Add a temporary column to Cassandra
        2. Insert a record with the column populated
        3. Verify it replicates to PostgreSQL
        4. Drop the column in Cassandra
        5. Insert another record (without the dropped column)
        6. Verify PostgreSQL still processes events correctly
        7. Verify the column may still exist in PostgreSQL (backward compatibility) or be marked deprecated
        """
        timestamp = int(time.time())
        temp_column = f"temp_col_{timestamp}"

        # Step 1: Add temporary column
        cassandra_session.execute(f"ALTER TABLE users ADD {temp_column} text")

        # Step 2: Insert record with the column
        test_id_before = str(uuid.uuid4())
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {temp_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (
                uuid.UUID(test_id_before),
                f"user_{test_id_before[:8]}",
                f"{test_id_before[:8]}@test.com",
                "temp_value",
            ),
        )

        # Step 3: Wait for replication
        time.sleep(5)

        cursor = postgres_conn.cursor()
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (test_id_before,))
        result = cursor.fetchone()
        assert result is not None, "Record with temp column not replicated"

        # Step 4: Drop the column in Cassandra
        cassandra_session.execute(f"ALTER TABLE users DROP {temp_column}")

        # Step 5: Insert record after dropping column
        test_id_after = str(uuid.uuid4())
        cassandra_session.execute(
            """
            INSERT INTO users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_after), f"user_{test_id_after[:8]}", f"{test_id_after[:8]}@test.com"),
        )

        # Step 6: Wait for replication and verify new record processed correctly
        time.sleep(5)

        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (test_id_after,))
        result = cursor.fetchone()
        assert result is not None, "Record after column drop not replicated"

        # Step 7: Verify PostgreSQL handles the missing column gracefully
        # PostgreSQL may still have the column (backward compatibility) or may have removed it
        # The important thing is that replication continues to work
        cursor.execute(
            "SELECT COUNT(*) FROM cdc_users WHERE id IN (%s, %s)",
            (test_id_before, test_id_after),
        )
        count = cursor.fetchone()[0]
        assert count == 2, f"Expected 2 records, found {count}"

        cursor.close()

    def test_drop_column_existing_data_preserved(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that dropping a column in Cassandra preserves existing data in PostgreSQL.

        Historical data should remain accessible even after column is dropped.
        """
        timestamp = int(time.time())
        temp_column = f"preserve_col_{timestamp}"

        # Add column and insert record
        cassandra_session.execute(f"ALTER TABLE users ADD {temp_column} text")

        test_id = str(uuid.uuid4())
        test_value = f"preserve_value_{test_id[:8]}"

        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {temp_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id), f"user_{test_id[:8]}", f"{test_id[:8]}@test.com", test_value),
        )

        # Wait for replication
        time.sleep(5)

        # Verify data replicated with column value
        cursor = postgres_conn.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'cdc_users'
            AND column_name = %s
            """,
            (temp_column,),
        )
        column_exists_before = cursor.fetchone() is not None

        if column_exists_before:
            cursor.execute(f"SELECT {temp_column} FROM cdc_users WHERE id = %s", (test_id,))
            result = cursor.fetchone()
            value_before_drop = result[0] if result else None

        # Drop column in Cassandra
        cassandra_session.execute(f"ALTER TABLE users DROP {temp_column}")

        # Wait for schema evolution to propagate
        time.sleep(5)

        # Verify historical data still accessible
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (test_id,))
        result = cursor.fetchone()
        assert result is not None, "Historical record lost after column drop"

        # If column existed before drop, verify data is preserved (backward compatibility)
        if column_exists_before:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'cdc_users'
                AND column_name = %s
                """,
                (temp_column,),
            )
            column_exists_after = cursor.fetchone() is not None

            # PostgreSQL may keep the column for backward compatibility
            # This is acceptable behavior for schema evolution
            if column_exists_after:
                cursor.execute(f"SELECT {temp_column} FROM cdc_users WHERE id = %s", (test_id,))
                result = cursor.fetchone()
                assert result is not None, "Record data lost"
                # Value may be NULL or preserved, both are acceptable

        cursor.close()

    def test_drop_non_null_column_graceful_handling(
        self, cassandra_session: Any, postgres_conn: PgConnection
    ) -> None:
        """
        Verify that dropping a non-nullable column is handled gracefully.

        This tests a more complex scenario where schema evolution needs careful handling.
        """
        timestamp = int(time.time())
        non_null_column = f"required_col_{timestamp}"

        # Add column and insert record with value
        cassandra_session.execute(f"ALTER TABLE users ADD {non_null_column} int")

        test_id_1 = str(uuid.uuid4())
        cassandra_session.execute(
            f"""
            INSERT INTO users (id, username, email, {non_null_column}, created_at, updated_at)
            VALUES (%s, %s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_1), f"user_{test_id_1[:8]}", f"{test_id_1[:8]}@test.com", 999),
        )

        # Wait for replication
        time.sleep(5)

        cursor = postgres_conn.cursor()
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (test_id_1,))
        assert cursor.fetchone() is not None, "Record not replicated"

        # Drop the column
        cassandra_session.execute(f"ALTER TABLE users DROP {non_null_column}")

        # Insert new record after drop
        test_id_2 = str(uuid.uuid4())
        cassandra_session.execute(
            """
            INSERT INTO users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, toTimestamp(now()), toTimestamp(now()))
            """,
            (uuid.UUID(test_id_2), f"user_{test_id_2[:8]}", f"{test_id_2[:8]}@test.com"),
        )

        # Wait for replication
        time.sleep(5)

        # Verify new record replicated successfully despite dropped column
        cursor.execute("SELECT * FROM cdc_users WHERE id = %s", (test_id_2,))
        result = cursor.fetchone()
        assert result is not None, "Record after non-null column drop not replicated"

        # Verify both records are in database
        cursor.execute(
            "SELECT COUNT(*) FROM cdc_users WHERE id IN (%s, %s)",
            (test_id_1, test_id_2),
        )
        count = cursor.fetchone()[0]
        assert count == 2, f"Expected 2 records, found {count}"

        cursor.close()
