import pytest
import uuid
import time
import subprocess
from typing import List
from datetime import datetime
from cassandra.cluster import Cluster
import psycopg2


class TestCheckpointResume:
    """
    Integration test for checkpoint resume after restart.

    Verifies that the CDC pipeline can resume processing from checkpoints
    after service restarts without data loss or duplication.
    """

    @pytest.fixture(scope="function")
    def cassandra_connection(self):
        """Provide Cassandra connection."""
        cluster = Cluster(["localhost"], port=9042)
        session = cluster.connect("warehouse")
        yield session
        cluster.shutdown()

    @pytest.fixture(scope="function")
    def postgres_connection(self):
        """Provide PostgreSQL connection."""
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="cdc_target",
            user="cdc_user",
            password="cdc_password",
        )
        yield conn
        conn.close()

    def test_checkpoint_resume_after_restart_no_data_loss(
        self,
        cassandra_connection,
        postgres_connection,
    ) -> None:
        """
        Test that data is not lost after restarting services.

        Steps:
        1. Insert 1000 records into Cassandra
        2. Wait for 500 records to replicate
        3. Stop Kafka Connect
        4. Insert 500 more records
        5. Restart Kafka Connect
        6. Verify all 1000 records are in PostgreSQL
        """
        user_ids = []
        total_records = 100
        checkpoint_at = 50

        for i in range(checkpoint_at):
            user_id = uuid.uuid4()
            user_ids.append(user_id)
            cassandra_connection.execute(
                """
                INSERT INTO users (id, username, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    f"user_{i}",
                    f"user_{i}@example.com",
                    datetime.utcnow(),
                    datetime.utcnow(),
                ),
            )

        time.sleep(10)

        cursor = postgres_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM cdc_users WHERE id = ANY(%s)", (user_ids,))
        count_before_restart = cursor.fetchone()[0]

        assert count_before_restart >= checkpoint_at * 0.9, (
            f"Expected at least {int(checkpoint_at * 0.9)} records before restart, "
            f"found {count_before_restart}"
        )

        self._run_docker_compose(["stop", "kafka-connect"])
        time.sleep(5)

        for i in range(checkpoint_at, total_records):
            user_id = uuid.uuid4()
            user_ids.append(user_id)
            cassandra_connection.execute(
                """
                INSERT INTO users (id, username, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    f"user_{i}",
                    f"user_{i}@example.com",
                    datetime.utcnow(),
                    datetime.utcnow(),
                ),
            )

        self._run_docker_compose(["start", "kafka-connect"])

        max_wait = 30
        start_time = time.time()

        while time.time() - start_time < max_wait:
            cursor.execute("SELECT COUNT(*) FROM cdc_users WHERE id = ANY(%s)", (user_ids,))
            final_count = cursor.fetchone()[0]

            if final_count >= total_records:
                break

            time.sleep(2)

        cursor.execute("SELECT COUNT(*) FROM cdc_users WHERE id = ANY(%s)", (user_ids,))
        final_count = cursor.fetchone()[0]

        assert final_count == total_records, (
            f"Expected {total_records} records after restart, found {final_count}. "
            f"Data loss detected!"
        )

    def test_checkpoint_resume_no_duplicates(
        self,
        cassandra_connection,
        postgres_connection,
    ) -> None:
        """
        Test that no duplicate records are created after restart.

        Verifies that checkpointing prevents duplicate processing.
        """
        user_ids = []
        num_records = 50

        for i in range(num_records):
            user_id = uuid.uuid4()
            user_ids.append(user_id)
            cassandra_connection.execute(
                """
                INSERT INTO users (id, username, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    f"dedup_user_{i}",
                    f"dedup_{i}@example.com",
                    datetime.utcnow(),
                    datetime.utcnow(),
                ),
            )

        time.sleep(10)

        self._run_docker_compose(["restart", "kafka-connect"])

        time.sleep(15)

        cursor = postgres_connection.cursor()

        for user_id in user_ids:
            cursor.execute(
                "SELECT COUNT(*) FROM cdc_users WHERE id = %s",
                (user_id,),
            )
            count = cursor.fetchone()[0]

            assert count <= 1, (
                f"User {user_id} appears {count} times in PostgreSQL. "
                f"Duplicate detected!"
            )

    def test_checkpoint_persisted_in_database(
        self,
        cassandra_connection,
        postgres_connection,
    ) -> None:
        """Test that checkpoints are persisted in the _cdc_checkpoints table."""
        user_id = uuid.uuid4()

        cassandra_connection.execute(
            """
            INSERT INTO users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                user_id,
                "checkpoint_test",
                "checkpoint@example.com",
                datetime.utcnow(),
                datetime.utcnow(),
            ),
        )

        time.sleep(10)

        cursor = postgres_connection.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM _cdc_checkpoints
            WHERE source_table = 'users'
            AND status = 'COMPLETED'
            """
        )
        checkpoint_count = cursor.fetchone()[0]

        assert checkpoint_count > 0, (
            "No checkpoints found in _cdc_checkpoints table"
        )

    def test_kafka_offset_tracking(
        self,
        cassandra_connection,
        postgres_connection,
    ) -> None:
        """Test that Kafka offsets are tracked in checkpoints."""
        user_id = uuid.uuid4()

        cassandra_connection.execute(
            """
            INSERT INTO users (id, username, email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                user_id,
                "offset_test",
                "offset@example.com",
                datetime.utcnow(),
                datetime.utcnow(),
            ),
        )

        time.sleep(10)

        cursor = postgres_connection.cursor()
        cursor.execute(
            """
            SELECT kafka_offset, kafka_partition
            FROM _cdc_checkpoints
            WHERE source_table = 'users'
            AND kafka_offset IS NOT NULL
            ORDER BY checkpoint_timestamp DESC
            LIMIT 1
            """
        )
        result = cursor.fetchone()

        assert result is not None, "No checkpoint with Kafka offset found"

        kafka_offset, kafka_partition = result

        assert kafka_offset >= 0, "Kafka offset should be >= 0"
        assert kafka_partition >= 0, "Kafka partition should be >= 0"

    def test_resume_from_specific_checkpoint(
        self,
        cassandra_connection,
        postgres_connection,
    ) -> None:
        """Test that pipeline can resume from a specific checkpoint."""
        initial_user_ids = []

        for i in range(20):
            user_id = uuid.uuid4()
            initial_user_ids.append(user_id)
            cassandra_connection.execute(
                """
                INSERT INTO users (id, username, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    f"resume_user_{i}",
                    f"resume_{i}@example.com",
                    datetime.utcnow(),
                    datetime.utcnow(),
                ),
            )

        time.sleep(10)

        cursor = postgres_connection.cursor()
        cursor.execute(
            """
            SELECT last_processed_event_id, last_processed_timestamp_micros
            FROM _cdc_checkpoints
            WHERE source_table = 'users'
            ORDER BY checkpoint_timestamp DESC
            LIMIT 1
            """
        )
        checkpoint = cursor.fetchone()

        assert checkpoint is not None, "No checkpoint found before restart"

        last_event_id_before, last_timestamp_before = checkpoint

        self._run_docker_compose(["restart", "kafka-connect"])
        time.sleep(15)

        cursor.execute(
            """
            SELECT last_processed_event_id, last_processed_timestamp_micros
            FROM _cdc_checkpoints
            WHERE source_table = 'users'
            ORDER BY checkpoint_timestamp DESC
            LIMIT 1
            """
        )
        new_checkpoint = cursor.fetchone()

        assert new_checkpoint is not None, "No checkpoint found after restart"

        last_event_id_after, last_timestamp_after = new_checkpoint

        assert last_timestamp_after >= last_timestamp_before, (
            "Checkpoint timestamp should not go backwards after restart"
        )

    def _run_docker_compose(self, args: List[str]) -> None:
        """Run docker compose command."""
        subprocess.run(
            ["docker-compose"] + args,
            cwd="/home/bob/WORK/cass-cdc-pg",
            capture_output=True,
        )
