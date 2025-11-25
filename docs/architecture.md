# CDC Pipeline Architecture

**Feature**: 001-cass-cdc-pg
**Version**: 1.0.0
**Date**: 2025-11-25

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CDC Pipeline Architecture                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐                    ┌──────────────────────┐
│   Cassandra Cluster  │                    │   PostgreSQL DB      │
│   (Source of Truth)  │                    │   (Target Data WH)   │
│                      │                    │                      │
│  ┌────────────────┐  │                    │  ┌────────────────┐  │
│  │ Data Tables    │  │                    │  │ cdc_users      │  │
│  │ - users        │  │                    │  │ cdc_orders     │  │
│  │ - orders       │  │                    │  │ cdc_sessions   │  │
│  │ - sessions     │  │                    │  └────────────────┘  │
│  └────────────────┘  │                    │                      │
│  ┌────────────────┐  │                    │  ┌────────────────┐  │
│  │ CommitLog CDC  │  │                    │  │ Control Tables │  │
│  │ /cdc_raw/      │  │                    │  │ - checkpoints  │  │
│  └────────┬───────┘  │                    │  │ - dlq_records  │  │
└───────────┼──────────┘                    │  │ - schema_meta  │  │
            │                                │  │ - reconcile    │  │
            │                                │  └────────────────┘  │
            ▼                                └──────────▲───────────┘
┌──────────────────────┐                               │
│  Debezium Source     │                               │
│  Connector           │                               │
│                      │                               │
│  - Reads CDC files   │                               │
│  - Parses mutations  │                               │
│  - Schema extraction │                               │
│  - Offset tracking   │                               │
└──────────┬───────────┘                               │
           │                                           │
           │ Avro/JSON events                          │
           ▼                                           │
┌──────────────────────────────────────────────────────┼───────────┐
│                    Apache Kafka Cluster               │           │
│                                                      │           │
│  ┌─────────────────────────────────────────────────┐ │           │
│  │ Topics:                                          │ │           │
│  │ - cdc-events-users (8 partitions)               │ │           │
│  │ - cdc-events-orders (8 partitions)              │ │           │
│  │ - cdc-events-sessions (8 partitions)            │ │           │
│  │ - dlq-events (1 partition)                      │ │           │
│  │ - schema-changes (1 partition)                  │ │           │
│  └─────────────────────────────────────────────────┘ │           │
│                                                      │           │
│  ┌─────────────────────────────────────────────────┐ │           │
│  │ Connect Offset Storage:                          │ │           │
│  │ - connect-offsets (checkpoint persistence)      │ │           │
│  │ - connect-configs (connector configurations)    │ │           │
│  │ - connect-status (connector health status)      │ │           │
│  └─────────────────────────────────────────────────┘ │           │
└────────────┬─────────────────────────────────────────┘           │
             │                                                      │
             │ Avro events                                          │
             ▼                                                      │
┌──────────────────────┐                                           │
│  JDBC Sink Connector │                                           │
│                      │                                           │
│  - Consumes events   │                                           │
│  - Type conversion   │                                           │
│  - UPSERT operations │                                           │
│  - DLQ routing       │                                           │
│  - Batching          │                                           │
└──────────┬───────────┘                                           │
           │                                                        │
           │ SQL INSERT/UPDATE/DELETE                              │
           └────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         Supporting Services Layer                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ Schema Registry│  │ HashiCorp Vault│  │  Prometheus    │  │    Jaeger      │
│                │  │                │  │                │  │                │
│ - Avro schemas │  │ - Credentials  │  │ - Metrics      │  │ - Traces       │
│ - Version mgmt │  │ - TLS certs    │  │ - Alerting     │  │ - Spans        │
│ - Compatibility│  │ - Secrets mgmt │  │ - Retention    │  │ - Sampling     │
└────────────────┘  └────────────────┘  └────────┬───────┘  └────────────────┘
                                                  │
                                                  │ Scrapes
                                                  ▼
                                        ┌────────────────┐
                                        │   Grafana      │
                                        │                │
                                        │ - Dashboards   │
                                        │ - Visualization│
                                        │ - Drill-down   │
                                        └────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         Reconciliation Service                               │
└─────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│  CDC API (FastAPI)                                                         │
│                                                                            │
│  ┌──────────────────────┐     ┌──────────────────────┐                    │
│  │ ReconciliationEngine │     │ ReconciliationScheduler│                  │
│  │                      │     │ (APScheduler)        │                    │
│  │ - Row count validate │     │ - Hourly triggers    │                    │
│  │ - Checksum validate  │────►│ - Manual triggers    │                    │
│  │ - Timestamp validate │     │ - Job persistence    │                    │
│  │ - Sample validate    │     └──────────────────────┘                    │
│  └──────────┬───────────┘                                                 │
│             │                                                              │
│             │ Reads data                                                   │
│             ▼                                                              │
│  ┌─────────────────┐          ┌─────────────────┐                        │
│  │ Cassandra       │          │ PostgreSQL      │                        │
│  │ (Source)        │          │ (Target)        │                        │
│  └─────────────────┘          └─────────────────┘                        │
│             │                          │                                   │
│             │ Compare                  │                                   │
│             └──────────┬───────────────┘                                   │
│                        │                                                   │
│                        ▼                                                   │
│             ┌──────────────────────┐                                      │
│             │ AlertService         │                                      │
│             │                      │                                      │
│             │ - Drift detection    │                                      │
│             │ - Alert routing      │                                      │
│             │ - Pushgateway push   │                                      │
│             └──────────┬───────────┘                                      │
│                        │                                                   │
│                        ▼                                                   │
│             ┌──────────────────────┐                                      │
│             │ Prometheus/AlertMgr  │                                      │
│             │ - ReconciliationDrift│                                      │
│             │ - JobFailed alerts   │                                      │
│             └──────────────────────┘                                      │
└────────────────────────────────────────────────────────────────────────────┘
```

## Component Descriptions

### Source System: Apache Cassandra

**Role**: Source of truth for operational data
**Version**: 4.1.3
**Key Features**:
- CommitLog-based CDC (Change Data Capture)
- Writes mutations to `/var/lib/cassandra/cdc_raw/` when CDC enabled
- No query performance impact
- Automatic CDC file rotation and cleanup

**CDC Configuration**:
```yaml
# cassandra.yaml
cdc_enabled: true
cdc_total_space_in_mb: 4096
cdc_free_space_check_interval_ms: 250
```

### CDC Connector: Debezium for Cassandra

**Role**: Captures changes from Cassandra CommitLog
**Version**: 2.5.0
**Key Features**:
- Log-based CDC (no query load on Cassandra)
- Automatic schema detection and evolution tracking
- Offset management for exactly-once delivery
- Snapshot support for initial data load

**Processing Flow**:
1. Reads CDC files from `/cdc_raw/` directory
2. Parses mutation records (INSERT, UPDATE, DELETE)
3. Extracts schema metadata from Cassandra system tables
4. Converts to Avro format with schema
5. Publishes to Kafka topics with key-based partitioning
6. Tracks offset in Kafka Connect offset topic

### Message Broker: Apache Kafka

**Role**: Durable event stream between source and sink
**Version**: 3.6.1 (KRaft mode, no Zookeeper)
**Key Features**:
- Distributed, partitioned, replicated log
- Topic-based routing (one topic per table)
- Offset-based consumption tracking
- Message retention (7 days default)

**Topic Strategy**:
- **Data Topics**: `cdc-events-{table}` (8 partitions, 3 replicas)
- **DLQ Topic**: `dlq-events` (1 partition, 3 replicas)
- **Control Topics**: `connect-offsets`, `connect-configs`, `connect-status`
- **Schema Topic**: `schema-changes` (audit log)

### Schema Management: Confluent Schema Registry

**Role**: Centralized Avro schema management
**Version**: 7.5.2
**Key Features**:
- Schema versioning and compatibility checking
- BACKWARD compatibility mode (default)
- RESTful API for schema registration
- Integration with Kafka Connect

**Schema Evolution**:
- New schema versions automatically registered by Debezium
- Compatibility validated before acceptance
- Schema ID embedded in Kafka message headers
- JDBC Sink retrieves schema by ID for DDL generation

### Target System: PostgreSQL

**Role**: Data warehouse for analytics
**Version**: 16.1
**Key Features**:
- JSONB support for complex Cassandra types (maps, sets, UDTs)
- Partitioning for large tables
- Indexes for CDC metadata columns
- TTL trigger for expiring records

**Control Tables**:
- `_cdc_schema_metadata`: Schema version history
- `_cdc_checkpoints`: Manual checkpoint tracking (optional)
- `_cdc_dlq_records`: Failed event repository
- `_cdc_reconciliation_jobs`: Reconciliation job history
- `_cdc_reconciliation_mismatches`: Data drift tracking
- `_cdc_audit_log`: GDPR compliance audit trail

### Sink Connector: JDBC Sink

**Role**: Writes Kafka events to PostgreSQL
**Version**: Confluent JDBC Sink 10.7.4
**Key Features**:
- UPSERT mode (INSERT ... ON CONFLICT UPDATE)
- Auto table creation and schema evolution
- Batching (1000 records per transaction)
- Error tolerance with DLQ routing

**Type Mapping**:
- Cassandra `text` → PostgreSQL `VARCHAR`/`TEXT`
- Cassandra `map<K,V>` → PostgreSQL `JSONB`
- Cassandra `set<T>` → PostgreSQL `T[]` (array)
- Cassandra `timestamp` → PostgreSQL `TIMESTAMPTZ`

### Secrets Management: HashiCorp Vault

**Role**: Centralized secrets and credential rotation
**Version**: 1.15.4
**Key Features**:
- KV Secrets Engine for static credentials
- Database Secrets Engine for dynamic PostgreSQL credentials
- PKI Secrets Engine for TLS certificates
- AppRole authentication for services

**Integration**:
- Cassandra credentials from `secret/data/cdc/cassandra`
- PostgreSQL dynamic credentials from `database/creds/postgresql-writer`
- TLS certificates from PKI backend
- Automatic credential refresh (24-hour TTL)

### Observability: Prometheus + Grafana + Jaeger

**Prometheus** (Metrics):
- Scrapes metrics from Kafka Connect, CDC API
- Stores 15 days of metrics data
- Evaluates alerting rules every 15 seconds
- Sends alerts to AlertManager

**Grafana** (Visualization):
- Pre-configured dashboards (CDC Pipeline, Reconciliation, Kafka)
- Prometheus datasource
- 30-second auto-refresh

**Jaeger** (Tracing):
- Distributed request tracing
- Span collection via OTLP
- UI for trace visualization
- Sampling (10% default)

### Reconciliation Service

**Role**: Validates data consistency between Cassandra and PostgreSQL
**Components**:
- **ReconciliationEngine**: Core validation logic
- **ReconciliationScheduler**: APScheduler-based hourly jobs
- **AlertService**: Prometheus pushgateway integration
- **ReconciliationRepository**: PostgreSQL persistence

**Validation Strategies**:
1. **Row Count**: Fast drift detection via COUNT(*) queries
2. **Checksum**: SHA-256 hash comparison of record contents
3. **Timestamp Range**: Validates recent changes within time window
4. **Sample**: Statistical validation with configurable sample size

## Data Flow

### Normal Operation (Happy Path)

```
1. Application writes to Cassandra
   ↓
2. Cassandra writes to CommitLog and cdc_raw
   ↓
3. Debezium reads cdc_raw, parses mutation
   ↓
4. Debezium extracts schema, converts to Avro
   ↓
5. Debezium publishes to Kafka topic (cdc-events-users)
   ↓
6. JDBC Sink consumes from Kafka
   ↓
7. JDBC Sink retrieves schema from Schema Registry
   ↓
8. JDBC Sink executes UPSERT in PostgreSQL
   ↓
9. PostgreSQL triggers update (TTL cleanup, CDC metadata update)
   ↓
10. Success - Kafka offset committed
```

### Error Handling Flow (DLQ Path)

```
1. JDBC Sink fails to write to PostgreSQL
   ↓
2. Error: Type conversion error / Constraint violation / Timeout
   ↓
3. Retry with exponential backoff (10 attempts, max 60s)
   ↓
4. All retries exhausted
   ↓
5. Route event to dlq-events Kafka topic
   ↓
6. DLQ Replay Service polls dlq-events
   ↓
7. Persist to _cdc_dlq_records table in PostgreSQL
   ↓
8. Alert fired: DLQEventsAccumulating (if rate > 10/sec)
   ↓
9. Manual intervention: Review DLQ via API
   ↓
10. Fix root cause (schema mismatch, data issue)
    ↓
11. Replay via POST /dlq/replay API
    ↓
12. Re-route to original Kafka topic
    ↓
13. Normal flow resumes
```

### Reconciliation Flow

```
1. Hourly APScheduler trigger fires
   ↓
2. ReconciliationScheduler creates ReconciliationJob
   ↓
3. ReconciliationEngine queries Cassandra: SELECT COUNT(*) FROM users
   ↓
4. ReconciliationEngine queries PostgreSQL: SELECT COUNT(*) FROM cdc_users
   ↓
5. Calculate drift percentage: |cass - pg| / cass * 100
   ↓
6. If drift > 5%: AlertService sends to Prometheus Pushgateway
   ↓
7. Prometheus evaluates ReconciliationDriftCritical alert rule
   ↓
8. AlertManager routes to Slack/PagerDuty
   ↓
9. On-call engineer reviews via GET /reconciliation/jobs/{job_id}
   ↓
10. Investigates mismatches via GET /reconciliation/mismatches
    ↓
11. Resolves via POST /reconciliation/mismatches/{id}/resolve
    ↓
12. Optional: Trigger manual re-sync from Cassandra snapshot
```

## Deployment Architecture

### Local Development (Docker Compose)

- **12 containers**: Cassandra, PostgreSQL, Kafka, Schema Registry, Kafka Connect, Vault, Prometheus, Pushgateway, AlertManager, Grafana, Jaeger, CDC API
- **Resource requirements**: 4GB RAM, 4 CPU cores
- **Network**: Single bridge network (cdc-network)
- **Volumes**: Persistent storage for databases and metrics

### Production (Kubernetes)

- **Namespaces**: `cdc-pipeline` (isolated from other apps)
- **Deployments**:
  - Cassandra StatefulSet (3 replicas)
  - PostgreSQL StatefulSet (primary + 2 read replicas)
  - Kafka StatefulSet (3 brokers)
  - Schema Registry Deployment (2 replicas)
  - Kafka Connect Deployment (3 workers, auto-scaling)
  - CDC API Deployment (2 replicas, auto-scaling)
- **Services**: ClusterIP for internal, LoadBalancer for Grafana/API
- **ConfigMaps**: Connector configurations, Prometheus rules
- **Secrets**: Vault token, TLS certificates (sealed secrets)
- **PersistentVolumeClaims**: Cassandra (500GB), PostgreSQL (1TB), Kafka (100GB per broker)

## Security

### Network Security

- **TLS 1.3** for all inter-service communication
- **mTLS** for Kafka broker-to-broker and client-to-broker
- **Network policies** in Kubernetes (deny-all-ingress by default)

### Authentication & Authorization

- **Cassandra**: Username/password (stored in Vault)
- **PostgreSQL**: Dynamic credentials from Vault (24h TTL)
- **Kafka**: SASL/SCRAM-SHA-512
- **Schema Registry**: Basic auth
- **Vault**: AppRole for service authentication
- **CDC API**: JWT bearer tokens (future: OAuth2)

### Data Protection

- **At-rest encryption**: Cassandra transparent encryption, PostgreSQL pgcrypto
- **In-transit encryption**: TLS 1.3 for all connections
- **PII masking**: Transformation rules for sensitive columns
- **GDPR compliance**: Audit logging, data erasure API

## Scalability

### Horizontal Scaling

- **Cassandra**: Add nodes to ring, rebalance tokens
- **Kafka**: Add brokers, reassign partitions
- **Kafka Connect**: Add workers, rebalance tasks
- **PostgreSQL**: Read replicas for analytics queries
- **CDC API**: Increase replica count (stateless)

### Vertical Scaling

- **Cassandra**: Increase heap size (16-32GB recommended)
- **PostgreSQL**: Increase shared_buffers (25% of RAM)
- **Kafka**: Increase broker heap (4-8GB recommended)

### Performance Tuning

- **Batching**: JDBC Sink batch size = 1000
- **Parallelism**: 8 partitions per Kafka topic
- **Compression**: Snappy compression for Kafka messages
- **Connection pooling**: PostgreSQL max_connections = 100

## Monitoring & Alerts

### Key Metrics

- **Throughput**: `cdc_events_processed_total` (target: > 5K events/sec)
- **Latency**: `cdc_processing_latency_seconds` (P95 < 2 seconds)
- **Errors**: `cdc_errors_total` (< 1% error rate)
- **Lag**: `cdc_backlog_depth` (< 10K events)
- **Drift**: `cdc_reconciliation_drift_percentage` (< 1%)

### Critical Alerts

1. **HighConsumerLag**: Kafka consumer lag > 10K events (5m)
2. **HighLatency**: P95 latency > 2 seconds (5m)
3. **HighErrorRate**: Error rate > 10/sec (5m)
4. **ReconciliationDriftCritical**: Drift > 5% (2m)
5. **KafkaConnectTaskFailure**: Connector in FAILED state (2m)

## Disaster Recovery

### Backup Strategy

- **Cassandra**: Daily snapshots to S3, retention 30 days
- **PostgreSQL**: Daily pg_dump to S3, WAL archiving for PITR
- **Kafka**: Mirror topics to DR cluster
- **Vault**: Raft snapshot every 6 hours

### Recovery Procedures

1. **Cassandra node failure**: Auto-replace via StatefulSet
2. **PostgreSQL primary failure**: Promote read replica
3. **Kafka broker failure**: Reassign partitions to surviving brokers
4. **Complete data center loss**: Restore from S3 snapshots, replay from Kafka DR cluster

## References

- [Debezium Cassandra Connector Documentation](https://debezium.io/documentation/reference/stable/connectors/cassandra.html)
- [Confluent JDBC Sink Connector](https://docs.confluent.io/kafka-connectors/jdbc/current/sink-connector/index.html)
- [Kafka KRaft Mode](https://kafka.apache.org/documentation/#kraft)
- [HashiCorp Vault Best Practices](https://learn.hashicorp.com/tutorials/vault/production-hardening)
