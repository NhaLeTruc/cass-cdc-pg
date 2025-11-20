# Tasks: Cassandra-to-PostgreSQL CDC Pipeline

**Input**: Design documents from `/specs/001-cass-cdc-pg/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are included for ALL user stories as this is a TDD project per constitution (Principle I: Test-First Development - NON-NEGOTIABLE).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root
- Paths follow plan.md structure: `src/cdc_pipeline/`, `tests/unit/`, `tests/integration/`, `tests/contract/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Create project directory structure per plan.md (src/cdc_pipeline/{config,connectors,models,services,repositories,workers,observability,resilience,api}, tests/{unit,integration,contract,performance}, docker/, config/, docs/, monitoring/)
- [ ] T002 Initialize Python project with pyproject.toml (Poetry/setuptools with Python 3.11, all dependencies from research.md)
- [ ] T003 [P] Create .gitignore file with Python, Docker, IDE patterns
- [ ] T004 [P] Create LICENSE file (choose appropriate open-source license)
- [ ] T005 [P] Create README.md with project overview and quickstart reference
- [ ] T006 [P] Configure Ruff linter in .ruff.toml (max line length 100, select E,F,W,I rules)
- [ ] T007 [P] Configure Black formatter in pyproject.toml (line-length 100, target-version py311)
- [ ] T008 [P] Configure mypy in mypy.ini (strict mode, allow untyped decorators)
- [ ] T009 [P] Configure pytest in pytest.ini (asyncio_mode=auto, testpaths=tests, addopts for coverage)
- [ ] T010 [P] Create .pre-commit-config.yaml with hooks (black, ruff, mypy, trailing-whitespace)
- [ ] T011 [P] Create Dockerfile.worker in docker/ (Python 3.11-slim base, install dependencies, ENTRYPOINT python -m cdc_pipeline.workers.replication_worker)
- [ ] T012 [P] Create Dockerfile.api in docker/ (Python 3.11-slim, FastAPI app, uvicorn server)
- [ ] T013 Create docker-compose.yml in docker/ with all services (Cassandra 4.1, Kafka 3.6 KRaft, PostgreSQL 16, Redis 7.2, Vault, Prometheus, Grafana, Jaeger, Debezium Connect) per quickstart.md
- [ ] T014 [P] Create docker-compose.test.yml for test environment (testcontainers will also spin up services)
- [ ] T015 [P] Create config/dev/.env.dev with development environment variables
- [ ] T016 [P] Create config/dev/kafka.properties with Kafka consumer config
- [ ] T017 [P] Create config/dev/redis.conf with Redis persistence settings (AOF + RDB)
- [ ] T018 [P] Create monitoring/prometheus/prometheus.yml with scrape config for CDC worker metrics endpoint
- [ ] T019 [P] Create monitoring/prometheus/alerts.yml with alert rules (lag > 2min, error rate > 1%, DLQ size > 10000)
- [ ] T020 [P] Create monitoring/grafana/dashboards/pipeline_overview.json (copy from Grafana, export JSON)
- [ ] T021 [P] Create monitoring/grafana/dashboards/worker_metrics.json for per-worker metrics
- [ ] T022 [P] Create .github/workflows/ci.yml for CI pipeline (pytest, ruff, mypy, coverage, Trivy scan, Safety check)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T023 Create src/cdc_pipeline/__init__.py with package version
- [ ] T024 Create src/cdc_pipeline/config/__init__.py
- [ ] T025 Create src/cdc_pipeline/config/settings.py with Pydantic Settings model (load from env vars: KAFKA_BOOTSTRAP_SERVERS, POSTGRES_HOST, REDIS_HOST, VAULT_ADDR, etc.)
- [ ] T026 Create src/cdc_pipeline/config/vault.py with HashiCorp Vault client wrapper (hvac library, methods: get_secret, list_secrets)
- [ ] T027 [P] Create src/cdc_pipeline/models/__init__.py
- [ ] T028 [P] Create src/cdc_pipeline/models/events.py with ChangeEvent Pydantic model (from contracts/data-models/change_event.py)
- [ ] T029 [P] Create src/cdc_pipeline/models/checkpoints.py with ReplicationCheckpoint Pydantic model
- [ ] T030 [P] Create src/cdc_pipeline/models/schemas.py with SchemaDefinition and ColumnDefinition Pydantic models
- [ ] T031 [P] Create src/cdc_pipeline/observability/__init__.py
- [ ] T032 Create src/cdc_pipeline/observability/logging.py with structlog configuration (JSON processor, add logger name, add log level, add timestamp, context injector)
- [ ] T033 [P] Create src/cdc_pipeline/observability/metrics.py with Prometheus metric definitions (events_processed_total Counter, replication_latency_seconds Histogram, replication_lag_seconds Gauge, error_total Counter, dlq_size Gauge)
- [ ] T034 [P] Create src/cdc_pipeline/observability/tracing.py with OpenTelemetry setup (TracerProvider, JaegerExporter, BatchSpanProcessor)
- [ ] T035 [P] Create src/cdc_pipeline/resilience/__init__.py
- [ ] T036 [P] Create src/cdc_pipeline/resilience/retry.py with tenacity retry decorators (exponential backoff: multiplier=1, min=1s, max=60s, max_attempts=10)
- [ ] T037 [P] Create src/cdc_pipeline/resilience/circuit_breaker.py with pybreaker CircuitBreaker wrappers (fail_max=5, timeout_duration=30s)
- [ ] T038 [P] Create src/cdc_pipeline/resilience/idempotency.py with idempotency helpers (generate idempotency key from event)
- [ ] T039 Create src/cdc_pipeline/repositories/__init__.py
- [ ] T040 Create src/cdc_pipeline/repositories/checkpoint_repo.py with RedisCheckpointRepository (methods: get_checkpoint, save_checkpoint, list_checkpoints, Redis key pattern: checkpoint:{table}:{partition})
- [ ] T041 [P] Create src/cdc_pipeline/repositories/schema_repo.py with RedisSchemaRepository (methods: get_schema, save_schema, invalidate_schema, TTL 3600s)
- [ ] T042 [P] Create src/cdc_pipeline/repositories/metrics_repo.py with PrometheusMetricsRepository (wrapper for prometheus_client, expose /metrics endpoint)
- [ ] T043 Create src/cdc_pipeline/connectors/__init__.py
- [ ] T044 Create src/cdc_pipeline/connectors/kafka_consumer.py with KafkaConsumerWrapper (confluent_kafka Consumer, subscribe to topics, poll messages, commit offsets, handle rebalance)
- [ ] T045 Create src/cdc_pipeline/connectors/postgres_writer.py with PostgreSQLWriter (psycopg3 async connection pool, batch upsert with ON CONFLICT DO UPDATE, transaction management)
- [ ] T046 Create src/cdc_pipeline/api/__init__.py
- [ ] T047 Create src/cdc_pipeline/api/health.py with FastAPI health check endpoints (/health/liveness returns 200, /health/readiness checks Kafka/PostgreSQL/Redis connectivity)
- [ ] T048 [P] Create src/cdc_pipeline/api/admin.py with admin endpoints (pause/resume pipeline, trigger rebalance, get worker status) per contracts/api/admin-api.yaml
- [ ] T049 Create scripts/setup_vault.sh to initialize Vault with dev secrets (Cassandra, Kafka, PostgreSQL, Redis credentials)
- [ ] T050 [P] Create scripts/create_kafka_topics.sh to create Kafka topics (cassandra.<keyspace>.<table>, cassandra.cdc.dlq, cassandra.cdc.staleness_audit, cassandra.cdc.validation_errors)
- [ ] T051 [P] Create scripts/init_postgres_schema.py with Alembic migration to create base tables (_cdc_metadata, error_log, dlq_archive, staleness_audit, validation_errors)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Basic Change Capture and Replication (Priority: P1) 🎯 MVP

**Goal**: Capture changes from Cassandra tables and replicate to PostgreSQL with <30s latency and 100% data accuracy

**Independent Test**: Insert records into Cassandra table, verify they appear in PostgreSQL within 30 seconds with all field values matching

### Tests for User Story 1 (TDD - Write FIRST, ensure FAIL before implementation) ⚠️

- [ ] T052 [P] [US1] Create tests/unit/test_event_processor.py with unit tests for event validation (invalid operation type, missing primary key, before/after data consistency)
- [ ] T053 [P] [US1] Create tests/unit/test_transformer.py with unit tests for Cassandra→PostgreSQL type transformations (uuid, text, int, timestamp, list, map)
- [ ] T054 [P] [US1] Create tests/contract/test_event_schemas.py with Avro schema validation tests (ChangeEvent schema from contracts/events/change-event.avsc)
- [ ] T055 [US1] Create tests/integration/test_cassandra_kafka.py with testcontainers integration test (start Cassandra+Kafka, insert record with CDC enabled, verify event in Kafka topic)
- [ ] T056 [US1] Create tests/integration/test_kafka_postgres.py with testcontainers integration test (publish ChangeEvent to Kafka, verify worker consumes and writes to PostgreSQL)
- [ ] T057 [US1] Create tests/integration/test_end_to_end.py with full pipeline test (Cassandra INSERT/UPDATE/DELETE → verify PostgreSQL reflects changes within 30s, validate field-by-field)

**Run tests - ALL should FAIL (no implementation yet)**: `pytest tests/unit/test_event_processor.py tests/unit/test_transformer.py tests/contract/test_event_schemas.py -v`

### Implementation for User Story 1

- [ ] T058 [P] [US1] Create src/cdc_pipeline/services/__init__.py
- [ ] T059 [P] [US1] Create src/cdc_pipeline/services/transformer.py with CassandraToPostgresTransformer (methods: transform_event, map_cassandra_type_to_postgres, handle_collections, handle_udts_to_jsonb)
- [ ] T060 [P] [US1] Create src/cdc_pipeline/services/validator.py with EventValidator (validate ChangeEvent against Pydantic schema, check operation/data consistency, validate primary key non-empty)
- [ ] T061 [US1] Create src/cdc_pipeline/services/event_processor.py with EventProcessor (orchestrates: receive event → validate → transform → write, uses validator, transformer, postgres_writer, checkpoint_repo)
- [ ] T062 [US1] Create src/cdc_pipeline/workers/__init__.py
- [ ] T063 [US1] Create src/cdc_pipeline/workers/replication_worker.py with ReplicationWorker (main worker: initialize Kafka consumer, poll events, process via EventProcessor, commit checkpoints every 10s or 1000 records, handle SIGTERM gracefully)
- [ ] T064 [US1] Create src/cli/__init__.py and src/cli/main.py with Click CLI (commands: start-worker, status, pause, resume)
- [ ] T065 [US1] Add Debezium connector configuration to config/debezium/cassandra-connector.json (connector.class: CassandraConnector, keyspace whitelist, CDC table, Kafka topic prefix)
- [ ] T066 [US1] Update docker-compose.yml to start cdc-worker service with environment variables

**Run tests - ALL should PASS now**: `pytest tests/unit/ tests/contract/ tests/integration/ -v`

**Checkpoint**: At this point, User Story 1 (basic replication) should be fully functional and testable independently. Run quickstart.md steps to verify end-to-end.

---

## Phase 4: User Story 2 - Local Development Testing (Priority: P2)

**Goal**: Enable developers to run full CDC pipeline locally on 16GB laptop using Docker Compose v2

**Independent Test**: Run `docker compose up`, insert Cassandra data, verify replication to local PostgreSQL within 30s, run test suite completes in <5 minutes

### Tests for User Story 2 (TDD - Write FIRST) ⚠️

- [ ] T067 [P] [US2] Create tests/integration/test_local_stack.py with test that starts full stack via testcontainers (all 11 services), verifies all healthy, runs basic replication test
- [ ] T068 [P] [US2] Create tests/integration/test_docker_resource_limits.py with test that verifies Docker resource usage stays within limits (measure container memory/CPU, assert total < 8GB RAM)
- [ ] T069 [US2] Create tests/performance/test_local_performance.py with pytest-benchmark test that measures local throughput (generate 1000 events, measure time, assert >= 100 events/sec minimum for local dev)

**Run tests - Should FAIL (Docker Compose not fully configured yet)**

### Implementation for User Story 2

- [ ] T070 [P] [US2] Update docker-compose.yml with resource limits per service (Cassandra 2g, Kafka 1g, PostgreSQL 512m, Redis 256m, workers 1g each)
- [ ] T071 [P] [US2] Add healthcheck configurations to all services in docker-compose.yml (cqlsh for Cassandra, kafka-topics for Kafka, pg_isready for PostgreSQL)
- [ ] T072 [P] [US2] Create scripts/generate_test_data.py with Faker to generate sample CDC events (users table: 1000 records with realistic names, emails, ages)
- [ ] T073 [US2] Create docker-compose.test.yml optimized for test runs (single replica for each service, shorter timeouts, test-specific environment variables)
- [ ] T074 [US2] Update quickstart.md with verified step-by-step instructions (incorporate actual commands from testing)
- [ ] T075 [US2] Create docs/troubleshooting.md with common issues and solutions (connector not starting, no data in PostgreSQL, high lag, OOM errors) from quickstart.md
- [ ] T076 [US2] Add monitoring/grafana/dashboards/local_dev.json simplified dashboard for local development (fewer panels, 5-minute refresh)

**Run tests - Should PASS now**: `pytest tests/integration/test_local_stack.py tests/integration/test_docker_resource_limits.py -v`

**Checkpoint**: Developers can now `docker compose up` and have fully functional local CDC pipeline in <2 minutes

---

## Phase 5: User Story 3 - Failure Recovery and Retry (Priority: P3)

**Goal**: Automatically recover from transient failures with exponential backoff, without data loss or manual intervention

**Independent Test**: Simulate PostgreSQL failure, verify worker retries with backoff, verify all data eventually replicates once PostgreSQL recovers

### Tests for User Story 3 (TDD - Write FIRST) ⚠️

- [ ] T077 [P] [US3] Create tests/unit/test_retry_logic.py with unit tests for retry decorator (mock transient exceptions, verify exponential backoff timing: 1s, 2s, 4s, 8s)
- [ ] T078 [P] [US3] Create tests/unit/test_circuit_breaker.py with unit tests for circuit breaker (fail 5 times → open, wait 30s → half-open, success → close)
- [ ] T079 [US3] Create tests/integration/test_postgres_failure.py with integration test (start pipeline, insert Cassandra data, stop PostgreSQL container, wait, restart PostgreSQL, verify data eventually written)
- [ ] T080 [US3] Create tests/integration/test_dlq_routing.py with integration test (simulate record exceeding 10 retries, verify moved to DLQ Kafka topic with full context)

**Run tests - Should FAIL (retry/circuit breaker not implemented yet)**

### Implementation for User Story 3

- [ ] T081 [P] [US3] Update src/cdc_pipeline/resilience/retry.py to add @retry_on_transient_error decorator (retries psycopg.OperationalError, redis.ConnectionError, kafka errors with exponential backoff)
- [ ] T082 [P] [US3] Update src/cdc_pipeline/resilience/circuit_breaker.py to add postgres_circuit_breaker instance (wrap postgres_writer methods)
- [ ] T083 [P] [US3] Create src/cdc_pipeline/models/errors.py with ErrorRecord Pydantic model (from data-model.md)
- [ ] T084 [US3] Update src/cdc_pipeline/services/event_processor.py to add error handling (try/except around write, increment attempt_count, route to DLQ after 10 attempts)
- [ ] T085 [US3] Create src/cdc_pipeline/connectors/dlq_publisher.py with DLQPublisher (Kafka producer for cassandra.cdc.dlq topic, publish ErrorRecord)
- [ ] T086 [US3] Update src/cdc_pipeline/workers/replication_worker.py to integrate retry logic and circuit breaker (wrap process_event calls)
- [ ] T087 [US3] Create src/cdc_pipeline/workers/dlq_processor.py with DLQProcessor worker (consume DLQ topic, categorize errors, re-enqueue transient, export validation errors to CSV)
- [ ] T088 [US3] Add DLQ processor to docker-compose.yml as separate service
- [ ] T089 [US3] Update monitoring/prometheus/alerts.yml to add circuit breaker alerts (state=open → critical alert)

**Run tests - Should PASS now**: `pytest tests/unit/test_retry_logic.py tests/unit/test_circuit_breaker.py tests/integration/test_postgres_failure.py tests/integration/test_dlq_routing.py -v`

**Checkpoint**: Pipeline now automatically recovers from transient failures, failed records routed to DLQ for manual review

---

## Phase 6: User Story 4 - Schema Evolution Handling (Priority: P4)

**Goal**: Detect schema changes in Cassandra tables and handle gracefully without breaking replication

**Independent Test**: Add new nullable column to Cassandra table while pipeline running, insert records with new column, verify pipeline continues processing without stopping

### Tests for User Story 4 (TDD - Write FIRST) ⚠️

- [ ] T090 [P] [US4] Create tests/unit/test_schema_registry.py with unit tests for schema change detection (compare old vs new schema, identify added columns, dropped columns, type changes)
- [ ] T091 [US4] Create tests/integration/test_additive_schema_change.py with integration test (start pipeline, add nullable column to Cassandra table, insert record with new column, verify PostgreSQL receives data and logs schema change)
- [ ] T092 [US4] Create tests/integration/test_breaking_schema_change.py with integration test (change column type in Cassandra, verify pipeline routes records to validation queue and logs ERROR)

**Run tests - Should FAIL (schema evolution not implemented yet)**

### Implementation for User Story 4

- [ ] T093 [P] [US4] Create src/cdc_pipeline/services/schema_registry.py with SchemaRegistryService (methods: get_schema, detect_schema_change, compute_schema_diff, is_additive, apply_schema_migration)
- [ ] T094 [US4] Update src/cdc_pipeline/repositories/schema_repo.py to add schema versioning (store version number, invalidate on change)
- [ ] T095 [US4] Update src/cdc_pipeline/services/event_processor.py to check schema version (compare event.schema_version with cached schema, refresh if different)
- [ ] T096 [US4] Update src/cdc_pipeline/services/transformer.py to handle unknown columns (ignore if not in target schema, log INFO about new column)
- [ ] T097 [US4] Create config/schema-evolution.yml with configuration (strategy: hybrid, auto_apply_additive: true, breaking_change_behavior: log_and_skip)
- [ ] T098 [US4] Update src/cdc_pipeline/observability/logging.py to add schema change log processor (emit structured logs with schema diff details)
- [ ] T099 [US4] Create src/cdc_pipeline/connectors/kafka_schema_registry.py with Kafka Schema Registry client integration (register Avro schemas, enforce compatibility)
- [ ] T100 [US4] Update monitoring/prometheus/metrics.py to add schema_changes_detected_total Counter metric

**Run tests - Should PASS now**: `pytest tests/unit/test_schema_registry.py tests/integration/test_additive_schema_change.py tests/integration/test_breaking_schema_change.py -v`

**Checkpoint**: Pipeline detects schema changes, handles additive changes automatically, logs breaking changes for manual review

---

## Phase 7: User Story 5 - Dirty Data Handling (Priority: P5)

**Goal**: Validate incoming data against schemas, isolate invalid records in error queues without stopping pipeline

**Independent Test**: Insert records with missing required fields, incorrect data types into Cassandra, verify pipeline isolates them in validation error queue while continuing to process valid records

### Tests for User Story 5 (TDD - Write FIRST) ⚠️

- [ ] T101 [P] [US5] Create tests/unit/test_validator_dirty_data.py with unit tests for validation errors (missing required field, type mismatch, constraint violation, oversized value)
- [ ] T102 [US5] Create tests/integration/test_validation_error_routing.py with integration test (insert Cassandra record with invalid data, verify routed to validation error Kafka topic, valid records continue processing)
- [ ] T103 [US5] Create tests/integration/test_validation_threshold_alert.py with integration test (generate >5% error rate, verify pipeline emits alert while continuing)

**Run tests - Should FAIL (validation error handling not implemented yet)**

### Implementation for User Story 5

- [ ] T104 [P] [US5] Create src/cdc_pipeline/models/validation_errors.py with ValidationError and ValidationFailure Pydantic models (from data-model.md)
- [ ] T105 [P] [US5] Update src/cdc_pipeline/services/validator.py to add comprehensive validation (check required fields, validate types, check constraints, detect oversized values)
- [ ] T106 [US5] Create src/cdc_pipeline/connectors/validation_error_publisher.py with ValidationErrorPublisher (Kafka producer for cassandra.cdc.validation_errors topic)
- [ ] T107 [US5] Update src/cdc_pipeline/services/event_processor.py to route validation errors (catch ValidationError, publish to validation topic, increment error counter, continue processing)
- [ ] T108 [US5] Update src/cdc_pipeline/observability/metrics.py to add validation_error_total Counter (labels: table, error_type)
- [ ] T109 [US5] Update monitoring/prometheus/alerts.yml to add validation error rate alert (> 5% error rate → warning)
- [ ] T110 [US5] Create src/cdc_pipeline/api/admin.py endpoint to resubmit corrected records (POST /admin/validation-errors/{error_id}/resubmit)

**Run tests - Should PASS now**: `pytest tests/unit/test_validator_dirty_data.py tests/integration/test_validation_error_routing.py tests/integration/test_validation_threshold_alert.py -v`

**Checkpoint**: Pipeline validates all data, isolates bad data without blocking good data, provides API to correct and resubmit

---

## Phase 8: User Story 6 - Stale Event Handling (Priority: P6)

**Goal**: Detect and handle stale events (late-arriving changes) to prevent out-of-order updates from corrupting recent data

**Independent Test**: Insert Cassandra record, update it, then simulate delayed event with old timestamp arriving after new update processed, verify pipeline detects staleness and logs rejection

### Tests for User Story 6 (TDD - Write FIRST) ⚠️

- [ ] T111 [P] [US6] Create tests/unit/test_staleness_detection.py with unit tests for staleness logic (compare event timestamp with current PostgreSQL record timestamp, apply threshold)
- [ ] T112 [US6] Create tests/integration/test_stale_event_rejection.py with integration test (insert record, update, publish delayed old event, verify rejected and logged to staleness audit topic)
- [ ] T113 [US6] Create tests/integration/test_backfill_mode.py with integration test (enable backfill mode, publish old events, verify staleness detection disabled)

**Run tests - Should FAIL (staleness detection not implemented yet)**

### Implementation for User Story 6

- [ ] T114 [P] [US6] Create src/cdc_pipeline/models/staleness_audit.py with StalenessAuditEntry Pydantic model (from data-model.md)
- [ ] T115 [P] [US6] Create src/cdc_pipeline/services/staleness_detector.py with StalenessDetector (methods: is_stale, get_current_record_timestamp, compare_timestamps, check_threshold)
- [ ] T116 [US6] Create src/cdc_pipeline/connectors/staleness_audit_publisher.py with StalenessAuditPublisher (Kafka producer for cassandra.cdc.staleness_audit topic)
- [ ] T117 [US6] Update src/cdc_pipeline/connectors/postgres_writer.py to add read_current_record method (SELECT timestamp from table WHERE primary_key = ?)
- [ ] T118 [US6] Update src/cdc_pipeline/services/event_processor.py to add staleness check (before write, check if event is stale, if yes: log to audit topic and skip write)
- [ ] T119 [US6] Create config/staleness-detection.yml with configuration (threshold_seconds: 604800 (7 days), backfill_mode: false)
- [ ] T120 [US6] Update monitoring/prometheus/metrics.py to add stale_events_rejected_total Counter metric

**Run tests - Should PASS now**: `pytest tests/unit/test_staleness_detection.py tests/integration/test_stale_event_rejection.py tests/integration/test_backfill_mode.py -v`

**Checkpoint**: Pipeline detects late-arriving events, prevents out-of-order corruption, provides audit trail for rejected stale events

---

## Phase 9: User Story 7 - Production Observability (Priority: P7)

**Goal**: Comprehensive observability with metrics, logs, traces to diagnose issues within 5 minutes

**Independent Test**: Run pipeline under load, access Grafana dashboards showing real-time metrics, query structured logs with filters, view distributed traces end-to-end

### Tests for User Story 7 (TDD - Write FIRST) ⚠️

- [ ] T121 [P] [US7] Create tests/unit/test_logging_processors.py with unit tests for structlog processors (PII masking, correlation ID injection, context enrichment)
- [ ] T122 [P] [US7] Create tests/unit/test_metrics_collection.py with unit tests for Prometheus metrics (counter increment, histogram observe, gauge set)
- [ ] T123 [US7] Create tests/integration/test_distributed_tracing.py with integration test (process event, verify trace spans created: kafka.consume → validation → transformation → postgres.write → checkpoint.commit)
- [ ] T124 [US7] Create tests/integration/test_alerting.py with integration test (trigger alert condition: lag >2min, verify Prometheus alert fires)

**Run tests - Should FAIL (observability not fully integrated yet)**

### Implementation for User Story 7

- [ ] T125 [P] [US7] Update src/cdc_pipeline/observability/logging.py to add PII masking processor (regex patterns for email, SSN, credit card)
- [ ] T126 [P] [US7] Update src/cdc_pipeline/observability/logging.py to add correlation ID processor (extract from event.trace_id, inject into all logs)
- [ ] T127 [P] [US7] Update src/cdc_pipeline/observability/metrics.py to add all metrics from data-model.md (events_processed_total, replication_latency_seconds, replication_lag_seconds, error_total, dlq_size, checkpoint_age_seconds, circuit_breaker_state)
- [ ] T128 [US7] Update src/cdc_pipeline/observability/tracing.py to add instrumentation (wrap kafka consume, postgres write, redis operations with trace spans)
- [ ] T129 [US7] Update src/cdc_pipeline/services/event_processor.py to emit metrics (increment events_processed, observe latency, set lag gauge)
- [ ] T130 [US7] Update src/cdc_pipeline/workers/replication_worker.py to start Prometheus metrics HTTP server (port 8000, /metrics endpoint)
- [ ] T131 [US7] Update monitoring/grafana/dashboards/pipeline_overview.json to include all panels (throughput by table, latency heatmap P50/P95/P99, error rate, replication lag, DLQ size, worker health)
- [ ] T132 [US7] Update monitoring/prometheus/alerts.yml to include all critical alerts (lag >2min, error rate >1%, DLQ size >10000, circuit breaker open, worker down)
- [ ] T133 [US7] Create docs/runbooks/troubleshooting.md with diagnostic procedures (high lag: check worker CPU/memory, check PostgreSQL slow queries; errors: check logs for stacktrace, check DLQ for patterns)
- [ ] T134 [US7] Create docs/runbooks/scaling.md with procedures (horizontal scaling: add workers, rebalance; vertical scaling: increase batch size, connection pools)

**Run tests - Should PASS now**: `pytest tests/unit/test_logging_processors.py tests/unit/test_metrics_collection.py tests/integration/test_distributed_tracing.py tests/integration/test_alerting.py -v`

**Checkpoint**: Full observability stack operational, SREs can diagnose issues within 5 minutes using logs/metrics/traces

---

## Phase 10: User Story 8 - High Availability with Metadata Cache (Priority: P8)

**Goal**: Distributed cache for metadata enables multiple workers to coordinate and achieve HA without single points of failure

**Independent Test**: Run 3 pipeline workers connected to shared Redis cache, stop 1 worker, verify remaining 2 workers rebalance work and continue processing without interruption

### Tests for User Story 8 (TDD - Write FIRST) ⚠️

- [ ] T135 [P] [US8] Create tests/unit/test_worker_coordination.py with unit tests for distributed locking (acquire lock, release lock, detect stale locks)
- [ ] T136 [P] [US8] Create tests/unit/test_checkpoint_persistence.py with unit tests for Redis checkpoint operations (save, read, list, Redis persistence scenarios)
- [ ] T137 [US8] Create tests/integration/test_worker_failover.py with integration test (start 3 workers, kill 1, verify others detect failure within 30s, rebalance partitions, continue processing)
- [ ] T138 [US8] Create tests/integration/test_configuration_propagation.py with integration test (update config in Redis, verify all workers detect change within 60s and apply new settings)

**Run tests - Should FAIL (worker coordination not implemented yet)**

### Implementation for User Story 8

- [ ] T139 [P] [US8] Create src/cdc_pipeline/models/workers.py with PipelineWorker Pydantic model (from data-model.md)
- [ ] T140 [P] [US8] Create src/cdc_pipeline/services/coordinator.py with WorkerCoordinator (methods: register_worker, send_heartbeat, acquire_partition_lock, release_lock, detect_dead_workers, rebalance)
- [ ] T141 [P] [US8] Update src/cdc_pipeline/repositories/checkpoint_repo.py to add Redis Sentinel support (configure sentinel hosts, automatic failover)
- [ ] T142 [US8] Update src/cdc_pipeline/workers/replication_worker.py to integrate WorkerCoordinator (register on start, heartbeat every 10s, acquire partition locks, graceful shutdown releases locks)
- [ ] T143 [US8] Update src/cdc_pipeline/config/settings.py to add worker coordination config (worker_id generation: hostname-PID, heartbeat_interval_seconds: 10, worker_ttl_seconds: 30)
- [ ] T144 [US8] Update docker-compose.yml to add Redis Sentinel configuration (3 Sentinel nodes for HA)
- [ ] T145 [US8] Update src/cdc_pipeline/api/admin.py to add worker management endpoints (GET /workers, GET /workers/{worker_id}, POST /admin/workers/rebalance)
- [ ] T146 [US8] Update monitoring/prometheus/metrics.py to add worker metrics (active_workers Gauge, worker_heartbeat_age_seconds Gauge)
- [ ] T147 [US8] Update monitoring/grafana/dashboards/worker_metrics.json to show per-worker health (heartbeat freshness, assigned partitions, processing rate)

**Run tests - Should PASS now**: `pytest tests/unit/test_worker_coordination.py tests/unit/test_checkpoint_persistence.py tests/integration/test_worker_failover.py tests/integration/test_configuration_propagation.py -v`

**Checkpoint**: Multiple workers coordinate via Redis, automatic failover on worker failure, zero downtime during worker restarts

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T148 [P] Create docs/architecture.md with system architecture diagrams (component diagram, sequence diagram for event flow, deployment diagram)
- [ ] T149 [P] Create docs/runbooks/disaster_recovery.md with DR procedures (Redis backup/restore, Kafka topic backup, PostgreSQL snapshot restore, checkpoint recovery)
- [ ] T150 [P] Create docs/adr/001-debezium-vs-custom-cdc.md (Architecture Decision Record from research.md decision)
- [ ] T151 [P] Create docs/adr/002-kafka-vs-pulsar.md (Architecture Decision Record from research.md decision)
- [ ] T152 [P] Create docs/adr/003-redis-vs-etcd.md (Architecture Decision Record from research.md decision)
- [ ] T153 [P] Update README.md with badges (build status, coverage, license), quickstart summary, architecture link, contribution guidelines
- [ ] T154 Code cleanup: Run ruff linter on entire codebase, fix all issues (unused imports, undefined names, etc.)
- [ ] T155 Code cleanup: Run mypy type checker on entire codebase, add missing type hints, fix type errors
- [ ] T156 Code cleanup: Run black formatter on entire codebase, ensure consistent style
- [ ] T157 Performance optimization: Profile event_processor.py with py-spy, identify hot paths, optimize (target: >1000 events/sec)
- [ ] T158 Performance optimization: Tune PostgreSQL batch size based on load testing results (adjust batch_size config)
- [ ] T159 [P] Create tests/performance/locustfile.py with Locust load test scenarios (steady load 500 events/sec for 10 minutes, spike to 2000 events/sec)
- [ ] T160 Run full integration test suite and ensure 80% coverage (pytest tests/ --cov=src/cdc_pipeline --cov-report=html)
- [ ] T161 Security hardening: Run Trivy on Docker images, fix high/critical vulnerabilities (update base images, pin versions)
- [ ] T162 Security hardening: Run Safety on Python dependencies, fix known vulnerabilities (upgrade libraries)
- [ ] T163 Security hardening: Run Bandit SAST scanner, fix security issues (SQL injection, hardcoded secrets)
- [ ] T164 Run quickstart.md validation: Spin up local stack, follow every step, verify all commands work, update doc with corrections
- [ ] T165 Update .github/workflows/ci.yml to run full test suite + coverage + security scans on every PR

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phases 3-10)**: All depend on Foundational phase completion
  - User stories CAN proceed in parallel if you have multiple developers
  - Or sequentially in priority order (P1 → P2 → P3 → ... → P8) for single developer
- **Polish (Phase 11)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories ✅ MVP
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Independent, but benefits from US1 being complete for testing
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - Independent, extends US1 with retry logic
- **User Story 4 (P4)**: Can start after Foundational (Phase 2) - Independent, extends US1 with schema handling
- **User Story 5 (P5)**: Can start after Foundational (Phase 2) - Independent, extends US1 with validation
- **User Story 6 (P6)**: Can start after Foundational (Phase 2) - Independent, extends US1 with staleness detection
- **User Story 7 (P7)**: Can start after Foundational (Phase 2) - Independent, adds observability to existing components
- **User Story 8 (P8)**: Can start after Foundational (Phase 2) - Independent, extends US1 with HA coordination

**Key Insight**: After Foundational phase, ALL user stories are independently implementable in parallel!

### Within Each User Story

- Tests (TDD) MUST be written and FAIL before implementation
- Models before services (Pydantic models define contracts)
- Services before workers (business logic before orchestration)
- Core implementation before integration (e.g., event processor before worker)
- Story complete before moving to next priority

### Parallel Opportunities

- **Setup phase**: Almost all tasks are parallelizable (T003-T022 marked [P])
- **Foundational phase**: Many tasks parallelizable (T027-T030 models, T031-T038 observability/resilience, T039-T042 repositories)
- **Within each user story**: Tests can run in parallel, models can run in parallel, independent services can run in parallel
- **Across user stories**: After Foundational, different team members can work on different stories simultaneously

---

## Parallel Example: User Story 1 (MVP)

**Test Phase** (can run in parallel):
```bash
# Launch all tests together (they'll fail initially - that's TDD!)
Task: T052 - Unit test event processor
Task: T053 - Unit test transformer
Task: T054 - Contract test event schemas

# Then run integration tests (these depend on each other less)
Task: T055 - Integration test Cassandra→Kafka
Task: T056 - Integration test Kafka→PostgreSQL
Task: T057 - End-to-end test
```

**Model Phase** (can run in parallel):
```bash
Task: T059 - transformer.py
Task: T060 - validator.py
# These are independent modules in different files
```

**Services Phase** (some parallelizable):
```bash
Task: T061 - event_processor.py  # Depends on T059, T060 being done
Task: T063 - replication_worker.py  # Depends on T061
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (~2-3 hours)
2. Complete Phase 2: Foundational (~8-10 hours, CRITICAL blocking phase)
3. Complete Phase 3: User Story 1 - Basic Replication (~8-12 hours)
4. **STOP and VALIDATE**:
   - Run all tests: `pytest tests/ -v`
   - Run local stack: Follow quickstart.md
   - Verify: Insert Cassandra data → appears in PostgreSQL within 30s
   - Check coverage: `pytest --cov=src/cdc_pipeline --cov-report=html` (should be >80%)
5. **MVP COMPLETE**: You now have working CDC pipeline! Deploy/demo if ready.

**Estimated MVP Time**: ~20-25 hours for experienced developer (Phase 1 + Phase 2 + Phase 3)

### Incremental Delivery (After MVP)

Each subsequent user story adds independent value:

1. **US2 - Local Dev** (~4-6 hours): Docker Compose optimization, resource limits, test data generation → Enables faster developer iteration
2. **US3 - Retry & Recovery** (~6-8 hours): Exponential backoff, circuit breaker, DLQ → Production-grade reliability
3. **US4 - Schema Evolution** (~6-8 hours): Detect schema changes, handle additive changes → Supports evolving applications
4. **US5 - Dirty Data** (~4-6 hours): Validation, error queues, correction API → Handles real-world messy data
5. **US6 - Staleness** (~4-6 hours): Detect late events, audit logging → Prevents data corruption from out-of-order events
6. **US7 - Observability** (~6-8 hours): Full metrics/logs/traces → Enables production troubleshooting
7. **US8 - High Availability** (~8-10 hours): Worker coordination, failover → Enables horizontal scaling and zero downtime

**Total Estimated Time** (all 8 user stories + polish): ~65-85 hours

### Parallel Team Strategy

With 3 developers after Foundational phase:

1. **Dev A**: User Stories 1, 4, 7 (core replication + schema + observability)
2. **Dev B**: User Stories 2, 5, 8 (local dev + validation + HA)
3. **Dev C**: User Stories 3, 6 (retry + staleness)

**Timeline**: Can complete all 8 stories in ~3-4 weeks with parallel development

---

## Notes

- **[P] tasks** = different files, no dependencies, run in parallel
- **[Story] label** maps task to specific user story for traceability
- Each user story is independently completable and testable
- **TDD is mandatory**: Verify tests FAIL before implementing (per constitution)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence

---

## Summary

- **Total Tasks**: 165 tasks
- **Setup Phase**: 22 tasks
- **Foundational Phase**: 29 tasks (BLOCKING)
- **User Story 1 (MVP)**: 14 tasks (6 tests + 8 implementation)
- **User Story 2**: 10 tasks (3 tests + 7 implementation)
- **User Story 3**: 13 tasks (4 tests + 9 implementation)
- **User Story 4**: 11 tasks (3 tests + 8 implementation)
- **User Story 5**: 10 tasks (3 tests + 7 implementation)
- **User Story 6**: 10 tasks (3 tests + 7 implementation)
- **User Story 7**: 14 tasks (4 tests + 10 implementation)
- **User Story 8**: 13 tasks (4 tests + 9 implementation)
- **Polish Phase**: 18 tasks

**Total Test Tasks**: 30 (unit + integration + contract + performance tests)
**Parallel Opportunities**: ~80 tasks marked [P] can run in parallel

**Format Validation**: ✅ ALL tasks follow checklist format (checkbox, Task ID, optional [P]/[Story] labels, file path)
