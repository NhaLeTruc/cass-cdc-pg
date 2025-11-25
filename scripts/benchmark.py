#!/usr/bin/env python3
"""
Performance benchmarking script for Cassandra to PostgreSQL CDC Pipeline.

This script uses Locust to simulate high-volume data changes in Cassandra
and measures end-to-end replication latency to PostgreSQL.

Usage:
    # Run with default settings (10K events/sec target)
    locust -f scripts/benchmark.py --host=http://localhost

    # Run with custom user count and spawn rate
    locust -f scripts/benchmark.py --host=http://localhost --users 100 --spawn-rate 10

    # Headless mode with specific duration
    locust -f scripts/benchmark.py --host=http://localhost --headless --users 100 --spawn-rate 10 --run-time 5m

    # With HTML report generation
    locust -f scripts/benchmark.py --host=http://localhost --headless --users 100 --run-time 10m --html benchmark-report.html

Requirements:
    - Cassandra cluster running and accessible
    - PostgreSQL database running and accessible
    - Kafka Connect pipeline deployed and running
    - Required Python packages: locust, cassandra-driver, psycopg2-binary, prometheus-client
"""

import logging
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from cassandra.cluster import Cluster, Session
from locust import TaskSet, User, constant_pacing, events, task
from prometheus_client import Counter, Histogram, Gauge
import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "localhost")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "warehouse")
CASSANDRA_USERNAME = os.getenv("CASSANDRA_USERNAME", "cassandra")
CASSANDRA_PASSWORD = os.getenv("CASSANDRA_PASSWORD", "cassandra")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "warehouse")
POSTGRES_USER = os.getenv("POSTGRES_USER", "cdc_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "cdc_password")

# Benchmark configuration
TARGET_EVENTS_PER_SECOND = int(os.getenv("TARGET_EVENTS_PER_SECOND", "10000"))
MAX_LATENCY_P95_MS = int(os.getenv("MAX_LATENCY_P95_MS", "2000"))
MAX_LATENCY_P99_MS = int(os.getenv("MAX_LATENCY_P99_MS", "5000"))
VERIFICATION_SAMPLE_RATE = float(os.getenv("VERIFICATION_SAMPLE_RATE", "0.01"))  # 1% sample

# Prometheus metrics
events_written = Counter('benchmark_events_written_total', 'Total events written to Cassandra', ['operation'])
events_verified = Counter('benchmark_events_verified_total', 'Total events verified in PostgreSQL', ['status'])
replication_latency = Histogram('benchmark_replication_latency_seconds', 'End-to-end replication latency', buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0])
cassandra_errors = Counter('benchmark_cassandra_errors_total', 'Total Cassandra errors', ['error_type'])
postgres_errors = Counter('benchmark_postgres_errors_total', 'Total PostgreSQL errors', ['error_type'])
verification_queue_depth = Gauge('benchmark_verification_queue_depth', 'Number of events awaiting verification')


@dataclass
class BenchmarkEvent:
    """Represents an event to be written and verified."""
    event_id: str
    user_id: uuid.UUID
    operation: str  # INSERT, UPDATE, DELETE
    data: Dict[str, Any]
    timestamp: float
    verified: bool = False


class VerificationQueue:
    """Thread-safe queue for tracking events awaiting verification."""

    def __init__(self, max_size: int = 100000):
        self.max_size = max_size
        self.events: Dict[str, BenchmarkEvent] = {}
        self._lock = threading.Lock()

    def add(self, event: BenchmarkEvent) -> None:
        """Add event to verification queue (thread-safe)."""
        with self._lock:
            if len(self.events) >= self.max_size:
                # Remove oldest unverified event
                oldest_id = min(self.events.keys(), key=lambda k: self.events[k].timestamp)
                del self.events[oldest_id]

            self.events[event.event_id] = event
            verification_queue_depth.set(len(self.events))

    def verify(self, event_id: str) -> Optional[float]:
        """Mark event as verified and return latency (thread-safe)."""
        with self._lock:
            if event_id in self.events:
                event = self.events[event_id]
                if not event.verified:
                    latency = time.time() - event.timestamp
                    event.verified = True
                    events_verified.labels(status='success').inc()
                    replication_latency.observe(latency)
                    return latency
        return None

    def get_unverified_count(self) -> int:
        """Get count of unverified events (thread-safe)."""
        with self._lock:
            return sum(1 for e in self.events.values() if not e.verified)


# Global verification queue
verification_queue = VerificationQueue()


class CassandraClient:
    """Cassandra database client for benchmark operations."""

    def __init__(self):
        self.cluster: Optional[Cluster] = None
        self.session: Optional[Session] = None

    def connect(self) -> None:
        """Connect to Cassandra cluster."""
        try:
            self.cluster = Cluster(
                contact_points=[CASSANDRA_HOST],
                port=CASSANDRA_PORT,
                auth_provider=None  # Add auth if needed
            )
            self.session = self.cluster.connect(CASSANDRA_KEYSPACE)
            logger.info(f"Connected to Cassandra at {CASSANDRA_HOST}:{CASSANDRA_PORT}")
        except Exception as e:
            cassandra_errors.labels(error_type='connection').inc()
            logger.error(f"Failed to connect to Cassandra: {e}")
            raise

    def disconnect(self) -> None:
        """Disconnect from Cassandra cluster."""
        if self.session:
            self.session.shutdown()
        if self.cluster:
            self.cluster.shutdown()

    def insert_user(self, user_id: uuid.UUID, data: Dict[str, Any]) -> None:
        """Insert a user record."""
        query = """
            INSERT INTO users (user_id, email, name, created_at, metadata)
            VALUES (%s, %s, %s, %s, %s)
        """
        try:
            self.session.execute(query, (
                user_id,
                data['email'],
                data['name'],
                data['created_at'],
                str(data.get('metadata', {}))
            ))
            events_written.labels(operation='INSERT').inc()
        except Exception as e:
            cassandra_errors.labels(error_type='insert').inc()
            raise

    def update_user(self, user_id: uuid.UUID, data: Dict[str, Any]) -> None:
        """Update a user record."""
        query = """
            UPDATE users
            SET email = %s, name = %s, metadata = %s
            WHERE user_id = %s
        """
        try:
            self.session.execute(query, (
                data['email'],
                data['name'],
                str(data.get('metadata', {})),
                user_id
            ))
            events_written.labels(operation='UPDATE').inc()
        except Exception as e:
            cassandra_errors.labels(error_type='update').inc()
            raise

    def delete_user(self, user_id: uuid.UUID) -> None:
        """Delete a user record."""
        query = "DELETE FROM users WHERE user_id = %s"
        try:
            self.session.execute(query, (user_id,))
            events_written.labels(operation='DELETE').inc()
        except Exception as e:
            cassandra_errors.labels(error_type='delete').inc()
            raise


class PostgreSQLClient:
    """PostgreSQL database client for verification."""

    def __init__(self):
        self.conn = None

    def connect(self) -> None:
        """Connect to PostgreSQL database."""
        try:
            self.conn = psycopg2.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                database=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                cursor_factory=RealDictCursor
            )
            logger.info(f"Connected to PostgreSQL at {POSTGRES_HOST}:{POSTGRES_PORT}")
        except Exception as e:
            postgres_errors.labels(error_type='connection').inc()
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    def disconnect(self) -> None:
        """Disconnect from PostgreSQL."""
        if self.conn:
            self.conn.close()

    def verify_user_exists(self, user_id: uuid.UUID) -> bool:
        """Verify user record exists in PostgreSQL."""
        query = "SELECT user_id FROM cdc_users WHERE user_id = %s"
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query, (str(user_id),))
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            postgres_errors.labels(error_type='verify').inc()
            logger.error(f"Verification failed: {e}")
            return False

    def verify_user_deleted(self, user_id: uuid.UUID) -> bool:
        """Verify user record does not exist in PostgreSQL."""
        return not self.verify_user_exists(user_id)


class CDCBenchmarkTasks(TaskSet):
    """Locust task set for CDC benchmarking."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cassandra_client = None
        self.postgres_client = None
        self.existing_users: List[uuid.UUID] = []

    def on_start(self) -> None:
        """Initialize clients when user starts."""
        self.cassandra_client = CassandraClient()
        self.cassandra_client.connect()

        self.postgres_client = PostgreSQLClient()
        self.postgres_client.connect()

        logger.info("Benchmark user started")

    def on_stop(self) -> None:
        """Clean up when user stops."""
        if self.cassandra_client:
            self.cassandra_client.disconnect()
        if self.postgres_client:
            self.postgres_client.disconnect()

        logger.info("Benchmark user stopped")

    def _generate_user_data(self) -> Dict[str, Any]:
        """Generate random user data."""
        return {
            'email': f"user{random.randint(1, 1000000)}@example.com",
            'name': f"Test User {random.randint(1, 1000000)}",
            'created_at': datetime.utcnow(),
            'metadata': {'source': 'benchmark', 'version': '1.0'}
        }

    @task(70)
    def insert_user(self) -> None:
        """Insert a new user (70% of operations)."""
        start_time = time.time()
        user_id = uuid.uuid4()
        data = self._generate_user_data()
        event_id = str(uuid.uuid4())

        try:
            # Write to Cassandra
            self.cassandra_client.insert_user(user_id, data)

            # Track for verification if sampled
            if random.random() < VERIFICATION_SAMPLE_RATE:
                event = BenchmarkEvent(
                    event_id=event_id,
                    user_id=user_id,
                    operation='INSERT',
                    data=data,
                    timestamp=time.time()
                )
                verification_queue.add(event)

            # Store for future updates/deletes
            self.existing_users.append(user_id)
            if len(self.existing_users) > 1000:  # Keep last 1000
                self.existing_users = self.existing_users[-1000:]

            # Record success
            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="INSERT",
                name="Cassandra INSERT",
                response_time=total_time,
                response_length=0,
                exception=None,
                context={}
            )
        except Exception as e:
            # Record failure
            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="INSERT",
                name="Cassandra INSERT",
                response_time=total_time,
                response_length=0,
                exception=e,
                context={}
            )

    @task(20)
    def update_user(self) -> None:
        """Update an existing user (20% of operations)."""
        if not self.existing_users:
            return

        start_time = time.time()
        user_id = random.choice(self.existing_users)
        data = self._generate_user_data()

        try:
            self.cassandra_client.update_user(user_id, data)

            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="UPDATE",
                name="Cassandra UPDATE",
                response_time=total_time,
                response_length=0,
                exception=None,
                context={}
            )
        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="UPDATE",
                name="Cassandra UPDATE",
                response_time=total_time,
                response_length=0,
                exception=e,
                context={}
            )

    @task(10)
    def delete_user(self) -> None:
        """Delete an existing user (10% of operations)."""
        if not self.existing_users:
            return

        start_time = time.time()
        user_id = self.existing_users.pop(random.randint(0, len(self.existing_users) - 1))

        try:
            self.cassandra_client.delete_user(user_id)

            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="DELETE",
                name="Cassandra DELETE",
                response_time=total_time,
                response_length=0,
                exception=None,
                context={}
            )
        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="DELETE",
                name="Cassandra DELETE",
                response_time=total_time,
                response_length=0,
                exception=e,
                context={}
            )

    @task(5)
    def verify_replication(self) -> None:
        """Verify event replication (5% of operations)."""
        if not verification_queue.events:
            return

        # Pick a random unverified event
        unverified = [e for e in verification_queue.events.values() if not e.verified]
        if not unverified:
            return

        event = random.choice(unverified)
        start_time = time.time()

        try:
            # Check if replicated to PostgreSQL
            exists = self.postgres_client.verify_user_exists(event.user_id)

            if exists and event.operation in ['INSERT', 'UPDATE']:
                # Event successfully replicated
                latency = verification_queue.verify(event.event_id)
                if latency:
                    logger.info(f"Event {event.event_id} replicated in {latency:.3f}s")

            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="VERIFY",
                name="PostgreSQL VERIFY",
                response_time=total_time,
                response_length=0,
                exception=None,
                context={}
            )
        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            self.user.environment.events.request.fire(
                request_type="VERIFY",
                name="PostgreSQL VERIFY",
                response_time=total_time,
                response_length=0,
                exception=e,
                context={}
            )


class CDCBenchmarkUser(User):
    """Locust user for CDC benchmarking."""
    tasks = [CDCBenchmarkTasks]

    # Pacing to achieve target events/sec
    # With 100 users, each should wait 0.01s between tasks for 10K events/sec
    wait_time = constant_pacing(1)  # Adjust based on user count


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts."""
    logger.info("=" * 80)
    logger.info("CDC Pipeline Performance Benchmark Starting")
    logger.info("=" * 80)
    logger.info(f"Target: {TARGET_EVENTS_PER_SECOND} events/second")
    logger.info(f"Cassandra: {CASSANDRA_HOST}:{CASSANDRA_PORT}")
    logger.info(f"PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}")
    logger.info(f"Max P95 Latency: {MAX_LATENCY_P95_MS}ms")
    logger.info(f"Max P99 Latency: {MAX_LATENCY_P99_MS}ms")
    logger.info(f"Verification Sample Rate: {VERIFICATION_SAMPLE_RATE * 100}%")
    logger.info("=" * 80)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops - print summary."""
    logger.info("=" * 80)
    logger.info("CDC Pipeline Performance Benchmark Complete")
    logger.info("=" * 80)

    # Calculate statistics
    stats = environment.stats
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    avg_response_time = stats.total.avg_response_time

    logger.info(f"Total Requests: {total_requests}")
    logger.info(f"Total Failures: {total_failures}")
    logger.info(f"Failure Rate: {(total_failures / total_requests * 100) if total_requests > 0 else 0:.2f}%")
    logger.info(f"Average Response Time: {avg_response_time:.2f}ms")
    logger.info(f"Unverified Events: {verification_queue.get_unverified_count()}")
    logger.info("=" * 80)


if __name__ == "__main__":
    # This allows running the script directly with: python scripts/benchmark.py
    # But it's recommended to use the locust CLI for better control
    logger.info("Use 'locust -f scripts/benchmark.py' to run the benchmark")
    logger.info("Example: locust -f scripts/benchmark.py --host=http://localhost --users 100 --spawn-rate 10")
