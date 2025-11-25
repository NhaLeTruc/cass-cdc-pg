"""
Pytest configuration and shared fixtures for integration tests.
"""
import pytest
import requests
from typing import Generator
from cassandra.cluster import Cluster, Session
import psycopg2


def check_kafka_connectors() -> bool:
    """Check if required Kafka connectors are deployed."""
    try:
        response = requests.get("http://localhost:8083/connectors", timeout=5)
        connectors = response.json()
        return "postgres-sink" in connectors
    except Exception:
        return False


def check_cassandra_connector() -> bool:
    """Check if Cassandra source connector is deployed."""
    try:
        response = requests.get("http://localhost:8083/connectors", timeout=5)
        connectors = response.json()
        return "cassandra-source" in connectors
    except Exception:
        return False


def check_cdc_pipeline_ready() -> bool:
    """Check if full CDC pipeline is deployed and ready."""
    try:
        response = requests.get("http://localhost:8083/connectors", timeout=5)
        connectors = response.json()
        # Need both cassandra-source and postgres-sink for end-to-end tests
        return "cassandra-source" in connectors and "postgres-sink" in connectors
    except Exception:
        return False


def check_cassandra_available() -> bool:
    """Check if Cassandra is available."""
    try:
        cluster = Cluster(
            contact_points=["localhost"],
            port=9042,
            connect_timeout=5,
            control_connection_timeout=5,
        )
        session = cluster.connect()
        session.shutdown()
        cluster.shutdown()
        return True
    except Exception:
        return False


def check_postgres_available() -> bool:
    """Check if PostgreSQL is available."""
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="warehouse",
            user="cdc_user",
            password="cdc_password",
            connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:
        return False


def check_reconciliation_infrastructure() -> bool:
    """Check if reconciliation infrastructure (Cassandra + PostgreSQL) is available."""
    return check_cassandra_available() and check_postgres_available()


# Mark for skipping tests that require connectors
requires_connectors = pytest.mark.skipif(
    not check_kafka_connectors(),
    reason="Kafka connectors not deployed - run 'make deploy-connectors' first"
)

requires_cassandra_connector = pytest.mark.skipif(
    not check_cassandra_connector(),
    reason="Cassandra connector not deployed - run 'make deploy-connectors' first"
)

requires_cdc_pipeline = pytest.mark.skipif(
    not check_cdc_pipeline_ready(),
    reason="CDC pipeline connectors not deployed - run 'make deploy-connectors' first"
)

requires_reconciliation = pytest.mark.skipif(
    not check_reconciliation_infrastructure(),
    reason="Reconciliation infrastructure (Cassandra + PostgreSQL) not available"
)


# Shared fixtures for Cassandra and PostgreSQL connections
@pytest.fixture(scope="module")
def cassandra_session() -> Generator[Session, None, None]:
    """Provide shared Cassandra session for tests."""
    cluster = Cluster(
        contact_points=["localhost"],
        port=9042,
        connect_timeout=10,
        control_connection_timeout=10,
    )
    session = cluster.connect()
    yield session
    session.shutdown()
    cluster.shutdown()


@pytest.fixture(scope="module")
def postgres_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Provide shared PostgreSQL connection for tests."""
    # Register UUID adapter for psycopg2
    from psycopg2.extras import register_uuid
    register_uuid()

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
