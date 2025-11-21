# Tasks: Cassandra to PostgreSQL CDC Pipeline

**Input**: Design documents from `/home/bob/WORK/cass-cdc-pg/specs/001-cass-cdc-pg/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/kafka-topics.md, contracts/rest-api.md, quickstart.md

**Tests**: According to the constitution, tests MUST be written BEFORE implementation (TDD is NON-NEGOTIABLE). All test tasks must be completed and verified FAILING before proceeding with implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

**Total Tasks**: 141 tasks (original 107 + reconciliation extension 26 + analysis remediation 8 new tasks)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4, US5, US6)
- Include exact file paths in descriptions

## Path Conventions

All paths relative to repository root:
- Source: `src/`
- Tests: `tests/`
- Docker: `docker/`
- Config: `config/`
- Scripts: `scripts/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create project directory structure (src/, tests/, docker/, config/, scripts/, helm/, docs/)
- [X] T002 Initialize Python project with Poetry (pyproject.toml with dependencies from plan.md)
- [X] T003 [P] Configure pre-commit hooks (.pre-commit-config.yaml with Ruff, Black, mypy, bandit)
- [X] T004 [P] Create .gitignore for Python, Docker, IDEs, secrets
- [X] T005 [P] Create Makefile with common commands (start, stop, test, lint, clean, health)
- [X] T006 [P] Create README.md with project overview, quick start, architecture diagram

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Infrastructure & Configuration

- [X] T007 Create Docker Compose file (docker/docker-compose.yml with 12 services: Cassandra, PostgreSQL, Kafka, Schema Registry, Kafka Connect, Vault, Prometheus, Grafana, Jaeger, Zookeeper, Init)
- [X] T008 Create .env.example with all required environment variables (Cassandra, PostgreSQL, Kafka, Vault, monitoring)
- [X] T009 [P] Create Cassandra Docker config (docker/cassandra/Dockerfile, cassandra.yaml with CDC enabled, init-schema.cql, enable-cdc.sh)
- [X] T010 [P] Create PostgreSQL Docker config (docker/postgres/Dockerfile, postgresql.conf, init-db.sql with control tables: _cdc_schema_metadata, _cdc_checkpoints, _cdc_dlq_records, _cdc_audit_log with 1-year retention policy per constitution requirement)
- [X] T011 [P] Create Kafka Docker config (docker/kafka/server.properties, connect-distributed.properties, create-topics.sh)
- [X] T012 [P] Create Vault Docker config (docker/vault/config.hcl, policies/cdc-policy.hcl, init-secrets.sh)
- [X] T013 [P] Create Prometheus config (docker/monitoring/prometheus.yml with scrape configs, prometheus-alerts.yml)
- [X] T014 [P] Create Grafana config (docker/monitoring/grafana/datasources.yml, dashboards/cdc-pipeline.json, dashboards/kafka.json, dashboards/databases.json)
- [X] T015 [P] Create Jaeger config (docker/monitoring/jaeger.yml)

### Core Python Foundation

- [X] T016 Create configuration module (src/config/settings.py using pydantic-settings with VaultSettings, CassandraSettings, PostgreSQLSettings, KafkaSettings)
- [X] T017 Create logging configuration (src/config/logging_config.py with structlog JSON renderer, correlation IDs, no sensitive data filter)
- [X] T018 [P] Create base repository ABC (src/repositories/base.py with AbstractRepository interface)
- [X] T019 [P] Create metrics module (src/monitoring/metrics.py with Prometheus client, RED method metrics: events_processed_total, processing_latency_seconds, errors_total, backlog_depth)
- [X] T020 [P] Create tracing module (src/monitoring/tracing.py with OpenTelemetry setup, Jaeger exporter, span instrumentation helpers)
- [X] T021 [P] Create health check service (src/monitoring/health_check.py with checks for Cassandra, PostgreSQL, Kafka, Schema Registry, Vault)

### Utility Libraries

- [X] T022 [P] Create retry utility (src/utils/retry.py with tenacity decorators, exponential backoff 1s→60s)
- [X] T023 [P] Create circuit breaker (src/utils/circuit_breaker.py with 5 failures→open, 60s half-open)
- [X] T024 [P] Create validators (src/utils/validators.py for event validation, schema validation, data integrity)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Basic Data Replication (Priority: P1) 🎯 MVP

**Goal**: Capture all data changes from Cassandra tables and replicate to PostgreSQL in near real-time

**Independent Test**: Insert/update/delete records in Cassandra, verify they appear in PostgreSQL within 5 seconds

### Tests for User Story 1 (TDD - MUST COMPLETE FIRST) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T025 [P] [US1] Contract test for Change Event Avro schema in tests/contract/test_change_event_schema.py (validate schema compatibility, field types, required fields)
- [X] T026 [P] [US1] Contract test for cdc-events Kafka topic in tests/contract/test_kafka_topics.py (validate topic config, partitioning, replication)
- [X] T027 [P] [US1] Integration test for Cassandra→Kafka flow in tests/integration/test_cassandra_to_kafka.py (insert in Cassandra, verify event in Kafka topic)
- [X] T028 [P] [US1] Integration test for Kafka→PostgreSQL flow in tests/integration/test_kafka_to_postgres.py (produce to Kafka, verify write in PostgreSQL)
- [X] T029 [US1] End-to-end replication test in tests/integration/test_end_to_end_replication.py (INSERT, UPDATE, DELETE in Cassandra, verify all operations in PostgreSQL within 5s)
- [X] T136 [P] [US1] Integration test for TTL preservation in tests/integration/test_ttl_preservation.py (insert Cassandra record with TTL=3600 seconds, verify PostgreSQL record has ttl_expiry_timestamp column, wait 1 hour, verify record auto-deleted)
- [X] T137 [P] [US1] Integration test for out-of-order event handling in tests/integration/test_out_of_order_events.py (produce newer event with timestamp_micros=1000, then older event with timestamp_micros=500, verify older event rejected and not written to PostgreSQL)

### Data Models for User Story 1

- [X] T030 [P] [US1] Create ChangeEvent model in src/models/change_event.py (event_id, source, operation, timestamp_micros, before, after, schema_version, ttl_seconds, is_tombstone with OperationType enum: CREATE, UPDATE, DELETE, TRUNCATE)
- [X] T031 [P] [US1] Create Checkpoint model in src/models/checkpoint.py (checkpoint_id, source_table, partition_key_hash, last_processed_event_id, last_processed_timestamp_micros, checkpoint_timestamp, kafka_offset, kafka_partition, status)
- [X] T032 [P] [US1] Create SchemaMetadata model in src/models/schema_metadata.py (schema_id, source_table, version, columns, primary_key, avro_schema, avro_schema_id, effective_from, effective_to, compatibility_mode, change_type)

### Repositories for User Story 1

- [X] T033 [US1] Implement CassandraRepository in src/repositories/cassandra_repository.py (connect, read_schema, query_table, health_check methods using cassandra-driver)
- [X] T034 [US1] Implement PostgreSQLRepository in src/repositories/postgresql_repository.py (connect, create_table, upsert, delete, query, health_check methods using psycopg2 with connection pooling)
- [X] T035 [US1] Implement VaultRepository in src/repositories/vault_repository.py (get_credentials, renew_lease, health_check methods using hvac client)

### Services for User Story 1

- [X] T036 [US1] Implement TypeMapper service in src/services/type_mapper.py (Cassandra→PostgreSQL type conversion: text→VARCHAR, int→INTEGER, bigint→BIGINT, uuid→UUID, timestamp→TIMESTAMPTZ, list→ARRAY, map→JSONB, UDT→JSONB, TTL preservation via PostgreSQL retention policies)
- [X] T037 [US1] Implement SchemaService in src/services/schema_service.py (register_schema, get_schema_by_version, detect_schema_changes, validate_compatibility methods)
- [X] T134 [US1] Implement TTL preservation in src/services/type_mapper.py (convert Cassandra TTL to PostgreSQL retention: create trigger to auto-delete rows after TTL expires, store ttl_expiry_timestamp column calculated as inserted_at + ttl_seconds)
- [X] T135 [US1] Implement out-of-order event handling in src/connectors/transforms/timestamp_conflict_resolver.py (custom Kafka Connect SMT: compare event timestamp_micros with existing record's updated_at, reject older events with last-write-wins strategy, use event_id as tiebreaker if timestamps equal)

### Kafka Connect Connectors for User Story 1

- [X] T038 [US1] Create Debezium Cassandra source connector config (docker/connectors/cassandra-source.json with cassandra.hosts, cassandra.table.include.list, kafka.topic.prefix, offset.storage.topic, max.batch.size=2048, max.queue.size=8192, tombstones.on.delete=true)
- [X] T039 [US1] Create JDBC PostgreSQL sink connector config (docker/connectors/postgres-sink.json with connection.url, topics.regex, auto.create=true, auto.evolve=true, insert.mode=upsert, pk.mode=record_key, delete.enabled=true, batch.size=1000, errors.tolerance=all, errors.deadletterqueue.topic.name=dlq-events)
- [X] T040 [US1] Create connector deployment script (docker/connectors/deploy-connectors.sh to POST connector configs to Kafka Connect REST API on startup)

### Integration for User Story 1

- [X] T041 [US1] Configure Schema Registry with Change Event Avro schema (register schemas for cdc-events-users-key and cdc-events-users-value with BACKWARD compatibility)
- [X] T042 [US1] Create initial Cassandra test schema (docker/cassandra/init-schema.cql with warehouse keyspace, users and orders tables with CDC enabled)
- [X] T043 [US1] Create initial PostgreSQL test schema (docker/postgres/init-db.sql with public schema, cdc_users and cdc_orders tables, _cdc_schema_metadata, _cdc_checkpoints, _cdc_dlq_records control tables)
- [X] T044 [US1] Add monitoring for US1 metrics (cdc_events_processed_total counter by table/operation, cdc_processing_latency_seconds histogram by stage, cdc_backlog_depth gauge by topic)

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Local Development Environment (Priority: P2)

**Goal**: Enable developers to run entire CDC pipeline on laptop with single command

**Independent Test**: Run `docker-compose up`, insert test data, verify replication works locally under 4GB RAM

### Tests for User Story 2 (TDD - MUST COMPLETE FIRST) ⚠️

- [X] T045 [P] [US2] Integration test for Docker Compose health checks in tests/integration/test_docker_health.py (verify all 12 services start and become healthy within 90 seconds)
- [X] T046 [P] [US2] Integration test for resource constraints in tests/integration/test_resource_limits.py (verify total Docker memory usage < 4GB)
- [X] T047 [US2] Integration test for checkpoint resume after restart in tests/integration/test_checkpoint_resume.py (insert data, stop services, restart, verify no data loss or duplication)

### Implementation for User Story 2

- [X] T048 [P] [US2] Optimize Docker Compose resource limits (set memory_limit for Cassandra=1GB, PostgreSQL=512MB, Kafka=1GB, other services=256MB each)
- [X] T049 [P] [US2] Create health check scripts (scripts/health-check-cassandra.sh, scripts/health-check-postgres.sh, scripts/health-check-kafka.sh, scripts/health-check-vault.sh)
- [X] T050 [US2] Create test data generator (scripts/generate_test_data.py using faker to generate realistic users, orders with configurable count, minimum 10,000 records per table to validate SC-001 correctness requirement)
- [X] T051 [US2] Create setup script (scripts/setup_local_env.sh for one-command setup: check prerequisites, copy .env, start services, wait for health, deploy connectors, generate test data)
- [X] T052 [US2] Update quickstart.md with verified local setup instructions (prerequisites, quick start, verification steps, troubleshooting)
- [X] T053 [US2] Add hot-reload for code changes (volume mounts in docker-compose.yml for src/ directory to enable development without rebuild)

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Schema Evolution Handling (Priority: P3)

**Goal**: Automatically detect and handle Cassandra schema changes without manual intervention

**Independent Test**: Add column to Cassandra table, verify PostgreSQL schema updates automatically

### Tests for User Story 3 (TDD - MUST COMPLETE FIRST) ⚠️

- [X] T054 [P] [US3] Integration test for adding new column in tests/integration/test_schema_add_column.py (ALTER TABLE ADD COLUMN in Cassandra, verify column appears in PostgreSQL within 10s)
- [X] T055 [P] [US3] Integration test for dropping column in tests/integration/test_schema_drop_column.py (ALTER TABLE DROP COLUMN in Cassandra, verify PostgreSQL handles gracefully)
- [X] T056 [P] [US3] Integration test for compatible type change in tests/integration/test_schema_type_change.py (change int→bigint in Cassandra, verify PostgreSQL updates type)
- [X] T057 [US3] Integration test for incompatible schema change→DLQ in tests/integration/test_schema_incompatible.py (breaking type change, verify events routed to DLQ with SCHEMA_MISMATCH error)

### Implementation for User Story 3

- [X] T058 [US3] Enhance SchemaService with evolution detection (add detect_schema_changes method to compare current schema with registered schema, identify added/dropped/changed columns)
- [X] T059 [US3] Implement schema compatibility checker (add check_compatibility method supporting BACKWARD, FORWARD, FULL modes per schema-changes.md)
- [X] T060 [US3] Create Schema Registry integration (register_schema method to POST new schema versions to Schema Registry, validate compatibility before registration)
- [X] T061 [US3] Configure Kafka Connect schema evolution mode (set CONNECT_KEY_CONVERTER_SCHEMAS_ENABLE=true, CONNECT_VALUE_CONVERTER_SCHEMAS_ENABLE=true, compatibility=BACKWARD in Schema Registry)
- [X] T062 [US3] Add schema-changes Kafka topic for audit log (create topic with 1 partition, 365-day retention, publish SchemaChange events on schema evolution)
- [X] T063 [US3] Add monitoring for schema evolution events (cdc_schema_changes_total counter by change_type, cdc_schema_versions gauge by table)

**Checkpoint**: All user stories 1-3 should now be independently functional

---

## Phase 6: User Story 4 - Production Observability (Priority: P4)

**Goal**: Comprehensive metrics, logs, and traces for production monitoring

**Independent Test**: Query /metrics endpoint, review structured JSON logs, view distributed traces in Jaeger

### Tests for User Story 4 (TDD - MUST COMPLETE FIRST) ⚠️

- [X] T064 [P] [US4] Contract test for /health endpoint in tests/contract/test_health_api.py (verify returns 200 with all components, 503 if any component unhealthy)
- [X] T065 [P] [US4] Contract test for /metrics endpoint in tests/contract/test_metrics_api.py (verify Prometheus format, required metrics present: cdc_events_processed_total, cdc_processing_latency_seconds, cdc_backlog_depth, cdc_errors_total)
- [X] T066 [US4] Integration test for structured logging with correlation IDs in tests/integration/test_logging.py (process event, verify JSON logs contain trace_id, event_id, table, operation, no sensitive data)
- [X] T067 [US4] Integration test for distributed tracing spans in tests/integration/test_tracing.py (insert in Cassandra, verify trace in Jaeger with spans for capture, transform, load stages)

### Implementation for User Story 4

- [X] T068 [P] [US4] Create FastAPI app skeleton (src/api/main.py with app initialization, CORS middleware, exception handlers)
- [X] T069 [P] [US4] Implement /health endpoint (src/api/routes/health.py checking Cassandra, PostgreSQL, Kafka, Schema Registry, Vault per rest-api.md contract)
- [X] T070 [P] [US4] Implement /metrics endpoint (src/api/routes/metrics.py exposing Prometheus metrics from src/monitoring/metrics.py)
- [X] T071 [US4] Add Prometheus metrics instrumentation (RED method: cdc_events_processed_total rate by table/operation, cdc_errors_total by error_type, cdc_processing_latency_seconds duration histogram by stage, cdc_backlog_depth saturation gauge)
- [X] T072 [US4] Configure structlog JSON renderer (update src/config/logging_config.py with JSONRenderer, add correlation_id processor, filter credentials using bandit patterns)
- [X] T073 [US4] Configure OpenTelemetry tracing (update src/monitoring/tracing.py with JaegerExporter, auto-instrumentation for Kafka/Cassandra/PostgreSQL clients, 10% sampling for success, 100% for errors)
- [X] T074 [US4] Create Grafana dashboards (docker/monitoring/grafana/dashboards/cdc-pipeline.json with panels for throughput, latency P50/P95/P99, error rate, consumer lag, connection pools)
- [X] T075 [US4] Create Prometheus alerting rules (docker/monitoring/prometheus-alerts.yml for HighConsumerLag >10K for 5m, UnderReplicatedPartitions >0, DLQEventsAccumulating rate >10/sec, HighLatency P95 >2s)

**Checkpoint**: User stories 1-4 complete and observable

---

## Phase 7: User Story 5 - Error Handling & Recovery (Priority: P5)

**Goal**: Handle transient failures with retries, route failed records to DLQ, recover from crashes

**Independent Test**: Simulate PostgreSQL outage, verify retry with exponential backoff, confirm failed records in DLQ

### Tests for User Story 5 (TDD - MUST COMPLETE FIRST) ⚠️

- [X] T076 [P] [US5] Integration test for retry with exponential backoff in tests/integration/test_retry_logic.py (stop PostgreSQL, insert in Cassandra, verify retries at 1s, 2s, 4s, 8s intervals in logs)
- [X] T077 [P] [US5] Integration test for DLQ routing after retries exhausted in tests/integration/test_dlq_routing.py (stop PostgreSQL, insert invalid data, wait 5 minutes, verify event in dlq-events topic with retry_count=10)
- [X] T078 [P] [US5] Integration test for crash recovery from checkpoint in tests/integration/test_crash_recovery.py (insert 1000 records, kill Kafka Connect after 500, restart, verify remaining 500 processed without duplicates)
- [X] T079 [US5] Integration test for DLQ replay in tests/integration/test_dlq_replay.py (create DLQ record, fix issue, POST /dlq/replay, verify event reprocessed successfully)

### Data Models for User Story 5

- [X] T080 [P] [US5] Create DLQRecord model in src/models/dlq_record.py (dlq_id, original_event, error_type, error_message, error_stack_trace, retry_count, first_failed_at, last_retry_at, dlq_timestamp, source_component, resolution_status with ErrorType enum: SCHEMA_MISMATCH, TYPE_CONVERSION_ERROR, CONSTRAINT_VIOLATION, NETWORK_TIMEOUT, UNKNOWN)

### Implementation for User Story 5

- [X] T081 [US5] Implement DLQService in src/services/dlq_service.py (query_dlq_records, replay_events methods consuming from dlq-events topic, updating _cdc_dlq_records table)
- [X] T082 [US5] Configure Kafka Connect error handling (set errors.tolerance=all, errors.deadletterqueue.topic.name=dlq-events, errors.deadletterqueue.context.headers.enable=true in postgres-sink.json)
- [X] T083 [US5] Implement circuit breaker for PostgreSQL connections (use src/utils/circuit_breaker.py in PostgreSQLRepository, open after 5 consecutive failures, half-open after 60s)
- [X] T084 [US5] Configure retry policies (use tenacity in PostgreSQLRepository.upsert with exponential backoff: wait_exponential(multiplier=1, min=1, max=60), stop_after_delay(300))
- [X] T085 [US5] Create DLQ replay endpoint (src/api/routes/dlq.py with POST /dlq/replay accepting dlq_ids, resolution_notes, retry_strategy per rest-api.md)
- [X] T086 [US5] Create DLQ query endpoint (src/api/routes/dlq.py with GET /dlq/records supporting filters: error_type, resolution_status, table, start_date, end_date, pagination)
- [X] T087 [US5] Add DLQ monitoring metrics (cdc_dlq_events_total counter by table/error_type, cdc_dlq_replay_success_total counter, cdc_dlq_replay_failed_total counter)

**Checkpoint**: User stories 1-5 complete with robust error handling

---

## Phase 8: User Story 6 - Credentials Management (Priority: P6)

**Goal**: All credentials stored in Vault, rotated automatically, no secrets in code/config

**Independent Test**: Configure Vault, verify pipeline retrieves credentials from Vault, rotate credentials without restart

### Tests for User Story 6 (TDD - MUST COMPLETE FIRST) ⚠️

- [X] T088 [P] [US6] Integration test for Vault credential retrieval in tests/integration/test_vault_credentials.py (start pipeline, verify Cassandra/PostgreSQL connections use credentials from Vault paths secret/data/cdc/cassandra and database/creds/postgresql-writer)
- [X] T089 [P] [US6] Integration test for credential rotation in tests/integration/test_credential_rotation.py (change Vault credential, wait 5 minutes, verify pipeline refreshes and continues working)
- [X] T090 [US6] Integration test for no credentials in logs in tests/integration/test_no_secrets_in_logs.py (run pipeline, grep logs for password/secret/token patterns, verify 0 matches)

### Implementation for User Story 6

- [X] T091 [US6] Enhance VaultRepository with credential rotation (add refresh_credentials method checking lease TTL, auto-renewing before 24h expiry, caching credentials with 23h TTL)
- [X] T092 [US6] Configure Vault policies (docker/vault/policies/cdc-policy.hcl allowing read on secret/data/cdc/*, database/creds/postgresql-writer with AppRole authentication)
- [X] T093 [US6] Create Vault initialization script (docker/vault/init-secrets.sh to populate secret/cdc/cassandra with username/password, configure database/postgresql with dynamic credentials 24h TTL)
- [X] T094 [US6] Update settings.py to read from Vault (modify src/config/settings.py to use VaultRepository.get_credentials instead of environment variables in production mode)
- [X] T095 [US6] Configure Kafka Connect to use Vault credentials (set connection.user=${file:/secrets/postgres:username}, connection.password=${file:/secrets/postgres:password} in postgres-sink.json)
- [X] T096 [US6] Add TLS 1.3 configuration for all connections (Cassandra: ssl_context with TLSv1.3, PostgreSQL: sslmode=require sslprotocol=TLSv1.3, Kafka: security.protocol=SSL ssl.enabled.protocols=TLSv1.3)
- [X] T097 [US6] Verify no credentials in logs (update bandit pre-commit hook with patterns for password, secret, token, api_key, enforce in CI/CD)

**Checkpoint**: All user stories 1-6 complete and production-ready

---

## Phase 9: User Story 7 - Data Reconciliation (Priority: P7) 🆕 EXTENSION

**Goal**: Ensure data consistency between Cassandra and PostgreSQL through hourly automated and manual on-demand reconciliation with Prometheus/AlertManager alerting

**Independent Test**: Run manual reconciliation, verify drift detection, confirm alerts fired for mismatches

### Tests for User Story 7 (TDD - MUST COMPLETE FIRST) ⚠️

- [ ] T108 [P] [US7] Integration test for row count reconciliation in tests/integration/test_reconciliation_row_count.py (insert 1000 in Cassandra, delete 50 from PostgreSQL, run reconciliation, verify drift_percentage=5%)
- [ ] T109 [P] [US7] Integration test for checksum validation in tests/integration/test_reconciliation_checksum.py (modify 10 records in PostgreSQL, run checksum reconciliation, verify 10 DATA_MISMATCH records)
- [ ] T110 [P] [US7] Integration test for hourly scheduled reconciliation in tests/integration/test_reconciliation_scheduled.py (wait for scheduled job, verify ReconciliationJob created with job_type=HOURLY_SCHEDULED)
- [ ] T111 [P] [US7] Integration test for Prometheus metrics in tests/integration/test_reconciliation_metrics.py (run reconciliation, query /metrics, verify cdc_reconciliation_drift_percentage gauge present)
- [ ] T112 [US7] Integration test for AlertManager alert firing in tests/integration/test_reconciliation_alerts.py (create 10% drift, wait 5 minutes, verify ReconciliationDriftCritical alert in AlertManager API)

### Data Models for User Story 7

- [ ] T113 [P] [US7] Create ReconciliationJob model in src/models/reconciliation_job.py (job_id, table_name, job_type enum: HOURLY_SCHEDULED/MANUAL_ONDEMAND, validation_strategy enum: ROW_COUNT/CHECKSUM/TIMESTAMP_RANGE/SAMPLE, started_at, completed_at, status enum: RUNNING/COMPLETED/FAILED, cassandra_row_count, postgres_row_count, mismatch_count, drift_percentage, validation_errors JSONB, alert_fired bool)
- [ ] T114 [P] [US7] Create ReconciliationMismatch model in src/models/reconciliation_mismatch.py (mismatch_id, job_id FK, table_name, primary_key_value, mismatch_type enum: MISSING_IN_POSTGRES/MISSING_IN_CASSANDRA/DATA_MISMATCH, cassandra_checksum, postgres_checksum, cassandra_data JSONB, postgres_data JSONB, detected_at, resolution_status enum: PENDING/AUTO_RESOLVED/MANUAL_RESOLVED/IGNORED, resolution_notes, resolved_at)

### Repositories for User Story 7

- [ ] T115 [US7] Implement ReconciliationRepository in src/repositories/reconciliation_repository.py (create_job, update_job, get_job, list_jobs with filters, create_mismatch, list_mismatches with filters, resolve_mismatch methods accessing _cdc_reconciliation_jobs and _cdc_reconciliation_mismatches tables)

### Services for User Story 7

- [ ] T116 [US7] Implement ReconciliationEngine in src/services/reconciliation_engine.py (run_row_count_validation, run_checksum_validation, run_timestamp_range_validation, run_sample_validation methods comparing Cassandra vs PostgreSQL)
- [ ] T117 [US7] Implement AlertService in src/services/alert_service.py (send_alert_to_prometheus method using prometheus pushgateway, format_alert_message, determine_alert_severity based on drift thresholds)
- [ ] T118 [US7] Implement ReconciliationScheduler in src/services/reconciliation_scheduler.py (using APScheduler with hourly IntervalTrigger, PostgreSQLJobStore, schedule_reconciliation_for_all_tables method, manual_trigger_reconciliation method)

### API Endpoints for User Story 7

- [ ] T119 [P] [US7] Create reconciliation trigger endpoint in src/api/routes/reconciliation.py (POST /reconciliation/trigger accepting tables list and validation_strategy, returns job_ids)
- [ ] T120 [P] [US7] Create reconciliation jobs query endpoint in src/api/routes/reconciliation.py (GET /reconciliation/jobs with filters: table, status, from_date, to_date, pagination)
- [ ] T121 [P] [US7] Create reconciliation job detail endpoint in src/api/routes/reconciliation.py (GET /reconciliation/jobs/{job_id} returning ReconciliationJob with nested mismatches list)
- [ ] T122 [P] [US7] Create mismatches query endpoint in src/api/routes/reconciliation.py (GET /reconciliation/mismatches with filters: table, mismatch_type, resolution_status, pagination)
- [ ] T123 [P] [US7] Create mismatch resolution endpoint in src/api/routes/reconciliation.py (POST /reconciliation/mismatches/{mismatch_id}/resolve accepting resolution_status and resolution_notes)
- [ ] T138 [P] [US7] Create GDPR erasure endpoint in src/api/routes/gdpr.py (DELETE /records/{keyspace}/{table}/{primary_key} with cascading delete in Cassandra and PostgreSQL, audit to _cdc_audit_log with requester, timestamp, record_identifier, reason)
- [ ] T139 [P] [US7] Integration test for GDPR erasure in tests/integration/test_gdpr_erasure.py (create record, call DELETE endpoint, verify removed from both Cassandra and PostgreSQL, verify audit log entry created)

### Database Schema for User Story 7

- [ ] T124 [US7] Create reconciliation control tables in docker/postgres/init-db.sql (_cdc_reconciliation_jobs table with indexes on table_name+status and started_at, _cdc_reconciliation_mismatches table with indexes on job_id and table_name+resolution_status, _apscheduler_jobs table for APScheduler persistence)

### Monitoring for User Story 7

- [ ] T125 [US7] Add reconciliation metrics to src/monitoring/metrics.py (cdc_reconciliation_drift_percentage gauge by table, cdc_reconciliation_cassandra_rows gauge, cdc_reconciliation_postgres_rows gauge, cdc_reconciliation_mismatches_total counter by table+type, cdc_reconciliation_jobs_completed_total counter by table+status, cdc_reconciliation_duration_seconds histogram)
- [ ] T126 [US7] Add reconciliation alerting rules to docker/monitoring/prometheus-alerts.yml (ReconciliationDriftWarning for 1-5% drift, ReconciliationDriftCritical for >5% drift, ReconciliationJobFailed for >3 failures per hour)
- [ ] T127 [US7] Create reconciliation Grafana dashboard in docker/monitoring/grafana/dashboards/reconciliation.json (drift percentage by table timeseries, mismatch count by type, job success rate, reconciliation duration distribution)

### Integration for User Story 7

- [ ] T128 [US7] Configure Prometheus pushgateway in docker/docker-compose.yml (add pushgateway service on port 9091 for AlertService to push alerts)
- [ ] T129 [US7] Configure AlertManager in docker/docker-compose.yml (add alertmanager service on port 9093, configure alert routing to email/Slack/PagerDuty)
- [ ] T130 [US7] Add reconciliation scheduler startup to src/api/main.py (initialize ReconciliationScheduler on FastAPI startup event, start hourly jobs if RECONCILIATION_ENABLED=true)
- [ ] T131 [US7] Add reconciliation configuration to src/config/settings.py (RECONCILIATION_ENABLED, RECONCILIATION_INTERVAL_MINUTES=60, RECONCILIATION_DRIFT_WARNING_THRESHOLD=1.0, RECONCILIATION_DRIFT_CRITICAL_THRESHOLD=5.0, RECONCILIATION_SAMPLE_SIZE=1000, RECONCILIATION_TABLES list)

### Documentation for User Story 7

- [ ] T132 [US7] Document reconciliation feature in docs/reconciliation.md (architecture, validation strategies, alerting thresholds, API usage examples, troubleshooting common drift scenarios)
- [ ] T133 [US7] Update README.md with reconciliation section (overview, configuration options, how to trigger manual reconciliation, how to review reconciliation reports)

**Checkpoint**: All user stories 1-7 complete with data consistency validation

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T098 [P] Create architecture diagrams (docs/architecture.png showing Cassandra→Debezium→Kafka→JDBC Sink→PostgreSQL flow with supporting services)
- [ ] T099 [P] Create runbooks for common issues (docs/runbooks/high-consumer-lag.md, docs/runbooks/connector-failure.md, docs/runbooks/schema-mismatch.md, docs/runbooks/vault-sealed.md)
- [ ] T100 [P] Update README.md with complete documentation (prerequisites, quick start, architecture, monitoring, troubleshooting, deployment)
- [ ] T101 [P] Create CI/CD workflows (.github/workflows/test.yml for pytest on PR, .github/workflows/lint.yml for ruff/mypy/black, .github/workflows/security.yml for bandit/safety)
- [ ] T102 [P] Create Kubernetes Helm charts (helm/Chart.yaml, helm/values.yaml, helm/templates/deployment.yaml for Kafka Connect, configmap.yaml for connector configs, secret.yaml for Vault token)
- [ ] T103 [P] Add performance benchmarking script (scripts/benchmark.py using Locust to simulate 10K events/sec load, measure P50/P95/P99 latency)
- [ ] T104 [P] Create deployment checklist (docs/deployment-checklist.md for production readiness: TLS certificates, Vault policies, resource limits, monitoring alerts, backup strategy)
- [ ] T105 Run full E2E test suite and validate all acceptance criteria (execute tests/integration/test_end_to_end.py covering all 6 user stories, verify all success criteria from spec.md)
- [ ] T106 Verify quickstart.md instructions work on clean machine (spin up fresh VM, follow quickstart.md step-by-step, verify 5-minute setup succeeds)
- [ ] T107 Code cleanup and refactoring (remove DRY violations, extract common patterns, simplify complex functions >50 lines, ensure McCabe complexity ≤10)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-8)**: All depend on Foundational phase completion
  - User stories CAN proceed in parallel (if staffed)
  - Or sequentially in priority order (P1→P2→P3→P4→P5→P6)
- **Polish (Phase 9)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Foundation only - no other story dependencies
- **User Story 2 (P2)**: Requires US1 for testing - minimal dependency
- **User Story 3 (P3)**: Requires US1 (schema evolution needs replication working)
- **User Story 4 (P4)**: Independent - can start after Foundation
- **User Story 5 (P5)**: Requires US1 (error handling needs replication working)
- **User Story 6 (P6)**: Independent - can start after Foundation
- **User Story 7 (P7)**: Requires US1 (reconciliation needs replication working) and US4 (requires monitoring infrastructure)

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD)
- Models before services
- Services before endpoints/integrations
- Core implementation before integration
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- All Foundational tasks marked [P] can run in parallel (within Phase 2)
- Once Foundational completes, multiple user stories can start in parallel:
  - **Team Option A**: US1→US2→US3 sequential (MVP focus)
  - **Team Option B**: US1 + US4 + US6 parallel (3 developers)
- All tests for a user story marked [P] can run in parallel
- Models within a story marked [P] can run in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T006)
2. Complete Phase 2: Foundational (T007-T024) - CRITICAL - blocks all stories
3. Complete Phase 3: User Story 1 (T025-T044)
4. **STOP and VALIDATE**: Test US1 independently
5. Deploy/demo if ready

**Total tasks for MVP**: 44 tasks (Setup: 6, Foundational: 18, US1: 20)

### Incremental Delivery (Recommended)

1. Foundation → US1 → Validate → Deploy (MVP!)
2. Add US2 (Local Dev) → Validate → Improves developer productivity
3. Add US4 (Observability) → Validate → Production monitoring ready
4. Add US6 (Credentials) → Validate → Security compliance
5. Add US5 (Error Handling) → Validate → Production robustness
6. Add US7 (Reconciliation) → Validate → Data consistency validation
7. Add US3 (Schema Evolution) → Validate → Operational flexibility

### Parallel Team Strategy (3+ developers)

With multiple developers:
1. Team completes Setup + Foundational together (Days 1-3)
2. Once Foundational is done, split work:
   - Developer A: US1 (Basic Replication) - CRITICAL PATH
   - Developer B: US4 (Observability) - parallel to US1
   - Developer C: US6 (Credentials) - parallel to US1
3. Merge US1 first, then integrate US4 and US6
4. Once US1 + US4 are merged:
   - Developer A: US7 (Reconciliation) - depends on US1 + US4
   - Developer B: US5 (Error Handling) - depends on US1
   - Developer C: US2 (Local Dev) - depends on US1
5. Finally add US3 (Schema Evolution) as capacity allows

---

## Notes

- **[P] tasks**: Different files, no dependencies on incomplete tasks
- **[Story] label**: Maps task to specific user story for traceability
- **TDD workflow**: Write test → Verify it fails → Implement → Verify it passes → Refactor
- **Each user story**: Independently completable and testable
- **Commit strategy**: Commit after each task or logical group
- **Constitution compliance**: All tasks follow TDD, clean code, design patterns from constitution
- **File paths**: All paths are absolute from repository root
