# Feature Specification: Cassandra to PostgreSQL CDC Pipeline

**Feature Branch**: `001-cass-cdc-pg`
**Created**: 2025-11-20
**Status**: Draft
**Input**: User description: "Create a change data capture pipeline from a Cassandra cluster to a PostgresSQL data-warehouse. The pipeline must has the following qualities: 1. Locally testable. A typical developer's laptop must be able to test it end-to-end locally. 2. Production grade. It must be capable enough for enterprise's production deployment. 3. Observable. Its logging and monitoring must be enterprise's production level. 4. Strictly Tested. Tests must be written first before implementation for all of its components. 5. Robust. There must be proper enterprise level error handling, retry strategies, and stale event handling for the cdc pipeline. 6. Flexible. There must be proper handlings of schema evolutions, and dirty data. 7. Secured. There must be dedicated credentials management system."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Basic Data Replication (Priority: P1)

As a data engineer, I need to capture all data changes from specific Cassandra tables and replicate them to PostgreSQL in near real-time, so that our analytics team can query the data using familiar SQL tools.

**Why this priority**: This is the core MVP functionality. Without basic replication, the pipeline provides no value. All other features depend on this working correctly.

**Independent Test**: Can be fully tested by inserting/updating records in a Cassandra table, waiting for replication lag time (< 5 seconds), and verifying the same records appear in PostgreSQL with correct values.

**Acceptance Scenarios**:

1. **Given** a Cassandra table with existing records, **When** the pipeline starts, **Then** all existing records are captured and loaded into PostgreSQL
2. **Given** the pipeline is running, **When** a new record is inserted in Cassandra, **Then** the record appears in PostgreSQL within 5 seconds (P95 latency requirement)
3. **Given** the pipeline is running, **When** an existing record is updated in Cassandra, **Then** the updated values appear in PostgreSQL within 5 seconds (P95 latency requirement)
4. **Given** the pipeline is running, **When** a record is deleted in Cassandra (tombstone), **Then** the corresponding record is deleted from PostgreSQL within 5 seconds (P95 latency requirement)
5. **Given** multiple tables are configured for replication, **When** changes occur in any table, **Then** only changes from configured tables are replicated

---

### User Story 2 - Local Development Environment (Priority: P2)

As a developer, I need to run the entire CDC pipeline on my laptop using Docker containers for both Cassandra and PostgreSQL, so that I can develop, test, and debug changes without requiring access to production or staging environments.

**Why this priority**: Enables rapid development iteration and testing. Critical for developer productivity and reducing dependency on shared environments.

**Independent Test**: Can be fully tested by running a single command (e.g., `docker-compose up`) that starts Cassandra, PostgreSQL, and the CDC pipeline, then verifying data replication works end-to-end locally.

**Acceptance Scenarios**:

1. **Given** Docker is installed on a developer laptop, **When** the developer runs the setup script, **Then** all components (Cassandra, PostgreSQL, CDC pipeline) start successfully
2. **Given** the local environment is running, **When** test data is inserted into local Cassandra, **Then** the data replicates to local PostgreSQL correctly
3. **Given** the local environment is running, **When** the developer makes code changes and restarts the pipeline, **Then** changes take effect within 30 seconds
4. **Given** limited laptop resources (8GB RAM), **When** the local environment runs, **Then** total memory usage stays under 4GB
5. **Given** the developer stops the environment, **When** it is restarted, **Then** the pipeline resumes from the last checkpoint without data loss

---

### User Story 3 - Schema Evolution Handling (Priority: P3)

As a data engineer, I need the pipeline to automatically detect and handle schema changes in Cassandra (new columns, dropped columns, type changes), so that the replication continues without manual intervention when schemas evolve.

**Why this priority**: Reduces operational burden and prevents pipeline failures when schemas change. However, basic replication can work with static schemas initially.

**Independent Test**: Can be fully tested by adding a new column to a Cassandra table, inserting records with the new column, and verifying PostgreSQL schema updates automatically and new data includes the new column.

**Acceptance Scenarios**:

1. **Given** a replicated table, **When** a new column is added to the Cassandra table, **Then** PostgreSQL table is automatically altered to add the column
2. **Given** a replicated table, **When** a column is dropped from Cassandra, **Then** PostgreSQL column is marked deprecated (not dropped) to preserve historical data
3. **Given** a replicated table, **When** a column type changes in Cassandra (compatible change like int to bigint), **Then** PostgreSQL column type is updated accordingly
4. **Given** schema evolution is in progress, **When** data changes occur, **Then** the pipeline continues processing without data loss
5. **Given** an incompatible schema change occurs (e.g., string to int), **When** detected, **Then** affected records are routed to dead letter queue with clear error messages

---

### User Story 4 - Production Observability (Priority: P4)

As an operations engineer, I need comprehensive metrics, logs, and traces for the CDC pipeline, so that I can monitor health, diagnose issues, and optimize performance in production.

**Why this priority**: Critical for production operations but not required for initial MVP functionality. Can be added incrementally as system stabilizes.

**Independent Test**: Can be fully tested by querying metrics endpoint (e.g., Prometheus /metrics), reviewing structured logs (JSON format), and viewing distributed traces in a trace viewer showing end-to-end request flows.

**Acceptance Scenarios**:

1. **Given** the pipeline is running, **When** accessing the metrics endpoint, **Then** key metrics are exposed (throughput, latency, error rate, backlog depth)
2. **Given** the pipeline processes events, **When** reviewing logs, **Then** all logs are in structured JSON format with correlation IDs
3. **Given** an error occurs, **When** examining logs, **Then** error includes full context (table name, record ID, error type, stack trace)
4. **Given** the pipeline is healthy, **When** health check endpoint is called, **Then** it returns 200 OK with component status details
5. **Given** distributed tracing is enabled, **When** a record is replicated, **Then** trace spans show timing for each stage (capture, transform, load)

---

### User Story 5 - Error Handling & Recovery (Priority: P5)

As an operations engineer, I need the pipeline to automatically handle transient failures with retries, route permanently failed records to a dead letter queue, and recover from crashes without data loss, so that the system remains reliable under adverse conditions.

**Why this priority**: Essential for production reliability but can be basic initially. Advanced retry strategies and recovery mechanisms can evolve over time.

**Independent Test**: Can be fully tested by simulating PostgreSQL outage, observing retry behavior with exponential backoff, verifying pipeline eventually succeeds when PostgreSQL recovers, and confirming failed records appear in DLQ.

**Acceptance Scenarios**:

1. **Given** PostgreSQL is temporarily unavailable, **When** the pipeline attempts to write, **Then** it retries with exponential backoff (1s, 2s, 4s, 8s, up to 60s)
2. **Given** retries are exhausted (after 5 minutes), **When** write still fails, **Then** record is moved to dead letter queue for manual review
3. **Given** the pipeline crashes, **When** it restarts, **Then** it resumes from the last committed checkpoint without data loss or duplication
4. **Given** corrupt data is encountered, **When** processing the record, **Then** record is routed to DLQ with validation error details
5. **Given** DLQ contains failed records, **When** root cause is fixed, **Then** records can be manually replayed through the pipeline

---

### User Story 6 - Credentials Management (Priority: P6)

As a security engineer, I need all database credentials and secrets to be stored in a secure vault (not in code or config files), rotated automatically, and accessed only by authorized services, so that the system meets enterprise security standards.

**Why this priority**: Critical for security compliance but can start with environment variables in development. Production deployment must use proper secrets management.

**Independent Test**: Can be fully tested by configuring the pipeline to retrieve credentials from HashiCorp Vault, verifying no credentials appear in logs or config files, and rotating credentials while pipeline continues running without interruption.

**Acceptance Scenarios**:

1. **Given** credentials are stored in Vault, **When** the pipeline starts, **Then** it retrieves credentials from Vault (not from environment variables or config files)
2. **Given** the pipeline is running, **When** credentials are rotated in Vault, **Then** the pipeline detects rotation and refreshes credentials within 5 minutes
3. **Given** an unauthorized service attempts access, **When** requesting credentials from Vault, **Then** access is denied with audit log entry
4. **Given** pipeline logs are generated, **When** reviewing logs, **Then** no credentials or sensitive data appear in logs
5. **Given** development environment is running, **When** using local Vault instance, **Then** developers can test secret rotation scenarios

---

### Edge Cases

- **What happens when Cassandra replication lag causes same record to be captured multiple times?**
  - System must deduplicate based on record timestamp/version to ensure exactly-once semantics

- **What happens when PostgreSQL table exists but has different schema than expected?**
  - Pipeline should detect mismatch on startup, log clear error, and refuse to start until schema is reconciled

- **What happens when network partition causes Cassandra cluster split-brain?**
  - Pipeline should connect to Cassandra using consistency level QUORUM to avoid reading inconsistent data

- **What happens when a Cassandra table has millions of existing records at startup?**
  - Pipeline should support configurable backfill batch size to avoid overwhelming PostgreSQL and provide progress tracking

- **What happens when PostgreSQL transaction log grows too large?**
  - Pipeline should support batching commits (e.g., commit every 1000 records) to balance durability with performance

- **What happens when data contains characters that break JSON or SQL escaping?**
  - Pipeline must properly escape all data using parameterized queries and validated JSON serialization

- **What happens when stale events arrive out of order (older update after newer update)?**
  - Pipeline should use event timestamps to detect out-of-order events and apply "last write wins" or configurable conflict resolution strategy

- **What happens when a Cassandra node goes down during capture?**
  - Pipeline should automatically failover to another Cassandra node using driver's built-in retry and reconnection logic

## Requirements *(mandatory)*

### Functional Requirements

#### Core Data Replication

- **FR-001**: System MUST capture all data changes (inserts, updates, deletes) from configured Cassandra tables
- **FR-002**: System MUST replicate captured changes to corresponding PostgreSQL tables
- **FR-003**: System MUST support exactly-once delivery semantics (no duplicates, no data loss)
- **FR-004**: System MUST maintain change order per partition key to preserve Cassandra's consistency guarantees
- **FR-005**: System MUST checkpoint progress periodically (every 10 seconds or 5000 records) to enable recovery from failures
- **FR-006**: System MUST support filtering replication by keyspace, table, and column families
- **FR-007**: System MUST handle Cassandra tombstones (deletions) and replicate as DELETE operations to PostgreSQL
- **FR-008**: System MUST preserve Cassandra TTL information and apply equivalent retention in PostgreSQL

#### Data Transformation

- **FR-009**: System MUST map Cassandra data types to equivalent PostgreSQL types (text→varchar, int→integer, uuid→uuid, timestamp→timestamptz, etc.)
- **FR-010**: System MUST handle Cassandra collection types (list, set, map) by converting to PostgreSQL array or JSONB
- **FR-011**: System MUST handle Cassandra UDTs (User Defined Types) by converting to PostgreSQL composite types or JSONB
- **FR-012**: System MUST validate data integrity constraints (not null, unique, foreign keys) before loading to PostgreSQL
- **FR-013**: System MUST apply configurable transformation rules (e.g., masking PII, normalizing timestamps to UTC)

#### Schema Management

- **FR-014**: System MUST automatically detect schema changes in Cassandra tables
- **FR-015**: System MUST apply corresponding schema changes to PostgreSQL tables (add columns, alter types for compatible changes)
- **FR-016**: System MUST handle backward-compatible schema evolution without pipeline restart
- **FR-017**: System MUST route incompatible schema changes (breaking type changes) to DLQ with clear error messages
- **FR-018**: System MUST maintain schema version history for audit and rollback purposes

#### Error Handling & Resilience

- **FR-019**: System MUST retry transient failures (network errors, database timeouts) with exponential backoff
- **FR-020**: System MUST implement circuit breaker pattern for PostgreSQL connections (open after 5 consecutive failures, half-open after 60 seconds)
- **FR-021**: System MUST route permanently failed records to Dead Letter Queue after maximum retry attempts (5 minutes of retries)
- **FR-022**: System MUST continue processing other records when individual records fail (error isolation)
- **FR-023**: System MUST recover from crashes by resuming from last committed checkpoint without data loss
- **FR-024**: System MUST handle backpressure by pausing Cassandra consumption when PostgreSQL cannot keep up
- **FR-025**: System MUST detect and handle out-of-order events using event timestamps with configurable conflict resolution strategy

#### Observability

- **FR-026**: System MUST emit metrics for throughput (events/second), latency (P50, P95, P99), error rate, and backlog depth (Kafka consumer lag measured in event count, representing number of unprocessed events per topic partition)
- **FR-027**: System MUST log all operations in structured JSON format with correlation IDs for tracing
- **FR-028**: System MUST provide health check endpoint reporting status of all components (Cassandra, PostgreSQL, message queue)
- **FR-029**: System MUST support distributed tracing with spans for each pipeline stage (capture, transform, load)
- **FR-030**: System MUST not log sensitive data (credentials, PII) in logs or metrics

#### Security

- **FR-031**: System MUST retrieve all credentials from secure vault (HashiCorp Vault or equivalent), never from environment variables or config files in production
- **FR-032**: System MUST support automatic credential rotation without service restart
- **FR-033**: System MUST encrypt all network communication using TLS 1.3 (Cassandra connections, PostgreSQL connections)
- **FR-034**: System MUST authenticate to Cassandra and PostgreSQL using short-lived credentials (max 24 hours TTL)
- **FR-035**: System MUST apply principle of least privilege (read-only access to Cassandra, write-only to specific PostgreSQL schemas)

#### Local Development

- **FR-036**: System MUST provide Docker Compose configuration to run entire pipeline locally (Cassandra, PostgreSQL, pipeline components)
- **FR-037**: Local environment MUST run on standard developer laptop with 8GB RAM and 4 CPU cores
- **FR-038**: Local environment MUST include sample data and configuration for testing all pipeline features
- **FR-039**: Local environment MUST support hot-reload for code changes without full restart
- **FR-040**: Local environment MUST use simplified secrets management (environment variables acceptable for local dev)

#### Performance

- **FR-041**: System MUST process at minimum 10,000 events per second per pipeline instance (baseline performance target; higher throughput is acceptable and encouraged)
- **FR-042**: System MUST maintain end-to-end latency (capture to PostgreSQL commit) under 2 seconds at P95
- **FR-043**: System MUST support horizontal scaling by partitioning work across multiple pipeline instances
- **FR-044**: System MUST use batching for PostgreSQL writes (configurable batch size, default 1000 records)
- **FR-045**: System MUST use connection pooling for database connections (min 5, max 50 connections per pool)

### Key Entities

- **Change Event**: Represents a single data change captured from Cassandra
  - Attributes: table name, partition key, clustering key, operation type (INSERT/UPDATE/DELETE), column values, timestamp, event ID
  - Relationships: Maps to one PostgreSQL write operation

- **Checkpoint**: Tracks pipeline progress for recovery
  - Attributes: table name, partition key range, last processed timestamp, last processed event ID, checkpoint timestamp
  - Relationships: One checkpoint per Cassandra partition per table

- **Schema Metadata**: Stores current and historical schema information
  - Attributes: table name, column definitions (name, type, nullable), version number, effective timestamp
  - Relationships: Links Change Events to Schema versions for correct transformation

- **Dead Letter Queue Record**: Failed event that requires manual intervention
  - Attributes: original change event, error type, error message, retry count, first failed timestamp, last retry timestamp
  - Relationships: References original Change Event and Schema version

- **Configuration**: Defines what to replicate and how
  - Attributes: source keyspace/tables, destination PostgreSQL schemas/tables, transformation rules, filter predicates
  - Relationships: Determines which Change Events are processed

- **Metrics Snapshot**: Point-in-time measurements of pipeline health
  - Attributes: timestamp, events processed, throughput, latency percentiles, error count, backlog depth
  - Relationships: Aggregated from Change Event processing

## Success Criteria *(mandatory)*

### Measurable Outcomes

#### Functionality

- **SC-001**: Inserting 10,000 records into Cassandra results in exactly 10,000 records appearing in PostgreSQL with identical values (100% correctness)
- **SC-002**: Pipeline successfully replicates data from Cassandra tables with 20+ different data types without data loss or corruption
- **SC-003**: Developer can run complete local environment with single command and verify end-to-end replication within 5 minutes

#### Performance

- **SC-004**: Pipeline processes at least 10,000 change events per second per instance under steady load
- **SC-005**: 95% of events replicate from Cassandra to PostgreSQL within 2 seconds (P95 latency ≤ 2s)
- **SC-006**: Pipeline scales linearly to 100,000 events/second with 10 instances

#### Reliability

- **SC-007**: Pipeline recovers from crashes within 30 seconds and resumes processing without data loss (zero events lost)
- **SC-008**: Pipeline maintains 99.9% uptime over 30-day period (≤ 43 minutes downtime/month)
- **SC-009**: Transient PostgreSQL failures (up to 5 minutes) do not cause data loss, pipeline automatically recovers when service restores
- **SC-010**: Out-of-order events are correctly handled with less than 0.1% conflict rate

#### Schema Evolution

- **SC-011**: Adding a new column to Cassandra table automatically updates PostgreSQL schema within 10 seconds without pipeline restart
- **SC-012**: Pipeline successfully handles 100 schema changes per day without failures

#### Observability

- **SC-013**: All critical metrics (throughput, latency, errors) are visible in monitoring dashboard with 1-second refresh rate
- **SC-014**: 100% of errors include sufficient context to diagnose root cause within 5 minutes (table name, record ID, error type, correlation ID)
- **SC-015**: Distributed traces allow tracking individual record's journey from Cassandra to PostgreSQL with timing breakdown for each stage

#### Security

- **SC-016**: Zero credentials appear in code, configuration files, or logs (100% compliance verified by automated scan)
- **SC-017**: Credential rotation completes within 5 minutes with zero service interruption
- **SC-018**: All network communication uses TLS 1.3 encryption (100% of connections encrypted)

#### Operational

- **SC-019**: Mean time to recovery (MTTR) for common issues is under 10 minutes using provided runbooks
- **SC-020**: Local development environment runs on laptop using less than 4GB RAM and completes full test suite in under 2 minutes
- **SC-021**: Dead Letter Queue contains less than 0.01% of total events (99.99% success rate)

## Assumptions

1. **Cassandra Version**: Cassandra 3.11+ or 4.0+ is used (CDC features available)
2. **PostgreSQL Version**: PostgreSQL 12+ is used (supports JSONB, arrays, partitioning)
3. **Network**: Cassandra and PostgreSQL are network-accessible with latency < 10ms
4. **Authentication**: Both Cassandra and PostgreSQL support username/password or certificate-based authentication
5. **Capacity**: PostgreSQL has sufficient capacity to store all replicated data (no auto-scaling of storage)
6. **Consistency**: Cassandra uses tunable consistency; pipeline reads at QUORUM level for consistency
7. **Schema Changes**: Schema changes are infrequent (< 10 per day) and mostly backward-compatible
8. **Message Queue**: System uses Apache Kafka 3.6+ for buffering between capture and load stages (required for Debezium compatibility and exactly-once semantics)
9. **Deployment**: Production deployment uses Kubernetes or equivalent orchestration platform
10. **Monitoring**: Prometheus and Grafana (or equivalent) are available for metrics collection and visualization
11. **Tracing**: Jaeger or Zipkin (or equivalent) is available for distributed tracing
12. **Secrets**: HashiCorp Vault (or equivalent) is available for production secrets management
13. **Data Volume**: Initial backfill involves up to 100 million existing records per table
14. **Change Rate**: Expected change rate is 1,000 - 50,000 events/second peak load

## Dependencies

- **External Systems**: Cassandra cluster, PostgreSQL database, message queue (Kafka), secrets vault (HashiCorp Vault)
- **Development Tools**: Docker, Docker Compose for local development
- **Monitoring Stack**: Prometheus, Grafana, distributed tracing system (Jaeger/Zipkin)
- **Previous Features**: None (this is a greenfield project)

## Out of Scope

The following are explicitly **not** included in this feature:

- **Bi-directional replication**: Only Cassandra → PostgreSQL, not PostgreSQL → Cassandra
- **Historical data versioning**: Only current state is maintained in PostgreSQL, not full history
- **Real-time analytics**: Pipeline is near real-time (seconds latency), not sub-second streaming analytics
- **Data quality validation**: Basic type validation only, not complex business rules validation
- **Custom transformations UI**: Transformation rules defined in code/config, not through graphical interface
- **Multi-tenancy**: Single pipeline instance serves single Cassandra-PostgreSQL pair, not multi-tenant
- **Automatic conflict resolution UI**: Conflict resolution strategy is configured, not dynamically adjustable
- **Cross-datacenter replication**: Assumes single datacenter; multi-DC coordination is out of scope
