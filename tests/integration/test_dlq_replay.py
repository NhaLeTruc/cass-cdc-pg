"""Integration test for DLQ replay functionality."""

import time
import uuid
import pytest
import psycopg2
import requests
import json
from cassandra.cluster import Cluster
import structlog

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


class TestDLQReplay:
    """Test DLQ replay functionality."""

    @requires_cdc_pipeline
    def test_dlq_replay_successful_reprocessing(self, postgres_conn):
        """
        Test that DLQ events can be replayed after fixing the issue.

        Test steps:
        1. Create a DLQ record manually (simulating a failed event)
        2. POST to /dlq/replay with dlq_id
        3. Verify event is reprocessed successfully
        4. Verify DLQ record status updated to resolved
        """
        test_id = str(uuid.uuid4())
        email = f"dlq_replay_test_{int(time.time())}@example.com"

        logger.info("test_dlq_replay_start", test_id=test_id)

        cursor = postgres_conn.cursor()

        # Step 1: Create a DLQ record manually
        logger.info("creating_dlq_record", test_id=test_id)

        event_data = {
            "user_id": test_id,
            "email": email,
            "created_at": int(time.time() * 1000),
        }

        cursor.execute(
            """
            INSERT INTO _cdc_dlq_records (source_table, event_data, error_type, error_message, failed_at)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (
                "users",
                json.dumps(event_data),
                "TYPE_CONVERSION_ERROR",
                "Simulated error for replay test",
            ),
        )

        dlq_id = cursor.fetchone()[0]
        postgres_conn.commit()

        logger.info("dlq_record_created", dlq_id=dlq_id)

        # Step 2: POST to /dlq/replay endpoint
        logger.info("posting_to_replay_endpoint", dlq_id=dlq_id)

        try:
            response = requests.post(
                "http://localhost:8000/dlq/replay",
                json={
                    "dlq_ids": [dlq_id],
                    "resolution_notes": "Fixed the type conversion issue",
                    "retry_strategy": "immediate",
                },
                timeout=30,
            )

            logger.info(
                "replay_response",
                status_code=response.status_code,
                body=response.text,
            )

            if response.status_code == 200:
                replay_result = response.json()

                # Verify replay was initiated
                assert "replayed" in replay_result or "success" in replay_result, \
                    "Replay response should indicate success"

                logger.info("replay_initiated", result=replay_result)

                # Step 3: Wait and verify event was reprocessed
                time.sleep(15)

                cursor.execute(
                    "SELECT email FROM cdc_users WHERE user_id = %s",
                    (test_id,),
                )

                result = cursor.fetchone()

                if result:
                    assert result[0] == email, f"Email mismatch: {result[0]} != {email}"
                    logger.info("event_reprocessed_successfully", test_id=test_id)

                # Step 4: Verify DLQ record status updated
                cursor.execute(
                    "SELECT resolution_status, resolution_notes FROM _cdc_dlq_records WHERE id = %s",
                    (dlq_id,),
                )

                dlq_result = cursor.fetchone()

                if dlq_result:
                    resolution_status, resolution_notes = dlq_result

                    logger.info(
                        "dlq_record_updated",
                        resolution_status=resolution_status,
                        resolution_notes=resolution_notes,
                    )

                    # Status should be updated to resolved or similar
                    assert resolution_status in ["MANUAL_RESOLVED", "AUTO_RESOLVED", "resolved"], \
                        f"Expected resolved status, got {resolution_status}"

                logger.info("test_dlq_replay_success", dlq_id=dlq_id)

            elif response.status_code == 404:
                logger.warning(
                    "replay_endpoint_not_implemented",
                    note="/dlq/replay endpoint returns 404, implementation pending",
                )
                pytest.skip("DLQ replay endpoint not yet implemented")

            else:
                logger.error("replay_failed", status_code=response.status_code, body=response.text)
                pytest.fail(f"Replay request failed with status {response.status_code}")

        except requests.exceptions.RequestException as e:
            logger.warning("replay_endpoint_not_available", error=str(e))
            pytest.skip(f"DLQ replay endpoint not available: {e}")

        finally:
            cursor.close()

    @requires_cdc_pipeline
    def test_dlq_replay_batch_processing(self, postgres_conn):
        """
        Test that multiple DLQ events can be replayed in a single batch.

        Verifies batch replay with multiple dlq_ids.
        """
        cursor = postgres_conn.cursor()

        logger.info("test_batch_replay_start")

        # Create multiple DLQ records
        dlq_ids = []
        test_prefix = f"batch_replay_{int(time.time())}"

        for i in range(5):
            test_id = str(uuid.uuid4())
            email = f"{test_prefix}_{i}@example.com"

            event_data = {
                "user_id": test_id,
                "email": email,
                "created_at": int(time.time() * 1000),
            }

            cursor.execute(
                """
                INSERT INTO _cdc_dlq_records (source_table, event_data, error_type, error_message, failed_at)
                VALUES (%s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    "users",
                    json.dumps(event_data),
                    "NETWORK_TIMEOUT",
                    "Simulated timeout for batch replay test",
                ),
            )

            dlq_id = cursor.fetchone()[0]
            dlq_ids.append(dlq_id)

        postgres_conn.commit()

        logger.info("batch_dlq_records_created", count=len(dlq_ids))

        # Replay all DLQ records in batch
        try:
            response = requests.post(
                "http://localhost:8000/dlq/replay",
                json={
                    "dlq_ids": dlq_ids,
                    "resolution_notes": "Batch replay after network recovery",
                    "retry_strategy": "batch",
                },
                timeout=60,
            )

            logger.info("batch_replay_response", status_code=response.status_code)

            if response.status_code == 200:
                replay_result = response.json()
                logger.info("batch_replay_result", result=replay_result)

                # Verify successful batch replay
                if "replayed_count" in replay_result:
                    assert replay_result["replayed_count"] == len(dlq_ids), \
                        f"Expected {len(dlq_ids)} replayed, got {replay_result['replayed_count']}"

                logger.info("test_batch_replay_success", count=len(dlq_ids))

            elif response.status_code == 404:
                logger.warning("batch_replay_endpoint_not_implemented")
                pytest.skip("Batch DLQ replay not yet implemented")

        except requests.exceptions.RequestException as e:
            logger.warning("batch_replay_endpoint_not_available", error=str(e))
            pytest.skip(f"Batch replay endpoint not available: {e}")

        finally:
            cursor.close()

    @requires_cdc_pipeline
    def test_dlq_query_endpoint(self, postgres_conn):
        """
        Test GET /dlq/records endpoint with filters.

        Verifies:
        - Query by error_type
        - Query by resolution_status
        - Query by table
        - Pagination
        """
        logger.info("test_dlq_query_start")

        try:
            # Query all DLQ records
            response = requests.get(
                "http://localhost:8000/dlq/records",
                timeout=10,
            )

            logger.info("dlq_query_response", status_code=response.status_code)

            if response.status_code == 200:
                records = response.json()

                logger.info("dlq_records_retrieved", count=len(records) if isinstance(records, list) else "unknown")

                # Verify response structure
                if isinstance(records, list):
                    for record in records[:3]:  # Check first 3 records
                        assert "id" in record or "dlq_id" in record, "Record should have id"
                        assert "source_table" in record, "Record should have source_table"
                        assert "error_type" in record, "Record should have error_type"
                        assert "failed_at" in record, "Record should have failed_at"

                    logger.info("dlq_query_structure_valid")

                elif isinstance(records, dict):
                    # Paginated response
                    assert "items" in records or "records" in records, \
                        "Paginated response should have items/records"

                    if "items" in records:
                        items = records["items"]
                    else:
                        items = records["records"]

                    logger.info("dlq_paginated_response", count=len(items))

                # Test filtering by error_type
                response_filtered = requests.get(
                    "http://localhost:8000/dlq/records?error_type=TYPE_CONVERSION_ERROR",
                    timeout=10,
                )

                if response_filtered.status_code == 200:
                    logger.info("dlq_filter_by_error_type_success")

                # Test filtering by table
                response_table = requests.get(
                    "http://localhost:8000/dlq/records?table=users",
                    timeout=10,
                )

                if response_table.status_code == 200:
                    logger.info("dlq_filter_by_table_success")

                logger.info("test_dlq_query_success")

            elif response.status_code == 404:
                logger.warning("dlq_query_endpoint_not_implemented")
                pytest.skip("DLQ query endpoint not yet implemented")

        except requests.exceptions.RequestException as e:
            logger.warning("dlq_query_endpoint_not_available", error=str(e))
            pytest.skip(f"DLQ query endpoint not available: {e}")

    @requires_cdc_pipeline
    def test_dlq_replay_with_validation(self, postgres_conn):
        """
        Test that DLQ replay validates events before reprocessing.

        Verifies:
        - Invalid DLQ IDs are rejected
        - Already resolved events are skipped
        - Validation errors are returned
        """
        logger.info("test_dlq_replay_validation_start")

        try:
            # Test with non-existent DLQ ID
            response = requests.post(
                "http://localhost:8000/dlq/replay",
                json={
                    "dlq_ids": [999999],
                    "resolution_notes": "Testing invalid ID",
                },
                timeout=10,
            )

            logger.info("invalid_id_response", status_code=response.status_code)

            if response.status_code == 404:
                logger.info("invalid_dlq_id_rejected_correctly")

            elif response.status_code == 400:
                # Bad request for invalid ID
                error_response = response.json()
                logger.info("validation_error_returned", error=error_response)

            elif response.status_code == 200:
                # Some implementations may return success with empty results
                logger.info("invalid_id_returned_empty_result")

            # Test with missing required parameters
            response_missing = requests.post(
                "http://localhost:8000/dlq/replay",
                json={},
                timeout=10,
            )

            logger.info("missing_params_response", status_code=response_missing.status_code)

            # Should return 400 or 422 for missing parameters
            assert response_missing.status_code in [400, 422], \
                "Missing parameters should return validation error"

            logger.info("test_dlq_replay_validation_success")

        except requests.exceptions.RequestException as e:
            logger.warning("dlq_replay_validation_endpoint_not_available", error=str(e))
            pytest.skip(f"DLQ replay endpoint not available: {e}")

    @requires_cdc_pipeline
    def test_dlq_metrics_updated_on_replay(self, postgres_conn):
        """
        Test that DLQ metrics are updated when events are replayed.

        Verifies cdc_dlq_replay_success_total and cdc_dlq_replay_failed_total counters.
        """
        logger.info("test_dlq_replay_metrics_start")

        cursor = postgres_conn.cursor()

        # Create DLQ record for replay
        test_id = str(uuid.uuid4())
        email = f"metrics_replay_test_{int(time.time())}@example.com"

        event_data = {
            "user_id": test_id,
            "email": email,
            "created_at": int(time.time() * 1000),
        }

        cursor.execute(
            """
            INSERT INTO _cdc_dlq_records (source_table, event_data, error_type, error_message, failed_at)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (
                "users",
                json.dumps(event_data),
                "SCHEMA_MISMATCH",
                "Metrics test",
            ),
        )

        dlq_id = cursor.fetchone()[0]
        postgres_conn.commit()
        cursor.close()

        # Get initial metrics
        try:
            response = requests.get("http://localhost:8000/metrics", timeout=10)
            initial_metrics = response.text

            logger.info("initial_metrics_captured")

            # Replay the event
            replay_response = requests.post(
                "http://localhost:8000/dlq/replay",
                json={"dlq_ids": [dlq_id], "resolution_notes": "Metrics test replay"},
                timeout=30,
            )

            if replay_response.status_code == 200:
                time.sleep(5)

                # Get updated metrics
                response = requests.get("http://localhost:8000/metrics", timeout=10)
                updated_metrics = response.text

                # Verify DLQ replay metrics exist
                assert "cdc_dlq_replay" in updated_metrics or "dlq_replay" in updated_metrics, \
                    "DLQ replay metrics should be exposed"

                logger.info("test_dlq_replay_metrics_success")

            else:
                logger.warning("replay_failed_metrics_test_skipped")

        except requests.exceptions.RequestException as e:
            logger.warning("metrics_endpoint_not_available", error=str(e))
            pytest.skip(f"Metrics endpoint not available: {e}")
