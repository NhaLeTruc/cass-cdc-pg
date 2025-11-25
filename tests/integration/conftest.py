"""
Pytest configuration and shared fixtures for integration tests.
"""
import pytest
import requests
from typing import Generator


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
