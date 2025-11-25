"""
Pytest configuration and fixtures for CDC pipeline tests.
"""
import pytest
from typing import Generator


@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    """Path to docker compose file for testcontainers"""
    return "docker-compose.yml"


@pytest.fixture(scope="session")
def cassandra_container() -> Generator:
    """Cassandra test container fixture"""
    # Placeholder - will be implemented with testcontainers
    yield


@pytest.fixture(scope="session")
def postgres_container() -> Generator:
    """PostgreSQL test container fixture"""
    # Placeholder - will be implemented with testcontainers
    yield


@pytest.fixture(scope="session")
def kafka_container() -> Generator:
    """Kafka test container fixture"""
    # Placeholder - will be implemented with testcontainers
    yield


@pytest.fixture
def sample_change_event() -> dict:
    """Sample change event for testing"""
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "source_keyspace": "warehouse",
        "source_table": "users",
        "partition_key": {"id": "user-12345"},
        "clustering_key": None,
        "operation_type": "UPDATE",
        "before_values": {
            "id": "user-12345",
            "username": "john_doe",
            "email": "john@example.com",
        },
        "after_values": {
            "id": "user-12345",
            "username": "john_doe",
            "email": "john.doe@example.com",
        },
        "column_types": {
            "id": "text",
            "username": "text",
            "email": "text",
        },
        "timestamp_micros": 1732092300000000,
        "captured_at": "2025-11-20T08:45:00.123456Z",
        "schema_version": 3,
        "trace_id": "a1b2c3d4e5f6789012345678abcdef90",
        "ttl_seconds": None,
        "is_tombstone": False,
    }
