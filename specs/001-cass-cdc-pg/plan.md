# Implementation Plan: Cassandra-to-PostgreSQL CDC Pipeline

**Branch**: `001-cass-cdc-pg` | **Date**: 2025-11-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-cass-cdc-pg/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Build an enterprise-grade Change Data Capture (CDC) pipeline that captures data changes from Cassandra cluster and replicates them to PostgreSQL data warehouse with production-level reliability, observability, and high availability. The pipeline uses Debezium connectors with Kafka as the message backbone, leverages Redis for distributed coordination and metadata caching, and implements comprehensive error handling with retry strategies, schema evolution support, and dirty data validation. Local development environment runs entirely in Docker Compose v2, enabling full end-to-end testing on developer laptops.

**Technical Approach**: Debezium Cassandra connector captures CDC events → Kafka topics provide durable event log → Custom Kafka Connect sink (or standalone consumers) writes to PostgreSQL → Redis coordinates worker state and caches metadata → Prometheus + Grafana + OpenTelemetry provide observability → HashiCorp Vault manages secrets → All components containerized for local development.

## Technical Context

**Language/Version**: Python 3.11 (pipeline workers, data validation, transformation logic)

**Primary Dependencies**:
- Apache Cassandra 4.1.x (latest stable) with CDC enabled
- Apache Kafka 3.6.x (message backbone for CDC events)
- Debezium 2.5.x (Cassandra CDC connector)
- PostgreSQL 16.x (target data warehouse)
- Redis 7.2.x (distributed cache for metadata and coordination)
- Kafka Connect 3.6.x (connector framework)

**Storage**:
- Source: Cassandra 4.1.x cluster with CDC commitlog enabled
- Target: PostgreSQL 16.x data warehouse
- Metadata Cache: Redis 7.2.x with persistence (AOF + RDB snapshots)
- Event Log: Kafka 3.6.x topics with configurable retention

**Testing**:
- pytest 7.4+ (unit and integration tests)
- testcontainers-python 3.7+ (integration tests with real Cassandra/Kafka/PostgreSQL containers)
- pytest-cov (code coverage tracking, target 80%)
- pytest-asyncio (async test support)
- Faker 20+ (mock data generation)

**Target Platform**: Linux server (x86_64), Docker containers for all components, Kubernetes-ready deployment

**Project Type**: Single project (distributed pipeline system with multiple worker types)

**Performance Goals**:
- Throughput: ≥1000 events/second per worker instance
- Latency: P95 end-to-end replication <5 seconds
- Replication lag: <30 seconds steady-state
- Checkpoint interval: Every 10 seconds or 1000 records
- Recovery time: <60 seconds from restart

**Constraints**:
- Memory: 4GB RAM per worker minimum, 16GB for local dev environment
- CPU: 2 cores per worker minimum
- Network: <10ms latency between components (same datacenter/region)
- Storage: Kafka retention configurable (default 7 days), Redis persistence enabled

**Scale/Scope**:
- Event volume: Designed for millions of events per day
- Table count: Support 50+ Cassandra tables simultaneously
- Worker count: Horizontally scalable (3-10 workers typical)
- Local dev: Runnable on laptop with 16GB RAM, 4 CPU cores

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### ✅ Principle I: Test-First Development (NON-NEGOTIABLE)

**Status**: PASS (by design commitment)

**Compliance**:
- Architecture includes comprehensive test strategy (unit, integration, contract, E2E)
- testcontainers-python enables real integration tests locally
- pytest with coverage tracking enforces 80% minimum
- Mock data generation (Faker) supports test scenario creation
- All user stories include detailed acceptance criteria for test-first development

**Validation**: TDD methodology will be enforced through PR reviews and CI pipeline (tests must exist and fail before implementation merged).

---

### ✅ Principle II: Clean, Maintainable Code

**Status**: PASS

**Compliance**:
- Python 3.11 with type hints for self-documenting code
- Ruff linter + Black formatter enforce consistent style
- Modular architecture with clear separation of concerns:
  - CDC readers (Debezium/Kafka consumers)
  - Data validators (schema validation, dirty data handling)
  - Writers (PostgreSQL sink)
  - Coordinators (Redis-based state management)
- Function/file length limits enforced by linter configuration

**Tooling**:
- Ruff 0.1+ (fast Python linter, replaces Flake8/isort/pyupgrade)
- Black 23+ (code formatter)
- mypy 1.7+ (static type checker)
- Pre-commit hooks enforce style checks

---

### ✅ Principle III: Robust Architecture & Design Patterns

**Status**: PASS

**Compliance**:
- **Event Sourcing**: Kafka provides immutable event log
- **Repository Pattern**: Abstracted data access for Cassandra reads, PostgreSQL writes
- **Circuit Breaker**: Implemented via resilience4j pattern in Python (pybreaker library)
- **Retry with Exponential Backoff**: tenacity library for declarative retry logic
- **Idempotency**: PostgreSQL upserts with unique constraints, Kafka consumer offsets for exactly-once semantics
- **CQRS**: Separate read path (Debezium → Kafka) from write path (consumers → PostgreSQL)
- **Dependency Injection**: Dependency-injector library for testable components

**Libraries**:
- tenacity 8.2+ (retry logic)
- pybreaker 1.0+ (circuit breaker)
- dependency-injector 4.41+ (DI container)

---

### ✅ Principle IV: Data Integrity & Consistency

**Status**: PASS

**Compliance**:
- **Schema Validation**: Pydantic 2.5+ models validate every event against expected schema
- **Checksums**: Kafka message checksums, optional application-level CRC32 for blob fields
- **Atomic Transactions**: PostgreSQL ACID transactions for multi-row writes
- **Exactly-Once Delivery**: Kafka consumer offsets + PostgreSQL upserts with unique constraints
- **Data Lineage**: Every event tagged with source table, timestamp, Cassandra node, Kafka offset
- **Audit Logging**: Separate audit log topic in Kafka for all transformations
- **Reconciliation**: Periodic batch job compares Cassandra→PostgreSQL row counts and checksums

**Tooling**:
- Pydantic 2.5+ (schema validation with Python type hints)
- PostgreSQL constraints (unique indexes, foreign keys, check constraints)
- Kafka transactional producers for multi-step operations

---

### ✅ Principle V: Observability & Operational Excellence

**Status**: PASS

**Compliance**:
- **Structured Logging**: Python structlog library outputs JSON logs with correlation IDs
- **Metrics**: Prometheus client library exposes metrics (counters, histograms, gauges)
- **Distributed Tracing**: OpenTelemetry Python SDK with Jaeger backend
- **Health Checks**: FastAPI endpoints for liveness/readiness probes
- **Runbooks**: Documentation includes failure scenarios and remediation steps
- **Alerting**: Prometheus AlertManager rules for lag, error rate, queue depth thresholds
- **Profiling**: py-spy for production profiling, cProfile for development

**Tooling** (all open-source):
- structlog 23.2+ (structured logging)
- prometheus-client 0.19+ (metrics)
- OpenTelemetry SDK 1.21+ (distributed tracing)
- Jaeger 1.52+ (trace visualization)
- Grafana 10.2+ (metrics dashboards)
- Prometheus 2.48+ (metrics storage and alerting)

---

### ✅ Principle VI: Scalability & Performance

**Status**: PASS

**Compliance**:
- **Stateless Workers**: All state in Redis/Kafka, workers are ephemeral
- **Partitioned Workloads**: Kafka partitions enable parallel processing, Redis distributed locks for table assignment
- **Backpressure**: Kafka consumer `max.poll.records` and `fetch.max.wait.ms` provide flow control
- **Configurable Batching**: Batch size and flush interval tunable per environment
- **Resource Limits**: Docker memory/CPU limits, Python connection pools with max size
- **Benchmarks**: Locust 2.20+ for load testing, results tracked in Git
- **Load Testing**: testcontainers + pytest-benchmark for repeatable performance tests

**Performance Targets** (from spec):
- ≥1000 events/sec per worker ✓
- P95 latency <5s ✓
- Lag <30s ✓
- Recovery <60s ✓

**Tooling**:
- Locust 2.20+ (load testing)
- pytest-benchmark 4.0+ (microbenchmarks)

---

### ✅ Principle VII: Security & Compliance

**Status**: PASS

**Compliance**:
- **Secret Management**: HashiCorp Vault (open-source) for credentials, API keys
- **Least Privilege**: Database users with minimal required permissions (SELECT on Cassandra, INSERT/UPDATE on PostgreSQL)
- **TLS Everywhere**:
  - Cassandra client TLS
  - Kafka SSL/SASL authentication
  - PostgreSQL SSL mode=require
  - Redis TLS mode
- **Sensitive Data Masking**: structlog processors mask PII fields in logs (email, SSN patterns)
- **SQL Injection Prevention**: psycopg3 parameterized queries only
- **Input Validation**: Pydantic models validate all external inputs
- **Security Scanning**: Trivy 0.48+ scans Docker images, Safety checks Python dependencies
- **Audit Trail**: Configuration changes logged to audit topic in Kafka

**Tooling** (all open-source):
- HashiCorp Vault 1.15+ (secrets management)
- Trivy 0.48+ (container vulnerability scanning)
- Safety 2.3+ (Python dependency vulnerability scanning)
- Bandit 1.7+ (Python security linter)

---

### ✅ Enterprise Production Requirements

**High Availability**: ✓
- No SPOF: Multiple workers, Kafka replication (min 3 brokers), Redis Sentinel/Cluster
- Graceful Degradation: Circuit breakers halt writes on PostgreSQL failure, events buffer in Kafka
- Automatic Failover: Kafka consumer group rebalancing, Redis Sentinel for cache failover
- Zero-Downtime Deployment: Rolling updates via Kubernetes or Docker Swarm, health checks prevent traffic to unhealthy workers

**Disaster Recovery**: ✓
- Checkpointing: Redis persistence (AOF + RDB), Kafka consumer offsets committed per batch
- Resume from Checkpoint: Workers read last committed offset from Redis/Kafka
- Dead Letter Queue: Kafka topic for failed events, configurable retention (default 30 days)
- Backup Procedures: Automated Redis RDB backups, Kafka topic backups, PostgreSQL pg_dump scripts

**Configuration Management**: ✓
- Externalized Config: Environment variables + YAML files (12-factor app)
- Environment Separation: .env.dev, .env.staging, .env.prod files
- No Code Changes for Config: All tunable parameters in config files
- Schema Migrations: Alembic for PostgreSQL DDL changes (reversible migrations)

**Versioning & Breaking Changes**: ✓
- Semantic Versioning: Git tags, Docker image tags follow MAJOR.MINOR.PATCH
- Breaking Changes: Increment MAJOR version, coordinate with downstream consumers
- Deprecation: Log warnings for 1 MINOR version before removal
- Schema Evolution: Avro schemas in Kafka Schema Registry for forward/backward compatibility

---

### 🔍 Gate Evaluation

**Result**: ✅ **PASS** - All constitutional principles satisfied

**Justification**: Architecture leverages proven open-source technologies that align with all 7 principles. Debezium + Kafka provide event sourcing and durability, Redis enables stateless workers, comprehensive tooling (pytest, structlog, Prometheus, OpenTelemetry) ensures observability and quality, HashiCorp Vault secures credentials. No constitutional violations requiring justification.

**Proceed to Phase 0**: Research specific implementation patterns and best practices.

## Project Structure

### Documentation (this feature)

```text
specs/001-cass-cdc-pg/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── events/          # Kafka event schemas (Avro or JSON Schema)
│   ├── api/             # Admin/monitoring API contracts (OpenAPI)
│   └── data-models/     # Pydantic models for internal data structures
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
# Single project structure for distributed CDC pipeline
src/
├── cdc_pipeline/                # Main package
│   ├── __init__.py
│   ├── config/                  # Configuration management
│   │   ├── __init__.py
│   │   ├── settings.py          # Pydantic settings models
│   │   └── vault.py             # HashiCorp Vault client
│   ├── connectors/              # Data source/sink connectors
│   │   ├── __init__.py
│   │   ├── cassandra_reader.py  # Debezium event consumer
│   │   ├── kafka_consumer.py    # Kafka consumer wrapper
│   │   └── postgres_writer.py   # PostgreSQL sink with batching
│   ├── models/                  # Data models (Pydantic)
│   │   ├── __init__.py
│   │   ├── events.py            # CDC event models
│   │   ├── schemas.py           # Schema metadata models
│   │   └── checkpoints.py       # Checkpoint state models
│   ├── services/                # Business logic
│   │   ├── __init__.py
│   │   ├── event_processor.py   # Core CDC event processing
│   │   ├── schema_registry.py   # Schema evolution detection
│   │   ├── validator.py         # Data quality validation
│   │   ├── transformer.py       # Data type transformations
│   │   └── coordinator.py       # Worker coordination (Redis)
│   ├── repositories/            # Repository pattern implementations
│   │   ├── __init__.py
│   │   ├── checkpoint_repo.py   # Redis checkpoint storage
│   │   ├── schema_repo.py       # Redis schema cache
│   │   └── metrics_repo.py      # Prometheus metrics registry
│   ├── workers/                 # Worker entry points
│   │   ├── __init__.py
│   │   ├── replication_worker.py    # Main CDC worker
│   │   ├── reconciliation_worker.py # Periodic data validation
│   │   └── dlq_processor.py         # Dead letter queue handler
│   ├── observability/           # Observability infrastructure
│   │   ├── __init__.py
│   │   ├── logging.py           # structlog configuration
│   │   ├── metrics.py           # Prometheus metrics
│   │   └── tracing.py           # OpenTelemetry setup
│   ├── resilience/              # Reliability patterns
│   │   ├── __init__.py
│   │   ├── retry.py             # tenacity retry decorators
│   │   ├── circuit_breaker.py   # pybreaker wrappers
│   │   └── idempotency.py       # Idempotency helpers
│   └── api/                     # Admin/monitoring API
│       ├── __init__.py
│       ├── health.py            # Health check endpoints
│       └── admin.py             # Admin operations (pause/resume, metrics)
├── cli/                         # Command-line interface
│   ├── __init__.py
│   └── main.py                  # Click-based CLI
└── scripts/                     # Operational scripts
    ├── setup_vault.sh           # Initialize Vault secrets
    ├── create_kafka_topics.sh   # Kafka topic provisioning
    └── init_postgres_schema.py  # PostgreSQL schema initialization

tests/
├── unit/                        # Fast isolated tests
│   ├── __init__.py
│   ├── test_validator.py
│   ├── test_transformer.py
│   └── test_models.py
├── integration/                 # Tests with real dependencies (testcontainers)
│   ├── __init__.py
│   ├── test_cassandra_kafka.py
│   ├── test_kafka_postgres.py
│   └── test_end_to_end.py
├── contract/                    # Schema contract tests
│   ├── __init__.py
│   ├── test_event_schemas.py
│   └── test_api_contracts.py
└── performance/                 # Load and benchmark tests
    ├── __init__.py
    ├── test_throughput.py
    └── locustfile.py            # Locust load test scenarios

docker/                          # Docker and orchestration
├── Dockerfile.worker            # CDC worker image
├── Dockerfile.api               # Admin API image
├── docker-compose.yml           # Local development stack (v2)
├── docker-compose.test.yml      # Test environment
└── docker-compose.prod.yml      # Production-like local setup

config/                          # Configuration files
├── dev/                         # Development environment
│   ├── .env.dev
│   ├── kafka.properties
│   └── redis.conf
├── staging/
│   └── .env.staging
├── prod/
│   └── .env.prod.example        # Template (secrets from Vault)
└── alembic/                     # PostgreSQL migrations
    ├── alembic.ini
    ├── env.py
    └── versions/

docs/                            # Project documentation
├── architecture.md              # System architecture diagrams
├── runbooks/                    # Operational runbooks
│   ├── troubleshooting.md
│   ├── scaling.md
│   └── disaster_recovery.md
└── adr/                         # Architecture Decision Records
    ├── 001-debezium-vs-custom-cdc.md
    ├── 002-kafka-vs-pulsar.md
    └── 003-redis-vs-etcd.md

monitoring/                      # Observability configuration
├── prometheus/
│   ├── prometheus.yml
│   └── alerts.yml
├── grafana/
│   └── dashboards/
│       ├── pipeline_overview.json
│       └── worker_metrics.json
└── jaeger/
    └── jaeger-config.yml

.github/                         # CI/CD
├── workflows/
│   ├── ci.yml                   # Run tests, linting, security scans
│   ├── cd.yml                   # Build and push Docker images
│   └── performance.yml          # Scheduled performance tests
└── dependabot.yml               # Dependency updates

pyproject.toml                   # Python project metadata (Poetry or setuptools)
poetry.lock                      # Locked dependencies
.pre-commit-config.yaml          # Pre-commit hooks (Black, Ruff, mypy)
pytest.ini                       # pytest configuration
mypy.ini                         # mypy type checking configuration
.ruff.toml                       # Ruff linter configuration
README.md                        # Project overview and quickstart
LICENSE                          # License file
.gitignore                       # Git ignore patterns
```

**Structure Decision**:

Selected **single project structure** because this is a cohesive distributed system with shared data models, configuration, and observability infrastructure. While the system has multiple worker types (replication, reconciliation, DLQ processing), they all share the same codebase and are variations of the same pipeline logic.

Key structural decisions:
1. **Package-by-feature within `src/cdc_pipeline/`**: Each subdirectory represents a functional area (connectors, services, workers) rather than technical layers
2. **Repository pattern**: Abstracts Redis, Kafka, PostgreSQL access for testability
3. **Observability as first-class**: Dedicated `observability/` module for logging, metrics, tracing
4. **Docker Compose v2**: Multi-service local development in `docker/docker-compose.yml`
5. **Configuration externalization**: All environments in `config/` directory, secrets from Vault
6. **Comprehensive testing**: Separate directories for unit, integration, contract, performance tests

This structure supports the constitution's principles:
- **TDD**: Clear separation of tests from implementation
- **Clean Code**: SRP applied at module level, max 500 lines per file enforced by linter
- **Observability**: Centralized in `observability/` module
- **Scalability**: Stateless workers in `workers/` directory
- **Security**: Vault integration in `config/vault.py`, secrets never committed

## Complexity Tracking

> **No violations** - Constitution check passed. This section is empty as no complexity justification is required.

