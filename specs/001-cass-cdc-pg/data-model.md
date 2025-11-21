# Data Model: CDC Pipeline Entities

**Feature**: 001-cass-cdc-pg
**Date**: 2025-11-20
**Status**: Approved

## Overview

This document defines the core entities used throughout the CDC pipeline for tracking changes, managing checkpoints, handling errors, and maintaining schema metadata.

## Entity Definitions

### 1. Change Event

**Description**: Represents a single data change captured from Cassandra, enriched with metadata for processing and tracking.

**Purpose**:
- Primary unit of work in the CDC pipeline
- Carries all information needed to replicate change to PostgreSQL
- Enables tracing and debugging of individual events

**Attributes**:

| Attribute | Type | Nullable | Description | Validation Rules |
|-----------|------|----------|-------------|------------------|
| `event_id` | UUID | No | Unique identifier for this event | UUID v4 format |
| `source_keyspace` | String | No | Cassandra keyspace name | Max 48 chars, alphanumeric + underscore |
| `source_table` | String | No | Cassandra table name | Max 48 chars, alphanumeric + underscore |
| `partition_key` | JSON | No | Cassandra partition key values | JSON object with key-value pairs |
| `clustering_key` | JSON | Yes | Cassandra clustering key values | JSON object or null |
| `operation_type` | Enum | No | Type of operation | One of: INSERT, UPDATE, DELETE, SCHEMA_CHANGE |
| `before_values` | JSON | Yes | Column values before change (for UPDATE/DELETE) | JSON object or null |
| `after_values` | JSON | Yes | Column values after change (for INSERT/UPDATE) | JSON object or null |
| `column_types` | JSON | No | Data type information for each column | Map of column_name -> type_name |
| `timestamp_micros` | Integer | No | Event timestamp (microseconds since epoch) | Positive long integer |
| `captured_at` | Timestamp | No | When event was captured by Debezium | ISO 8601 format with timezone |
| `schema_version` | Integer | No | Schema version at time of capture | Positive integer, references schema_metadata |
| `trace_id` | String | Yes | Distributed tracing correlation ID | 32-character hex string |
| `ttl_seconds` | Integer | Yes | Cassandra TTL if applicable | Positive integer or null |
| `is_tombstone` | Boolean | No | True if this is a delete tombstone | Default: false |

**Relationships**:
- References `Schema Metadata` via `schema_version`
- One-to-one with PostgreSQL write operation
- Can become `Dead Letter Queue Record` if processing fails

**Example (JSON serialization)**:
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_keyspace": "warehouse",
  "source_table": "users",
  "partition_key": {"id": "user-12345"},
  "clustering_key": null,
  "operation_type": "UPDATE",
  "before_values": {
    "id": "user-12345",
    "username": "john_doe",
    "email": "john@example.com",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-06-20T14:22:00Z"
  },
  "after_values": {
    "id": "user-12345",
    "username": "john_doe",
    "email": "john.doe@example.com",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2025-11-20T08:45:00Z"
  },
  "column_types": {
    "id": "text",
    "username": "text",
    "email": "text",
    "created_at": "timestamp",
    "updated_at": "timestamp"
  },
  "timestamp_micros": 1732092300000000,
  "captured_at": "2025-11-20T08:45:00.123456Z",
  "schema_version": 3,
  "trace_id": "a1b2c3d4e5f6789012345678abcdef90",
  "ttl_seconds": null,
  "is_tombstone": false
}
```

**Indexes** (if stored in database):
- Primary key: `event_id`
- Secondary indexes: `(source_table, timestamp_micros)`, `trace_id`
- Partition by: `source_table` (for horizontal scaling)

---

### 2. Checkpoint

**Description**: Tracks CDC pipeline progress per Cassandra table partition, enabling resumable processing after failures.

**Purpose**:
- Enable exactly-once delivery semantics
- Allow pipeline to resume from last successful position after crash
- Track lag and processing velocity per partition

**Attributes**:

| Attribute | Type | Nullable | Description | Validation Rules |
|-----------|------|----------|-------------|------------------|
| `checkpoint_id` | UUID | No | Unique identifier for checkpoint record | UUID v4 format |
| `source_keyspace` | String | No | Cassandra keyspace name | Max 48 chars |
| `source_table` | String | No | Cassandra table name | Max 48 chars |
| `partition_key_hash` | String | No | Hash of partition key for grouping | 64-character hex string (SHA-256) |
| `partition_key_range_start` | String | Yes | Start of token range (for distributed checkpoints) | Cassandra token format |
| `partition_key_range_end` | String | Yes | End of token range | Cassandra token format |
| `last_processed_event_id` | UUID | No | Last successfully processed event | UUID v4 format, references change_event |
| `last_processed_timestamp_micros` | Integer | No | Timestamp of last processed event | Positive long integer |
| `checkpoint_timestamp` | Timestamp | No | When this checkpoint was created | ISO 8601 with timezone |
| `events_processed_count` | Integer | No | Total events processed in this partition | Non-negative integer |
| `kafka_offset` | Integer | Yes | Kafka topic offset for this checkpoint | Non-negative long integer |
| `kafka_partition` | Integer | Yes | Kafka partition number | 0-1023 |
| `status` | Enum | No | Checkpoint status | One of: ACTIVE, COMPLETED, FAILED |
| `last_error_message` | String | Yes | Error message if status=FAILED | Max 1000 chars |

**Relationships**:
- One checkpoint per (table, partition_key_hash)
- References last `Change Event` via `last_processed_event_id`
- Used by pipeline to determine resume point

**Checkpoint Strategy**:
- Checkpoint every 10 seconds OR 5000 events (whichever first)
- Atomic update with transaction boundary
- Stored in Kafka offset topic (distributed) or PostgreSQL control table (centralized)

**Example**:
```json
{
  "checkpoint_id": "660f9500-f3ac-42e5-b826-557766550111",
  "source_keyspace": "warehouse",
  "source_table": "orders",
  "partition_key_hash": "a1b2c3d4e5f6789012345678abcdef9012345678abcdef9012345678abcdef90",
  "partition_key_range_start": "-9223372036854775808",
  "partition_key_range_end": "-6148914691236517205",
  "last_processed_event_id": "770fa611-04bd-53f6-c937-668877660222",
  "last_processed_timestamp_micros": 1732092350000000,
  "checkpoint_timestamp": "2025-11-20T08:46:00.000000Z",
  "events_processed_count": 127456,
  "kafka_offset": 127456,
  "kafka_partition": 2,
  "status": "ACTIVE",
  "last_error_message": null
}
```

**Storage**:
- Option 1: Kafka Connect offset topic (`connect-offsets`) - automatic
- Option 2: PostgreSQL `_cdc_checkpoints` control table - manual management

---

### 3. Schema Metadata

**Description**: Stores current and historical schema definitions for Cassandra tables, enabling schema evolution tracking and backward compatibility.

**Purpose**:
- Track schema changes over time
- Enable correct transformation of events captured under different schemas
- Support schema compatibility validation
- Audit schema evolution history

**Attributes**:

| Attribute | Type | Nullable | Description | Validation Rules |
|-----------|------|----------|-------------|------------------|
| `schema_id` | UUID | No | Unique identifier for this schema version | UUID v4 format |
| `source_keyspace` | String | No | Cassandra keyspace name | Max 48 chars |
| `source_table` | String | No | Cassandra table name | Max 48 chars |
| `version` | Integer | No | Sequential version number | Positive integer, monotonically increasing |
| `columns` | JSON | No | Column definitions (name, type, nullable, position) | Array of column objects |
| `primary_key` | JSON | No | Primary key definition (partition + clustering keys) | JSON object |
| `table_options` | JSON | Yes | Cassandra table options (compaction, compression, etc.) | JSON object |
| `avro_schema` | JSON | No | Avro schema registered in Schema Registry | Valid Avro schema JSON |
| `avro_schema_id` | Integer | Yes | Schema Registry schema ID | Positive integer |
| `effective_from` | Timestamp | No | When this schema version became active | ISO 8601 with timezone |
| `effective_to` | Timestamp | Yes | When this schema version was superseded (null if current) | ISO 8601 with timezone or null |
| `compatibility_mode` | Enum | No | Schema evolution compatibility | One of: BACKWARD, FORWARD, FULL, NONE |
| `change_type` | Enum | No | Type of schema change | One of: CREATED, COLUMN_ADDED, COLUMN_DROPPED, TYPE_CHANGED, INDEX_ADDED |
| `change_description` | String | Yes | Human-readable description of change | Max 500 chars |

**Relationships**:
- One-to-many with `Change Event` (events reference schema version)
- Self-referencing: Each version links to previous version via `version - 1`
- References external Schema Registry via `avro_schema_id`

**Schema Evolution Rules**:
1. **BACKWARD** (default): New schema can read data written with old schema
   - Allowed: Add optional column, remove column
   - Forbidden: Rename column, change type incompatibly
2. **FORWARD**: Old schema can read data written with new schema
   - Allowed: Add column with default, remove optional column
3. **FULL**: Both backward and forward compatible
4. **NONE**: No compatibility checks (requires manual validation)

**Example**:
```json
{
  "schema_id": "880fb722-15ce-64g7-d048-779988771333",
  "source_keyspace": "warehouse",
  "source_table": "users",
  "version": 3,
  "columns": [
    {
      "name": "id",
      "type": "text",
      "nullable": false,
      "position": 0,
      "is_partition_key": true,
      "is_clustering_key": false
    },
    {
      "name": "username",
      "type": "text",
      "nullable": false,
      "position": 1,
      "is_partition_key": false,
      "is_clustering_key": false
    },
    {
      "name": "email",
      "type": "text",
      "nullable": true,
      "position": 2,
      "is_partition_key": false,
      "is_clustering_key": false
    },
    {
      "name": "phone_number",
      "type": "text",
      "nullable": true,
      "position": 3,
      "is_partition_key": false,
      "is_clustering_key": false,
      "added_in_version": 3
    }
  ],
  "primary_key": {
    "partition_keys": ["id"],
    "clustering_keys": []
  },
  "table_options": {
    "compaction": {"class": "SizeTieredCompactionStrategy"},
    "compression": {"sstable_compression": "LZ4Compressor"}
  },
  "avro_schema": {
    "type": "record",
    "name": "users",
    "namespace": "warehouse",
    "fields": [
      {"name": "id", "type": "string"},
      {"name": "username", "type": "string"},
      {"name": "email", "type": ["null", "string"], "default": null},
      {"name": "phone_number", "type": ["null", "string"], "default": null}
    ]
  },
  "avro_schema_id": 3,
  "effective_from": "2025-11-20T08:00:00Z",
  "effective_to": null,
  "compatibility_mode": "BACKWARD",
  "change_type": "COLUMN_ADDED",
  "change_description": "Added phone_number column for contact information"
}
```

**Storage**: PostgreSQL `_cdc_schema_metadata` control table

**Indexes**:
- Primary key: `schema_id`
- Unique: `(source_table, version)`
- Index: `(source_table, effective_from)` for temporal queries

---

### 4. Dead Letter Queue Record

**Description**: Failed events that could not be processed after exhausting retry attempts, requiring manual intervention or debugging.

**Purpose**:
- Isolate failures to prevent blocking healthy event processing
- Preserve failed events for debugging and replay
- Track failure patterns for system improvements
- Enable manual or automated recovery workflows

**Attributes**:

| Attribute | Type | Nullable | Description | Validation Rules |
|-----------|------|----------|-------------|------------------|
| `dlq_id` | UUID | No | Unique identifier for DLQ entry | UUID v4 format |
| `original_event` | JSON | No | Complete original Change Event | Serialized Change Event entity |
| `error_type` | Enum | No | Category of error | One of: SCHEMA_MISMATCH, TYPE_CONVERSION_ERROR, CONSTRAINT_VIOLATION, NETWORK_TIMEOUT, UNKNOWN |
| `error_message` | String | No | Detailed error description | Max 2000 chars |
| `error_stack_trace` | String | Yes | Full exception stack trace | Max 5000 chars |
| `retry_count` | Integer | No | Number of retry attempts before DLQ | Non-negative integer |
| `first_failed_at` | Timestamp | No | When error first occurred | ISO 8601 with timezone |
| `last_retry_at` | Timestamp | No | Most recent retry attempt | ISO 8601 with timezone |
| `dlq_timestamp` | Timestamp | No | When event was moved to DLQ | ISO 8601 with timezone |
| `source_component` | String | No | Which component generated the error | One of: SOURCE_CONNECTOR, TRANSFORM, SINK_CONNECTOR |
| `resolution_status` | Enum | No | Current resolution state | One of: UNRESOLVED, IN_PROGRESS, RESOLVED, DISCARDED |
| `resolution_notes` | String | Yes | Human notes on resolution attempt | Max 1000 chars |
| `resolved_at` | Timestamp | Yes | When issue was resolved | ISO 8601 with timezone or null |
| `resolved_by` | String | Yes | Username or system that resolved | Max 100 chars |

**Relationships**:
- One-to-one with original `Change Event`
- May reference `Schema Metadata` for schema mismatch errors

**Error Types & Common Causes**:

| Error Type | Common Causes | Resolution Strategy |
|------------|---------------|---------------------|
| `SCHEMA_MISMATCH` | Column missing in PostgreSQL, incompatible type change | Alter PostgreSQL schema, replay event |
| `TYPE_CONVERSION_ERROR` | Invalid data format (e.g., "abc" → integer) | Fix data or add validation rule |
| `CONSTRAINT_VIOLATION` | Unique key conflict, foreign key violation, null constraint | Resolve data conflict, replay |
| `NETWORK_TIMEOUT` | PostgreSQL unavailable, network partition | Wait for recovery, replay |
| `UNKNOWN` | Unexpected exception | Investigate logs, fix bug, replay |

**Example**:
```json
{
  "dlq_id": "990fc833-26df-75h8-e159-88aa99882444",
  "original_event": {
    "event_id": "550e8400-e29b-41d4-a716-446655440000",
    "source_table": "users",
    "operation_type": "INSERT",
    "after_values": {"id": "user-999", "age": "not-a-number"},
    ...
  },
  "error_type": "TYPE_CONVERSION_ERROR",
  "error_message": "Failed to convert column 'age' value 'not-a-number' to PostgreSQL type INTEGER",
  "error_stack_trace": "Traceback (most recent call last):\n  File \"sink.py\", line 123...",
  "retry_count": 10,
  "first_failed_at": "2025-11-20T08:30:00Z",
  "last_retry_at": "2025-11-20T08:35:00Z",
  "dlq_timestamp": "2025-11-20T08:35:05Z",
  "source_component": "SINK_CONNECTOR",
  "resolution_status": "UNRESOLVED",
  "resolution_notes": null,
  "resolved_at": null,
  "resolved_by": null
}
```

**Storage**:
- Kafka DLQ topic: `dlq-events` (primary, for event replay)
- PostgreSQL table: `_cdc_dlq_records` (secondary, for reporting/querying)

**DLQ Replay API**:
```http
POST /api/v1/dlq/replay
Content-Type: application/json

{
  "dlq_ids": ["990fc833-26df-75h8-e159-88aa99882444"],
  "resolution_notes": "Fixed schema mismatch by adding missing column",
  "retry_strategy": "immediate"  // or "scheduled", "rate_limited"
}
```

---

### 5. Configuration

**Description**: Defines what data to replicate, how to transform it, and pipeline behavior parameters.

**Purpose**:
- Declarative pipeline configuration (infrastructure as code)
- Version-controlled pipeline definitions
- Enable multiple independent pipelines with different configs
- Validation and auditing of configuration changes

**Attributes**:

| Attribute | Type | Nullable | Description | Validation Rules |
|-----------|------|----------|-------------|------------------|
| `config_id` | UUID | No | Unique identifier for this configuration | UUID v4 format |
| `config_name` | String | No | Human-readable configuration name | Max 100 chars, unique |
| `version` | Integer | No | Configuration version | Positive integer |
| `enabled` | Boolean | No | Whether this configuration is active | Default: true |
| `source_connection` | JSON | No | Cassandra connection parameters | JSON object with host, port, auth |
| `target_connection` | JSON | No | PostgreSQL connection parameters | JSON object with host, port, database, auth |
| `replication_rules` | JSON | No | Tables to replicate and filters | Array of replication rule objects |
| `transformation_rules` | JSON | Yes | Data transformation logic | Array of transformation rule objects |
| `performance_tuning` | JSON | No | Batch sizes, parallelism, timeouts | JSON object with tuning parameters |
| `error_handling` | JSON | No | Retry policies, DLQ behavior | JSON object with error handling config |
| `monitoring` | JSON | No | Metrics, logging, tracing settings | JSON object with observability config |
| `created_at` | Timestamp | No | When configuration was created | ISO 8601 with timezone |
| `updated_at` | Timestamp | No | Last modification timestamp | ISO 8601 with timezone |
| `created_by` | String | No | User who created configuration | Max 100 chars |
| `checksum` | String | No | SHA-256 hash of configuration for validation | 64-character hex string |

**Replication Rule Structure**:
```json
{
  "source_keyspace": "warehouse",
  "source_table": "users",
  "target_schema": "public",
  "target_table": "cdc_users",
  "include_columns": ["id", "username", "email", "created_at"],
  "exclude_columns": null,
  "filter_predicate": "created_at > '2024-01-01'",  // CQL WHERE clause
  "snapshot_mode": "initial",  // initial, never, schema_only
  "partition_filter": null  // Optional: limit to specific partitions
}
```

**Transformation Rule Structure**:
```json
{
  "rule_name": "mask_email",
  "rule_type": "MASK",  // MASK, REDACT, CAST, RENAME, COMPUTE
  "source_column": "email",
  "target_column": "email",
  "transformation": "REPLACE(email, SUBSTRING(email, 1, POSITION('@' IN email) - 1), '***')",
  "condition": null  // Optional: apply conditionally
}
```

**Example Configuration**:
```json
{
  "config_id": "aa0fd944-37eg-86i9-f260-99bb00993555",
  "config_name": "warehouse-to-analytics",
  "version": 1,
  "enabled": true,
  "source_connection": {
    "hosts": ["cassandra-1", "cassandra-2", "cassandra-3"],
    "port": 9042,
    "datacenter": "dc1",
    "consistency_level": "QUORUM",
    "auth_provider": "vault",
    "vault_path": "secret/data/cdc/cassandra"
  },
  "target_connection": {
    "host": "postgres.analytics.local",
    "port": 5432,
    "database": "warehouse",
    "schema": "public",
    "auth_provider": "vault",
    "vault_path": "database/creds/postgresql-writer"
  },
  "replication_rules": [
    {
      "source_keyspace": "warehouse",
      "source_table": "users",
      "target_schema": "public",
      "target_table": "cdc_users",
      "include_columns": ["id", "username", "email", "created_at"],
      "snapshot_mode": "initial"
    },
    {
      "source_keyspace": "warehouse",
      "source_table": "orders",
      "target_schema": "public",
      "target_table": "cdc_orders",
      "snapshot_mode": "initial"
    }
  ],
  "transformation_rules": [
    {
      "rule_name": "normalize_timestamps",
      "rule_type": "CAST",
      "source_column": "created_at",
      "target_column": "created_at",
      "transformation": "CAST(created_at AS TIMESTAMPTZ)"
    }
  ],
  "performance_tuning": {
    "max_batch_size": 1000,
    "max_queue_size": 8192,
    "poll_interval_ms": 1000,
    "connection_pool_size": 20,
    "consumer_threads": 4
  },
  "error_handling": {
    "max_retries": 10,
    "retry_backoff_ms": 3000,
    "retry_backoff_multiplier": 2.0,
    "max_retry_backoff_ms": 60000,
    "circuit_breaker_failure_threshold": 5,
    "circuit_breaker_timeout_ms": 60000,
    "dlq_enabled": true
  },
  "monitoring": {
    "metrics_enabled": true,
    "metrics_port": 9090,
    "log_level": "INFO",
    "trace_sampling_rate": 0.1,
    "health_check_interval_ms": 30000
  },
  "created_at": "2025-11-20T07:00:00Z",
  "updated_at": "2025-11-20T07:00:00Z",
  "created_by": "admin",
  "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

**Storage**:
- YAML/JSON files in `config/` directory (version controlled)
- PostgreSQL `_cdc_configurations` table (runtime retrieval)
- Environment-specific overrides via environment variables

**Configuration Validation**:
```python
from pydantic import BaseModel, Field, validator

class ReplicationRule(BaseModel):
    source_keyspace: str = Field(..., max_length=48)
    source_table: str = Field(..., max_length=48)
    target_schema: str = Field(..., max_length=48)
    target_table: str = Field(..., max_length=48)
    snapshot_mode: str = Field(..., regex="^(initial|never|schema_only)$")

class Configuration(BaseModel):
    config_name: str = Field(..., max_length=100)
    enabled: bool = True
    replication_rules: list[ReplicationRule]

    @validator('replication_rules')
    def validate_rules(cls, rules):
        if len(rules) == 0:
            raise ValueError("At least one replication rule required")
        table_pairs = [(r.source_table, r.target_table) for r in rules]
        if len(table_pairs) != len(set(table_pairs)):
            raise ValueError("Duplicate replication rules detected")
        return rules
```

---

## Entity Relationships Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Configuration                             │
│  - config_id (PK)                                                │
│  - replication_rules (defines what to capture)                   │
│  - transformation_rules (defines how to transform)               │
└────────────────────┬────────────────────────────────────────────┘
                     │ determines
                     │ replication scope
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Change Event                               │
│  - event_id (PK)                                                 │
│  - source_table, operation_type                                  │
│  - before_values, after_values                                   │
│  - schema_version (FK to Schema Metadata)                        │
│  - trace_id (for distributed tracing)                            │
└──┬────────────────────┬──────────────────────┬──────────────────┘
   │                    │                      │
   │ processed by       │ references           │ fails to process
   │                    │                      │
   ▼                    ▼                      ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐
│  Checkpoint  │  │Schema        │  │  Dead Letter Queue       │
│              │  │Metadata      │  │  Record                  │
│- checkpoint_id│  │              │  │  - dlq_id (PK)           │
│- source_table │  │- schema_id   │  │  - original_event (JSON) │
│- last_event_id│  │- version     │  │  - error_type, error_msg │
│- kafka_offset │  │- columns     │  │  - retry_count           │
│- status       │  │- avro_schema │  │  - resolution_status     │
└──────────────┘  │- effective_from│  └──────────────────────────┘
                  │- effective_to │
                  └──────┬─────────┘
                         │ version history
                         │ (self-referencing)
                         ▼
                  ┌──────────────┐
                  │Schema        │
                  │Metadata v2   │
                  └──────────────┘
```

**Cardinality**:
- One Configuration → Many Change Events (1:N)
- One Schema Metadata → Many Change Events (1:N)
- One Change Event → One Checkpoint (N:1, grouped by partition)
- One Change Event → Zero or One DLQ Record (1:0..1)
- One Schema Metadata → One Previous Schema Metadata (1:0..1, version chain)

---

## Type Mapping: Cassandra → PostgreSQL

| Cassandra Type | PostgreSQL Type | Notes |
|----------------|-----------------|-------|
| `text`, `varchar` | `VARCHAR`, `TEXT` | UTF-8 encoding |
| `int` | `INTEGER` | 32-bit signed |
| `bigint` | `BIGINT` | 64-bit signed |
| `smallint` | `SMALLINT` | 16-bit signed |
| `tinyint` | `SMALLINT` | No direct equivalent, use SMALLINT |
| `float` | `REAL` | 32-bit floating point |
| `double` | `DOUBLE PRECISION` | 64-bit floating point |
| `decimal` | `NUMERIC` | Arbitrary precision |
| `boolean` | `BOOLEAN` | True/false |
| `uuid` | `UUID` | Native UUID type |
| `timestamp` | `TIMESTAMPTZ` | With timezone recommended |
| `date` | `DATE` | Calendar date |
| `time` | `TIME` | Time of day |
| `blob` | `BYTEA` | Binary data |
| `inet` | `INET` | IP address |
| `list<T>` | `T[]` (PostgreSQL ARRAY) | Array for all types; if T is primitive (int, text, etc.) use native array, if T is complex use JSONB[] |
| `set<T>` | `T[]` (PostgreSQL ARRAY) | Convert to array; note PostgreSQL arrays allow duplicates, so enforce uniqueness via CHECK constraint if required |
| `map<K,V>` | `JSONB` | Convert to JSONB object with key-value pairs |
| `tuple<T1,T2,...>` | `JSONB` or composite type | JSONB for flexibility |
| `UDT` (User Defined Type) | `JSONB` or composite type | JSONB recommended for schema evolution |
| `counter` | `BIGINT` | Cannot use auto-increment |

---

## Out-of-Order Event Handling & Conflict Resolution

**Problem**: Due to network delays or Cassandra replication lag, events may arrive out-of-order (older event arrives after newer event).

**Strategy**: **Last Write Wins (LWW)** based on event timestamps

**Resolution Algorithm**:
1. Compare incoming event's `timestamp_micros` with existing record's `updated_at` timestamp in PostgreSQL
2. If incoming `timestamp_micros` > existing `updated_at`: Accept event (newer write)
3. If incoming `timestamp_micros` < existing `updated_at`: Reject event (stale write)
4. If incoming `timestamp_micros` == existing `updated_at`: Use `event_id` lexicographic comparison as tiebreaker (higher event_id wins)

**Implementation**: Custom Kafka Connect Single Message Transform (SMT) in `src/connectors/transforms/timestamp_conflict_resolver.py`

**Example**:
```
Event A: timestamp_micros=1000, event_id="aaa-111", value="Alice"
Event B: timestamp_micros=500, event_id="bbb-222", value="Bob"

Scenario 1: Event A arrives first, then Event B
- Event A writes to PostgreSQL: updated_at=1000, value="Alice"
- Event B rejected (500 < 1000): value remains "Alice"

Scenario 2: Event B arrives first, then Event A
- Event B writes to PostgreSQL: updated_at=500, value="Bob"
- Event A accepted (1000 > 500): value updated to "Alice"

Scenario 3: Same timestamp
- Event A: timestamp_micros=1000, event_id="aaa-111"
- Event C: timestamp_micros=1000, event_id="zzz-999"
- Event C wins ("zzz-999" > "aaa-111" lexicographically)
```

**Metrics**: Track `cdc_out_of_order_events_total` counter and `cdc_conflict_resolution_rejections_total` counter

---

## Data Validation Rules

### Change Event Validation
- `event_id` must be unique across all events
- `timestamp_micros` must not be in the future (allow 1-minute clock skew)
- For UPDATE: `before_values` and `after_values` must both be present
- For INSERT: Only `after_values` required
- For DELETE: Only `before_values` required (or tombstone flag)
- `column_types` must match `schema_version` definition
- Out-of-order events validated using Last Write Wins algorithm (see above)

### Checkpoint Validation
- `last_processed_timestamp_micros` must be ≤ current time
- `kafka_offset` must be non-decreasing for same partition
- `events_processed_count` must be non-negative and non-decreasing
- Checkpoint for partition X must not exist in multiple states simultaneously

### Schema Metadata Validation
- `version` must be unique per (keyspace, table)
- `version` must increment by 1 from previous version
- `effective_from` of version N+1 must equal `effective_to` of version N
- `avro_schema` must pass Avro schema validator
- Column types must be valid Cassandra types
- Primary key must include at least one partition key

### DLQ Record Validation
- `original_event` must deserialize to valid Change Event
- `retry_count` must be ≥ 0
- `first_failed_at` ≤ `last_retry_at` ≤ `dlq_timestamp`
- If `resolution_status` = RESOLVED, then `resolved_at` and `resolved_by` must be set

### Configuration Validation
- At least one replication rule required
- No duplicate (source_table, target_table) pairs
- Connection parameters must include required fields (host, port, auth)
- Batch sizes must be between 1 and 10,000
- Retry intervals must be positive
- Circuit breaker thresholds must be ≥ 1

---

## Storage Considerations

### PostgreSQL Control Tables

```sql
-- Schema metadata storage
CREATE TABLE _cdc_schema_metadata (
    schema_id UUID PRIMARY KEY,
    source_keyspace VARCHAR(48) NOT NULL,
    source_table VARCHAR(48) NOT NULL,
    version INTEGER NOT NULL,
    columns JSONB NOT NULL,
    primary_key JSONB NOT NULL,
    avro_schema JSONB NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    UNIQUE (source_keyspace, source_table, version)
);
CREATE INDEX idx_schema_table_effective ON _cdc_schema_metadata (source_table, effective_from);

-- Checkpoint storage (optional, if not using Kafka offsets)
CREATE TABLE _cdc_checkpoints (
    checkpoint_id UUID PRIMARY KEY,
    source_table VARCHAR(100) NOT NULL,
    partition_key_hash VARCHAR(64) NOT NULL,
    last_processed_timestamp_micros BIGINT NOT NULL,
    checkpoint_timestamp TIMESTAMPTZ NOT NULL,
    kafka_offset BIGINT,
    kafka_partition INTEGER,
    status VARCHAR(20) NOT NULL,
    UNIQUE (source_table, partition_key_hash)
);
CREATE INDEX idx_checkpoint_table_status ON _cdc_checkpoints (source_table, status);

-- DLQ record storage (for querying/reporting)
CREATE TABLE _cdc_dlq_records (
    dlq_id UUID PRIMARY KEY,
    original_event JSONB NOT NULL,
    error_type VARCHAR(50) NOT NULL,
    error_message TEXT NOT NULL,
    first_failed_at TIMESTAMPTZ NOT NULL,
    dlq_timestamp TIMESTAMPTZ NOT NULL,
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'UNRESOLVED',
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(100)
);
CREATE INDEX idx_dlq_status_timestamp ON _cdc_dlq_records (resolution_status, dlq_timestamp DESC);
CREATE INDEX idx_dlq_error_type ON _cdc_dlq_records (error_type);

-- Configuration storage
CREATE TABLE _cdc_configurations (
    config_id UUID PRIMARY KEY,
    config_name VARCHAR(100) UNIQUE NOT NULL,
    version INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    config_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_config_name_enabled ON _cdc_configurations (config_name, enabled);
```

### Kafka Topics

| Topic Name | Partitions | Replication Factor | Retention | Purpose |
|------------|------------|-------------------|-----------|---------|
| `cdc-events-{table}` | 8 | 3 | 7 days | Main event stream per table |
| `dlq-events` | 1 | 3 | 30 days | Failed events for manual review |
| `schema-changes` | 1 | 3 | 365 days | Schema evolution audit log |
| `connect-offsets` | 25 | 3 | Compact | Kafka Connect checkpoint storage |
| `connect-configs` | 1 | 3 | Compact | Connector configurations |
| `connect-status` | 5 | 3 | Compact | Connector health status |

---

## Data Retention Policies

| Entity | Retention Period | Rationale |
|--------|------------------|-----------|
| Change Event (Kafka) | 7 days | Replayable window for recovery |
| Checkpoint | Until superseded | Keep only latest checkpoint per partition |
| Schema Metadata | Forever | Historical schema needed for auditing |
| DLQ Record | 90 days | Manual review window |
| Configuration | Forever (soft delete) | Audit trail of pipeline changes |

**Cleanup Jobs**:
- Kafka log compaction: Automatic, based on retention policy
- PostgreSQL DLQ: Weekly job to archive RESOLVED records older than 90 days
- Checkpoint: Automatic overwrite, no cleanup needed

---

## Summary

This data model provides:
- **Traceability**: Every event tracked from capture to load (or failure)
- **Resumability**: Checkpoints enable crash recovery without data loss
- **Schema Evolution**: Complete version history for backward compatibility
- **Error Isolation**: DLQ prevents bad events from blocking pipeline
- **Configuration as Code**: Declarative, version-controlled pipeline definitions
- **Observability**: Trace IDs and metadata enable full pipeline debugging

All entities support the constitution requirements for exactly-once delivery, 99.9% uptime, comprehensive observability, and enterprise-grade error handling.
