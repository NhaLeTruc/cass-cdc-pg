# Research: Cassandra-to-PostgreSQL CDC Pipeline

**Date**: 2025-11-20
**Feature**: 001-cass-cdc-pg
**Purpose**: Technical research and architecture decisions for CDC pipeline implementation

## Overview

This document captures technical research, technology choices, and best practices for building the Cassandra-to-PostgreSQL CDC pipeline. All decisions prioritize open-source, production-grade tools that align with the project constitution.

---

## 1. CDC Mechanism: Debezium vs. Custom Implementation

### Decision

**Use Debezium 2.5.x with Kafka Connect framework**

### Rationale

1. **Production-Proven**: Debezium is battle-tested at scale (LinkedIn, Uber, Netflix use it)
2. **Cassandra 4.x Support**: Debezium 2.5+ has stable Cassandra 4.x connector with CDC table support
3. **Schema Evolution**: Built-in schema registry integration handles DDL changes
4. **Operational Maturity**: Extensive monitoring, offset management, fault tolerance built-in
5. **Community Support**: Active development, security patches, extensive documentation

### Alternatives Considered

- **Custom Cassandra CDC Reader**: More control but requires implementing offset tracking, schema detection, error handling, monitoring from scratch. Estimated 3-6 months development vs. 1-2 weeks with Debezium.
- **Change Streams (if available)**: Cassandra doesn't have MongoDB-style change streams. CDC commitlog is the native mechanism.

### Implementation Notes

- Debezium Cassandra connector config stored in `config/debezium/cassandra-connector.json`
- Kafka Connect runs in distributed mode for HA
- Connector monitors Cassandra CDC commitlog directory (`/var/lib/cassandra/commitlog`)
- Events published to Kafka topics with pattern: `cassandra.<keyspace>.<table>`

### References

- [Debezium Cassandra Connector Docs](https://debezium.io/documentation/reference/stable/connectors/cassandra.html)
- [Cassandra CDC Implementation](https://cassandra.apache.org/doc/latest/operating/cdc.html)

---

## 2. Message Broker: Kafka vs. Pulsar vs. RabbitMQ

### Decision

**Use Apache Kafka 3.6.x (KRaft mode, no Zookeeper)**

### Rationale

1. **Debezium Integration**: Native integration, first-class support
2. **Durability**: Persistent log-based storage with configurable retention (7 days default)
3. **Scalability**: Horizontal scaling via partitions, consumer groups for parallel processing
4. **Exactly-Once Semantics**: Kafka transactions + idempotent producers prevent duplication
5. **Ecosystem**: Rich tooling (Kafka UI, AKHQ for topic management), Prometheus exporters
6. **KRaft Mode**: Simplified operations without Zookeeper dependency (Kafka 3.3+)

### Alternatives Considered

- **Apache Pulsar**: More modern, multi-tenancy, geo-replication built-in. However, less mature Debezium integration, smaller community.
- **RabbitMQ**: Lacks persistent log semantics needed for CDC (messages deleted after consumption), limited horizontal scaling.

### Implementation Notes

- Kafka runs in KRaft mode (Zookeeper-free) for simpler deployment
- Minimum 3 brokers for replication factor 3 (production), single broker for local dev
- Topics auto-created by Debezium with partitions=10 (configurable by table size)
- Consumer group ID: `cass-cdc-pg-workers` for coordinated consumption
- Kafka Connect sink connector OR custom Python consumers (decision: custom for flexibility)

### Configuration

```properties
# config/dev/kafka.properties
bootstrap.servers=kafka:9092
replication.factor=1  # 3 in production
min.insync.replicas=1  # 2 in production
log.retention.hours=168  # 7 days
log.segment.bytes=1073741824  # 1GB
compression.type=lz4
```

### References

- [Kafka KRaft Quickstart](https://kafka.apache.org/documentation/#kraft)
- [Kafka Performance Tuning](https://docs.confluent.io/platform/current/kafka/deployment.html#performance-tuning)

---

## 3. Distributed Cache: Redis vs. Memcached vs. etcd

### Decision

**Use Redis 7.2.x with AOF + RDB persistence**

### Rationale

1. **Persistence**: RDB snapshots + AOF log ensure checkpoint state survives restarts
2. **Data Structures**: Rich types (hashes for schemas, sorted sets for checkpoints, pub/sub for config updates)
3. **High Availability**: Redis Sentinel (3 nodes) for automatic failover in production
4. **Atomic Operations**: MULTI/EXEC transactions for checkpoint commits
5. **Performance**: <1ms latency for most operations, 100K+ ops/sec single-threaded
6. **Python Client**: redis-py 5.0+ with connection pooling and cluster support

### Alternatives Considered

- **Memcached**: Faster but no persistence, no rich data structures, no HA (crashes lose all data)
- **etcd**: Strong consistency, leader election built-in. However, slower (Raft consensus overhead), designed for small config data not high-throughput caching
- **Hazelcast**: In-process cache (JVM-based, not suitable for Python)

### Implementation Notes

Redis stores three types of metadata:

1. **Checkpoints**: `checkpoint:<table>:<partition>` → JSON with `{offset, timestamp, worker_id}`
2. **Schemas**: `schema:<keyspace>:<table>` → JSON schema definition with version
3. **Worker Coordination**: `lock:<table>` → Distributed lock for table assignment

Persistence configuration:
- **AOF**: `appendfsync=everysec` (fsync every second, balance durability/performance)
- **RDB**: Snapshot every 5 minutes or 100 writes
- **Eviction**: `noeviction` policy (fail writes if memory full, prevent data loss)

### Configuration

```conf
# config/dev/redis.conf
appendonly yes
appendfsync everysec
save 300 10  # Snapshot if 10+ keys changed in 5 minutes
maxmemory 2gb
maxmemory-policy noeviction
```

### References

- [Redis Persistence](https://redis.io/docs/management/persistence/)
- [Redis Sentinel](https://redis.io/docs/management/sentinel/)

---

## 4. Python Libraries & Frameworks

### Decision Matrix

| Purpose | Library | Version | Rationale |
|---------|---------|---------|-----------|
| **Kafka Consumer** | confluent-kafka-python | 2.3+ | C librdkafka wrapper, 10x faster than kafka-python, production-proven |
| **PostgreSQL Driver** | psycopg3 | 3.1+ | Async support, better performance than psycopg2, parameterized queries |
| **Redis Client** | redis-py | 5.0+ | Official Redis client, connection pooling, cluster support |
| **Schema Validation** | Pydantic | 2.5+ | Type-safe models, JSON schema generation, 5-50x faster than v1 |
| **Retry Logic** | tenacity | 8.2+ | Declarative retries with exponential backoff, well-tested |
| **Circuit Breaker** | pybreaker | 1.0+ | Lightweight, easy integration, Prometheus metrics |
| **Logging** | structlog | 23.2+ | Structured JSON logs, processors for context injection |
| **Metrics** | prometheus-client | 0.19+ | Official Prometheus library, zero dependencies |
| **Tracing** | opentelemetry-api | 1.21+ | Vendor-neutral tracing, Jaeger/Zipkin exporters |
| **Configuration** | pydantic-settings | 2.1+ | Type-safe settings from env vars, 12-factor app pattern |
| **Dependency Injection** | dependency-injector | 4.41+ | IoC container for testable code, provider patterns |
| **Testing** | pytest | 7.4+ | De facto standard, rich plugin ecosystem |
| **Integration Tests** | testcontainers-python | 3.7+ | Real Docker containers in tests, supports Cassandra/Kafka/PostgreSQL |
| **Mock Data** | Faker | 20+ | Realistic test data generation (names, addresses, timestamps) |
| **API Framework** | FastAPI | 0.104+ | Async, auto OpenAPI docs, dependency injection |
| **CLI** | Click | 8.1+ | Composable CLI, auto help generation |
| **Async Runtime** | asyncio | stdlib | Built-in, sufficient for I/O-bound tasks |

### Key Dependencies (pyproject.toml)

```toml
[tool.poetry.dependencies]
python = "^3.11"
confluent-kafka = "^2.3"
psycopg = {extras = ["binary", "pool"], version = "^3.1"}
redis = "^5.0"
pydantic = "^2.5"
pydantic-settings = "^2.1"
tenacity = "^8.2"
pybreaker = "^1.0"
structlog = "^23.2"
prometheus-client = "^0.19"
opentelemetry-api = "^1.21"
opentelemetry-sdk = "^1.21"
opentelemetry-instrumentation-kafka-python = "^0.42b0"
dependency-injector = "^4.41"
fastapi = "^0.104"
uvicorn = {extras = ["standard"], version = "^0.24"}
click = "^8.1"
alembic = "^1.13"
```

---

## 5. Data Type Mappings: Cassandra → PostgreSQL

### Mapping Table

| Cassandra Type | PostgreSQL Type | Notes |
|----------------|-----------------|-------|
| `uuid` | `uuid` | Direct mapping |
| `timeuuid` | `uuid` | Extract timestamp to separate column if needed |
| `text`, `varchar` | `text`, `varchar(n)` | PostgreSQL has no length limit on `text` |
| `int` | `integer` | 32-bit signed |
| `bigint` | `bigint` | 64-bit signed |
| `float` | `real` | 32-bit IEEE 754 |
| `double` | `double precision` | 64-bit IEEE 754 |
| `decimal` | `numeric` | Arbitrary precision, preserve scale/precision |
| `boolean` | `boolean` | Direct mapping |
| `timestamp` | `timestamptz` | Always store with timezone (UTC) |
| `date` | `date` | Direct mapping |
| `time` | `time` | Direct mapping |
| `blob` | `bytea` | Binary data, consider size limits (1GB max in PostgreSQL) |
| `ascii` | `varchar` | Subset of `text` |
| `list<T>` | `T[]` | PostgreSQL arrays, nested types supported |
| `set<T>` | `T[]` | No native set type, use array (enforce uniqueness with constraints) |
| `map<K,V>` | `jsonb` | Store as JSON, indexed with GIN indexes |
| `tuple<T1, T2, ...>` | `jsonb` or composite type | JSONB more flexible for schema changes |
| `frozen<UDT>` | `jsonb` | Cassandra UDTs → JSON objects |
| `counter` | `bigint` | Cassandra counter → snapshot value (no auto-increment) |
| `duration` | `interval` | Direct mapping for time intervals |
| `inet` | `inet` | IP address type |

### Complex Type Handling

**Collections**:
- Cassandra `list<int>` → PostgreSQL `integer[]`
- Cassandra `set<text>` → PostgreSQL `text[]` with unique constraint
- Cassandra `map<text, int>` → PostgreSQL `jsonb` with GIN index for fast lookups

**User-Defined Types (UDTs)**:
```python
# Cassandra UDT
CREATE TYPE address (
  street text,
  city text,
  zip int
);

# PostgreSQL jsonb
CREATE TABLE users (
  id uuid PRIMARY KEY,
  address jsonb
);

# Insert
INSERT INTO users (id, address) VALUES (
  '...',
  '{"street": "123 Main St", "city": "NYC", "zip": 10001}'::jsonb
);
```

**Tuples**:
- Cassandra `tuple<int, text, timestamp>` → PostgreSQL `jsonb` array
- Alternative: Create composite type if schema stable

### Null Handling

- Cassandra: All columns nullable by default (except primary key)
- PostgreSQL: Enforce NOT NULL on primary keys, optional on others
- Strategy: Preserve nullability from Cassandra schema, add NOT NULL if Cassandra uses `PRIMARY KEY`

### References

- [Cassandra Data Types](https://cassandra.apache.org/doc/latest/cql/types.html)
- [PostgreSQL Data Types](https://www.postgresql.org/docs/16/datatype.html)

---

## 6. Schema Evolution Strategies

### Approach

**Hybrid: Automatic for additive changes, manual review for breaking changes**

### Additive Changes (Automated)

Safe changes applied automatically:
- New nullable columns → `ALTER TABLE ... ADD COLUMN ... NULL`
- New UDT fields → Update JSONB structure (flexible schema)
- Index additions → `CREATE INDEX CONCURRENTLY` (non-blocking)

```python
# services/schema_registry.py
async def handle_schema_change(old_schema, new_schema):
    diff = compute_schema_diff(old_schema, new_schema)
    if diff.is_additive():
        # Apply automatically
        await postgres_writer.execute_ddl(diff.to_alembic_migration())
    else:
        # Breaking change: alert and route to manual review
        logger.error("Breaking schema change detected", extra=diff)
        await publish_to_schema_audit_topic(diff)
```

### Breaking Changes (Manual Review)

Require human intervention:
- Dropped columns → Log warning, continue processing remaining columns, alert ops team
- Type changes → Route records to validation queue, require manual mapping logic
- Primary key changes → Cannot auto-migrate, requires data backfill

### Schema Registry Integration

**Kafka Schema Registry** (Confluent Schema Registry or Apicurio):
- Stores Avro schemas for Kafka messages
- Enforces compatibility rules (BACKWARD, FORWARD, FULL)
- Debezium publishes schema changes to registry
- Consumers detect version bumps and fetch new schema

### Configuration

```yaml
# config/dev/schema-evolution.yml
strategy: hybrid
auto_apply_additive: true
breaking_change_behavior: log_and_skip
schema_cache_ttl_seconds: 60
compatibility_mode: BACKWARD  # Allow reading old data with new schema
```

### References

- [Schema Registry Documentation](https://docs.confluent.io/platform/current/schema-registry/index.html)
- [Avro Schema Evolution](https://avro.apache.org/docs/1.11.1/specification/#schema-resolution)

---

## 7. Error Handling & Dead Letter Queue

### Retry Strategy

**Exponential Backoff with Jitter** (tenacity library):

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(10),
    wait=wait_exponential(multiplier=1, min=1, max=60),  # 1s, 2s, 4s, 8s, ..., 60s
    retry=retry_if_exception_type((psycopg.OperationalError, redis.ConnectionError)),
    reraise=True
)
async def write_to_postgres(batch):
    ...
```

### Dead Letter Queue (DLQ)

**Kafka Topic**: `cassandra.cdc.dlq`

Records sent to DLQ:
- Exceeded retry threshold (10 attempts)
- Validation errors (schema mismatch, constraint violation)
- Transformation failures (unparseable data)

DLQ Message Format:
```json
{
  "original_event": {...},  // Original CDC event
  "error_type": "ValidationError",
  "error_message": "Field 'age' expected int, got string",
  "attempt_count": 10,
  "first_failure_timestamp": "2025-11-20T10:00:00Z",
  "last_failure_timestamp": "2025-11-20T10:05:00Z",
  "source_topic": "cassandra.prod.users",
  "source_partition": 3,
  "source_offset": 123456
}
```

### DLQ Processing

Dedicated worker (`dlq_processor.py`) consumes DLQ topic:
1. Parse error and categorize (transient, validation, permanent)
2. Transient errors (e.g., temporary network issue) → Re-enqueue to main topic
3. Validation errors → Export to CSV for manual correction, re-import via admin API
4. Permanent errors (e.g., corrupted data) → Log and archive

### Circuit Breaker

**pybreaker Configuration**:

```python
from pybreaker import CircuitBreaker

postgres_breaker = CircuitBreaker(
    fail_max=5,        # Open after 5 consecutive failures
    timeout_duration=30,  # Half-open after 30 seconds
    exclude=[ValidationError],  # Don't count validation errors
)

@postgres_breaker
async def write_to_postgres(batch):
    ...
```

When circuit OPEN:
- Stop PostgreSQL writes
- Buffer events in Kafka (Kafka retains up to 7 days)
- Alert: "PostgreSQL circuit open, check database health"
- Half-open after 30s: Test single request
- Close circuit if successful, otherwise stay open

### References

- [Tenacity Retry Patterns](https://tenacity.readthedocs.io/)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)

---

## 8. Observability Stack

### Structured Logging (structlog)

**Configuration**:

```python
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()  # JSON output
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
logger.info("event_processed", table="users", offset=12345, duration_ms=50)
```

**Log Output** (JSON):
```json
{
  "event": "event_processed",
  "table": "users",
  "offset": 12345,
  "duration_ms": 50,
  "logger": "cdc_pipeline.services.event_processor",
  "level": "info",
  "timestamp": "2025-11-20T10:15:30.123Z"
}
```

### Metrics (Prometheus)

**Key Metrics**:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cdc_events_processed_total` | Counter | `table`, `worker_id` | Total events processed |
| `cdc_replication_latency_seconds` | Histogram | `table` | End-to-end latency (Cassandra write → PostgreSQL commit) |
| `cdc_replication_lag_seconds` | Gauge | `table` | Difference between Kafka head offset and committed offset |
| `cdc_error_total` | Counter | `table`, `error_type` | Errors by type |
| `cdc_dlq_size` | Gauge | `table` | DLQ topic size |
| `cdc_checkpoint_age_seconds` | Gauge | `table`, `partition` | Time since last checkpoint |
| `cdc_postgres_batch_size` | Histogram | `table` | PostgreSQL write batch sizes |
| `cdc_circuit_breaker_state` | Gauge | `service` | 0=closed, 1=half-open, 2=open |

**Exporter**:
```python
from prometheus_client import Counter, Histogram, start_http_server

events_processed = Counter('cdc_events_processed_total', 'Events processed', ['table', 'worker_id'])
replication_latency = Histogram('cdc_replication_latency_seconds', 'Replication latency', ['table'])

# Start metrics server on :8000/metrics
start_http_server(8000)
```

### Distributed Tracing (OpenTelemetry + Jaeger)

**Trace Spans**:
1. `cassandra.read` → Debezium reads CDC log
2. `kafka.publish` → Debezium publishes to Kafka
3. `kafka.consume` → Worker polls Kafka
4. `validation` → Schema validation
5. `transformation` → Data type conversion
6. `postgres.write` → Batch write to PostgreSQL
7. `checkpoint.commit` → Redis checkpoint update

**Configuration**:
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

trace.set_tracer_provider(TracerProvider())
jaeger_exporter = JaegerExporter(
    agent_host_name="jaeger",
    agent_port=6831,
)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(jaeger_exporter))

tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("postgres.write") as span:
    span.set_attribute("table", table_name)
    span.set_attribute("batch_size", len(batch))
    await postgres_writer.write(batch)
```

### Grafana Dashboards

**Pipeline Overview**:
- Throughput (events/sec) by table
- Latency heatmap (P50, P95, P99)
- Error rate (% errors)
- Replication lag (seconds)

**Worker Health**:
- CPU/memory usage per worker
- Active connections (Kafka, PostgreSQL, Redis)
- Circuit breaker states
- DLQ growth rate

### References

- [structlog Best Practices](https://www.structlog.org/en/stable/standard-library.html)
- [Prometheus Python Client](https://github.com/prometheus/client_python)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)

---

## 9. Security: Vault, TLS, Encryption

### Secret Management (HashiCorp Vault)

**Architecture**:
- Vault server runs as Docker container in local dev
- Production: Vault cluster with Raft storage backend
- Secrets stored at path: `secret/cdc-pipeline/<env>/<service>`

**Secrets Stored**:
- Cassandra credentials: `secret/cdc-pipeline/prod/cassandra` → `{username, password}`
- PostgreSQL credentials: `secret/cdc-pipeline/prod/postgres` → `{username, password, host, port}`
- Kafka SASL credentials: `secret/cdc-pipeline/prod/kafka` → `{username, password}`
- Redis password: `secret/cdc-pipeline/prod/redis` → `{password}`

**Python Integration**:
```python
import hvac

client = hvac.Client(url='http://vault:8200', token=os.getenv('VAULT_TOKEN'))
postgres_creds = client.secrets.kv.v2.read_secret_version(path='cdc-pipeline/prod/postgres')
username = postgres_creds['data']['data']['username']
password = postgres_creds['data']['data']['password']
```

### TLS Configuration

**Cassandra**:
```yaml
# Cassandra client config
ssl_context:
  ca_certs: /certs/ca.pem
  certfile: /certs/client-cert.pem
  keyfile: /certs/client-key.pem
  check_hostname: true
```

**Kafka**:
```properties
# Kafka consumer config
security.protocol=SSL
ssl.ca.location=/certs/ca.pem
ssl.certificate.location=/certs/client-cert.pem
ssl.key.location=/certs/client-key.pem
```

**PostgreSQL**:
```python
# psycopg3 connection string
conn_str = f"postgresql://{user}:{pwd}@{host}:{port}/{db}?sslmode=require&sslrootcert=/certs/ca.pem"
```

**Redis**:
```python
redis_client = redis.Redis(
    host='redis',
    port=6379,
    password=redis_password,
    ssl=True,
    ssl_ca_certs='/certs/ca.pem',
)
```

### Encryption at Rest

**Cassandra**:
- Transparent Data Encryption (TDE) via `transparent_data_encryption_options` in cassandra.yaml
- Alternatively: LUKS disk encryption at OS level

**PostgreSQL**:
- pgcrypto extension for column-level encryption
- Or: File system encryption (LUKS, dm-crypt)

**Kafka**:
- Broker-side encryption via `log.message.encryption.type=AES`
- Or: Transparent disk encryption

**Redis**:
- RDB/AOF files encrypted at rest via OS-level encryption
- Redis Enterprise (paid) has built-in encryption

### Data Masking

**PII Detection & Masking** (structlog processor):
```python
import re

def mask_pii(logger, method_name, event_dict):
    """Mask PII in logs"""
    pii_patterns = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
        'credit_card': r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
    }

    for field, value in event_dict.items():
        if isinstance(value, str):
            for pii_type, pattern in pii_patterns.items():
                value = re.sub(pattern, f'<REDACTED:{pii_type.upper()}>', value)
            event_dict[field] = value

    return event_dict

# Add to structlog processors
structlog.configure(processors=[..., mask_pii, ...])
```

### References

- [Vault Python Client](https://hvac.readthedocs.io/)
- [PostgreSQL SSL](https://www.postgresql.org/docs/16/ssl-tcp.html)
- [Kafka Security](https://kafka.apache.org/documentation/#security)

---

## 10. Local Development: Docker Compose v2

### Stack Components

**Services** (docker-compose.yml):
1. **Cassandra** (cassandra:4.1): Single node, CDC enabled
2. **Kafka** (confluentinc/cp-kafka:7.5): KRaft mode, no Zookeeper
3. **Kafka Connect** (debezium/connect:2.5): Runs Debezium connectors
4. **PostgreSQL** (postgres:16): Target database
5. **Redis** (redis:7.2-alpine): Metadata cache
6. **Vault** (vault:1.15): Secrets management (dev mode)
7. **Prometheus** (prom/prometheus:v2.48): Metrics collection
8. **Grafana** (grafana/grafana:10.2): Dashboards
9. **Jaeger** (jaegertracing/all-in-one:1.52): Distributed tracing
10. **CDC Worker** (custom image): Python worker consuming Kafka → PostgreSQL
11. **Admin API** (custom image): FastAPI health checks, admin ops

### Startup Script

**docker-compose.yml**:
```yaml
version: '3.9'

services:
  cassandra:
    image: cassandra:4.1
    environment:
      - CASSANDRA_CDC_ENABLED=true
    volumes:
      - cassandra_data:/var/lib/cassandra
    ports:
      - "9042:9042"
    healthcheck:
      test: ["CMD", "cqlsh", "-e", "describe keyspaces"]
      interval: 10s
      timeout: 5s
      retries: 5

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_LISTENERS: PLAINTEXT://kafka:9092,CONTROLLER://kafka:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_LOG_RETENTION_HOURS: 168  # 7 days
    ports:
      - "9092:9092"
    healthcheck:
      test: ["CMD", "kafka-topics", "--bootstrap-server", "kafka:9092", "--list"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: cdc_user
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: warehouse
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7.2-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"

  vault:
    image: vault:1.15
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: dev-root-token
      VAULT_DEV_LISTEN_ADDRESS: 0.0.0.0:8200
    cap_add:
      - IPC_LOCK
    ports:
      - "8200:8200"

  prometheus:
    image: prom/prometheus:v2.48.0
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:10.2.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"

  jaeger:
    image: jaegertracing/all-in-one:1.52
    ports:
      - "6831:6831/udp"  # Thrift compact
      - "16686:16686"    # UI

  debezium-connect:
    image: debezium/connect:2.5
    environment:
      BOOTSTRAP_SERVERS: kafka:9092
      GROUP_ID: cdc-connectors
      CONFIG_STORAGE_TOPIC: _connect-configs
      OFFSET_STORAGE_TOPIC: _connect-offsets
      STATUS_STORAGE_TOPIC: _connect-status
    ports:
      - "8083:8083"
    depends_on:
      kafka:
        condition: service_healthy
      cassandra:
        condition: service_healthy

  cdc-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
      VAULT_ADDR: http://vault:8200
      VAULT_TOKEN: dev-root-token
    depends_on:
      - kafka
      - postgres
      - redis
      - vault

volumes:
  cassandra_data:
  kafka_data:
  postgres_data:
  redis_data:
  prometheus_data:
  grafana_data:
```

### Startup Command

```bash
# Start all services
docker compose up -d

# Check health
docker compose ps

# View logs
docker compose logs -f cdc-worker

# Stop all
docker compose down -v  # -v removes volumes (fresh start)
```

### Resource Limits (16GB laptop)

```yaml
# Per-service resource limits
services:
  cassandra:
    mem_limit: 2g
  kafka:
    mem_limit: 1g
  postgres:
    mem_limit: 512m
  redis:
    mem_limit: 256m
  # Total: ~6GB for infrastructure, leaves 10GB for OS + worker
```

### References

- [Docker Compose v2 Spec](https://docs.docker.com/compose/compose-file/)
- [Debezium Docker Images](https://hub.docker.com/r/debezium/connect)

---

## 11. Mock Data Generation

### Decision

**Use Faker + custom data generators**

### Faker Integration

```python
from faker import Faker

fake = Faker()

# Generate test users
def generate_user():
    return {
        'user_id': fake.uuid4(),
        'email': fake.email(),
        'name': fake.name(),
        'age': fake.random_int(18, 80),
        'created_at': fake.date_time_this_year(),
        'address': {
            'street': fake.street_address(),
            'city': fake.city(),
            'zipcode': fake.zipcode(),
        }
    }

# Insert into Cassandra
from cassandra.cluster import Cluster

cluster = Cluster(['localhost'])
session = cluster.connect('test_keyspace')

for _ in range(1000):
    user = generate_user()
    session.execute(
        """
        INSERT INTO users (user_id, email, name, age, created_at, address)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user['user_id'], user['email'], user['name'], user['age'], user['created_at'], user['address'])
    )
```

### Load Testing Data

**Locust** scenario:
```python
# tests/performance/locustfile.py
from locust import task, between, User
from cassandra.cluster import Cluster

class CassandraUser(User):
    wait_time = between(0.1, 0.5)  # 0.1-0.5s delay between requests

    def on_start(self):
        self.cluster = Cluster(['localhost'])
        self.session = self.cluster.connect('test_keyspace')

    @task
    def insert_user(self):
        user = generate_user()
        self.session.execute(...)
```

Run load test:
```bash
locust -f tests/performance/locustfile.py --host=localhost --users=100 --spawn-rate=10
```

### Alternatives Considered

- **Mimesis**: Similar to Faker, slightly faster but smaller community
- **factory_boy**: Django-focused, overkill for simple data generation
- **Custom generators**: Maximum control but more maintenance

### References

- [Faker Documentation](https://faker.readthedocs.io/)
- [Locust Load Testing](https://locust.io/)

---

## 12. Best Practices Summary

### Performance Optimization

1. **Batch Writes**: PostgreSQL inserts use `COPY` or `INSERT ... VALUES (...)` with 1000+ rows
2. **Connection Pooling**: psycopg3 pools (min=5, max=20 connections), redis-py pools
3. **Kafka Consumer Tuning**: `max.poll.records=500`, `fetch.min.bytes=1MB` to reduce overhead
4. **Redis Pipelining**: Batch Redis commands (checkpoints, schema reads) in pipelines
5. **Async I/O**: Use `asyncio` for concurrent I/O operations (Kafka consume + PostgreSQL write)

### Reliability Patterns

1. **Idempotency Keys**: PostgreSQL upserts with `ON CONFLICT (primary_key) DO UPDATE`
2. **At-Least-Once + Deduplication**: Kafka consumer offsets committed after PostgreSQL transaction
3. **Graceful Shutdown**: SIGTERM handler drains Kafka consumer, commits checkpoints, closes connections
4. **Health Checks**: Readiness probe checks Redis/PostgreSQL connectivity, liveness probe checks worker heartbeat

### Operational Excellence

1. **Runbooks**: Document failure scenarios (Kafka down, PostgreSQL full, Redis OOM)
2. **Alerts**: Prometheus alerts for lag >2min, error rate >1%, DLQ size >1000
3. **Log Aggregation**: Ship structlog JSON to ELK stack or Loki for centralized search
4. **Capacity Planning**: Track Kafka disk usage, PostgreSQL table sizes, Redis memory usage

### Security Hardening

1. **Principle of Least Privilege**: Database users have minimal permissions (SELECT on Cassandra, INSERT on PostgreSQL)
2. **Network Segmentation**: Workers in private subnet, only admin API exposed
3. **Secret Rotation**: Vault dynamic secrets with TTL (rotate every 30 days)
4. **Audit Logging**: All admin API calls logged to audit trail (immutable log)

### Testing Strategy

1. **Unit Tests**: Mock all I/O (Kafka, PostgreSQL, Redis), test business logic in isolation
2. **Integration Tests**: Use testcontainers to spin up real Cassandra/Kafka/PostgreSQL, test end-to-end flow
3. **Contract Tests**: Validate Kafka event schemas match Pydantic models
4. **Performance Tests**: Run Locust load tests in CI, fail build if P95 latency regresses >10%
5. **Chaos Tests**: Simulate failures (kill Kafka, fill PostgreSQL disk) and verify recovery

---

## Conclusion

All technical decisions prioritize open-source, production-proven tools that align with the project constitution. The architecture balances simplicity (single Python codebase) with reliability (Kafka durability, Redis coordination, comprehensive observability). Local development environment in Docker Compose v2 enables full end-to-end testing on developer laptops without external dependencies.

**Next Steps**: Proceed to Phase 1 to design data models, API contracts, and quickstart guide.
