# Kafka Topics Contract

**Feature**: 001-cass-cdc-pg
**Date**: 2025-11-20
**Status**: Approved

## Overview

This document defines the Kafka topic schemas, message formats, and contracts for the CDC pipeline. All topics use Avro serialization with schemas registered in Confluent Schema Registry.

## Topic Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Kafka Topics Architecture                     │
└─────────────────────────────────────────────────────────────────┘

Debezium Source               Topic per Table            JDBC Sink
┌─────────────┐              ┌─────────────────┐       ┌──────────┐
│ Cassandra   │─────────────▶│ cdc-events-users│──────▶│PostgreSQL│
│ CDC Reader  │              ├─────────────────┤       │ Writer   │
│             │─────────────▶│ cdc-events-orders│─────▶│          │
└─────────────┘              └─────────────────┘       └──────────┘
      │                              │
      │ schema changes               │ failures
      ▼                              ▼
┌──────────────────┐         ┌─────────────────┐
│ schema-changes   │         │ dlq-events      │
│ (audit log)      │         │ (dead letter)   │
└──────────────────┘         └─────────────────┘

         Internal Kafka Connect Topics
         ┌─────────────────────────────┐
         │ connect-offsets (checkpoints)│
         │ connect-configs (connectors) │
         │ connect-status  (health)     │
         └─────────────────────────────┘
```

## Topic Definitions

### 1. CDC Event Topics: `cdc-events-{table_name}`

**Purpose**: Main data stream carrying change events from Cassandra to PostgreSQL

**Naming Convention**: `cdc-events-{source_table_name}`
- Example: `cdc-events-users`, `cdc-events-orders`

**Configuration**:
```properties
partitions=8
replication.factor=3
min.insync.replicas=2
retention.ms=604800000  # 7 days
cleanup.policy=delete
compression.type=snappy
segment.ms=3600000  # 1 hour
```

**Partitioning Strategy**: Hash of Cassandra partition key
- Ensures order preservation per partition key
- Enables parallel processing across partitions
- Partition key extracted from Change Event `partition_key` field

**Message Format**:
- **Key**: Avro-serialized record containing partition key
- **Value**: Avro-serialized Change Event (includes before/after values)
- **Headers**:
  - `schema_version`: Integer (Schema Registry schema ID)
  - `trace_id`: String (distributed tracing correlation ID)
  - `source_timestamp_micros`: Long (Cassandra write timestamp)

**Avro Schema** (Key):
```json
{
  "type": "record",
  "name": "ChangeEventKey",
  "namespace": "com.cdc.kafka",
  "doc": "Partition key for CDC event routing",
  "fields": [
    {
      "name": "partition_key",
      "type": "string",
      "doc": "Cassandra partition key value(s) as JSON"
    }
  ]
}
```

**Avro Schema** (Value - Generic):
```json
{
  "type": "record",
  "name": "ChangeEvent",
  "namespace": "com.cdc.kafka",
  "doc": "CDC change event from Cassandra",
  "fields": [
    {
      "name": "event_id",
      "type": "string",
      "doc": "Unique event identifier (UUID)"
    },
    {
      "name": "source",
      "type": {
        "type": "record",
        "name": "Source",
        "fields": [
          {"name": "keyspace", "type": "string"},
          {"name": "table", "type": "string"},
          {"name": "cluster", "type": ["null", "string"], "default": null}
        ]
      },
      "doc": "Source metadata"
    },
    {
      "name": "operation",
      "type": {
        "type": "enum",
        "name": "Operation",
        "symbols": ["CREATE", "UPDATE", "DELETE", "TRUNCATE"]
      },
      "doc": "Type of change operation"
    },
    {
      "name": "timestamp_micros",
      "type": "long",
      "doc": "Event timestamp in microseconds since epoch"
    },
    {
      "name": "before",
      "type": [
        "null",
        {
          "type": "map",
          "values": ["null", "string", "long", "double", "boolean"]
        }
      ],
      "default": null,
      "doc": "Column values before change (for UPDATE/DELETE)"
    },
    {
      "name": "after",
      "type": [
        "null",
        {
          "type": "map",
          "values": ["null", "string", "long", "double", "boolean"]
        }
      ],
      "default": null,
      "doc": "Column values after change (for CREATE/UPDATE)"
    },
    {
      "name": "schema_version",
      "type": "int",
      "doc": "Schema version at capture time"
    },
    {
      "name": "ttl_seconds",
      "type": ["null", "int"],
      "default": null,
      "doc": "Cassandra TTL if applicable"
    }
  ]
}
```

**Avro Schema** (Value - Table-Specific Example for `users`):
```json
{
  "type": "record",
  "name": "users",
  "namespace": "warehouse",
  "doc": "CDC events for warehouse.users table",
  "fields": [
    {
      "name": "id",
      "type": "string",
      "doc": "User ID (partition key)"
    },
    {
      "name": "username",
      "type": "string",
      "doc": "Username"
    },
    {
      "name": "email",
      "type": ["null", "string"],
      "default": null,
      "doc": "Email address"
    },
    {
      "name": "created_at",
      "type": {
        "type": "long",
        "logicalType": "timestamp-millis"
      },
      "doc": "Account creation timestamp"
    },
    {
      "name": "updated_at",
      "type": {
        "type": "long",
        "logicalType": "timestamp-millis"
      },
      "doc": "Last update timestamp"
    },
    {
      "name": "__op",
      "type": {
        "type": "enum",
        "name": "OperationType",
        "symbols": ["c", "u", "d", "r"]
      },
      "doc": "Operation: c=create, u=update, d=delete, r=read (snapshot)"
    },
    {
      "name": "__source_ts_ms",
      "type": "long",
      "doc": "Source system timestamp in milliseconds"
    },
    {
      "name": "__deleted",
      "type": ["null", "boolean"],
      "default": null,
      "doc": "True if this is a delete/tombstone event"
    }
  ]
}
```

**Example Message** (JSON representation for documentation):
```json
{
  "key": {
    "partition_key": "{\"id\":\"user-12345\"}"
  },
  "value": {
    "event_id": "550e8400-e29b-41d4-a716-446655440000",
    "source": {
      "keyspace": "warehouse",
      "table": "users",
      "cluster": "cdc-cluster"
    },
    "operation": "UPDATE",
    "timestamp_micros": 1732092300000000,
    "before": {
      "id": "user-12345",
      "username": "john_doe",
      "email": "john@example.com",
      "created_at": 1705315800000,
      "updated_at": 1718890920000
    },
    "after": {
      "id": "user-12345",
      "username": "john_doe",
      "email": "john.doe@example.com",
      "created_at": 1705315800000,
      "updated_at": 1732092300000
    },
    "schema_version": 3,
    "ttl_seconds": null
  },
  "headers": {
    "schema_version": "3",
    "trace_id": "a1b2c3d4e5f6789012345678abcdef90",
    "source_timestamp_micros": "1732092300000000"
  }
}
```

**Consumer Contract**:
- Consumers MUST handle all operation types (CREATE, UPDATE, DELETE, TRUNCATE)
- Consumers MUST use `before` for DELETE operations
- Consumers MUST use `after` for CREATE/UPDATE operations
- Consumers MUST respect message order within a partition
- Consumers MUST commit offsets only after successful processing
- Consumers MUST handle schema evolution (check `schema_version`)

---

### 2. Dead Letter Queue Topic: `dlq-events`

**Purpose**: Store failed events that could not be processed after exhausting retries

**Configuration**:
```properties
partitions=1  # Single partition for ordered failure processing
replication.factor=3
min.insync.replicas=2
retention.ms=2592000000  # 30 days
cleanup.policy=delete
compression.type=gzip  # Higher compression for infrequent access
```

**Message Format**:
- **Key**: Original event key (maintains partitioning info)
- **Value**: DLQ Record with error context
- **Headers**:
  - `original_topic`: String (source topic name)
  - `original_partition`: Integer
  - `original_offset`: Long
  - `error_type`: String
  - `retry_count`: Integer

**Avro Schema** (Value):
```json
{
  "type": "record",
  "name": "DLQRecord",
  "namespace": "com.cdc.kafka",
  "doc": "Dead letter queue record for failed events",
  "fields": [
    {
      "name": "dlq_id",
      "type": "string",
      "doc": "Unique DLQ entry identifier (UUID)"
    },
    {
      "name": "original_event",
      "type": "bytes",
      "doc": "Original event serialized as bytes (Avro or JSON)"
    },
    {
      "name": "error_type",
      "type": {
        "type": "enum",
        "name": "ErrorType",
        "symbols": [
          "SCHEMA_MISMATCH",
          "TYPE_CONVERSION_ERROR",
          "CONSTRAINT_VIOLATION",
          "NETWORK_TIMEOUT",
          "UNKNOWN"
        ]
      },
      "doc": "Category of error"
    },
    {
      "name": "error_message",
      "type": "string",
      "doc": "Detailed error description"
    },
    {
      "name": "error_stack_trace",
      "type": ["null", "string"],
      "default": null,
      "doc": "Full exception stack trace"
    },
    {
      "name": "retry_count",
      "type": "int",
      "doc": "Number of retry attempts before DLQ"
    },
    {
      "name": "first_failed_at",
      "type": {
        "type": "long",
        "logicalType": "timestamp-millis"
      },
      "doc": "When error first occurred"
    },
    {
      "name": "last_retry_at",
      "type": {
        "type": "long",
        "logicalType": "timestamp-millis"
      },
      "doc": "Most recent retry attempt"
    },
    {
      "name": "dlq_timestamp",
      "type": {
        "type": "long",
        "logicalType": "timestamp-millis"
      },
      "doc": "When event was moved to DLQ"
    },
    {
      "name": "source_component",
      "type": {
        "type": "enum",
        "name": "SourceComponent",
        "symbols": ["SOURCE_CONNECTOR", "TRANSFORM", "SINK_CONNECTOR"]
      },
      "doc": "Which component generated the error"
    }
  ]
}
```

**Example Message**:
```json
{
  "key": {
    "partition_key": "{\"id\":\"user-999\"}"
  },
  "value": {
    "dlq_id": "990fc833-26df-75h8-e159-88aa99882444",
    "original_event": "<base64-encoded-bytes>",
    "error_type": "TYPE_CONVERSION_ERROR",
    "error_message": "Failed to convert column 'age' value 'not-a-number' to PostgreSQL type INTEGER",
    "error_stack_trace": "Traceback (most recent call last):\\n  File \"sink.py\", line 123...",
    "retry_count": 10,
    "first_failed_at": 1732090200000,
    "last_retry_at": 1732090500000,
    "dlq_timestamp": 1732090505000,
    "source_component": "SINK_CONNECTOR"
  },
  "headers": {
    "original_topic": "cdc-events-users",
    "original_partition": "3",
    "original_offset": "127456",
    "error_type": "TYPE_CONVERSION_ERROR",
    "retry_count": "10"
  }
}
```

**Consumer Contract** (DLQ Replay Service):
- Read events from DLQ for manual review
- Support filtered reads by `error_type` or time range
- Replay events to original topic after resolution
- Update `_cdc_dlq_records` table with resolution status

---

### 3. Schema Changes Topic: `schema-changes`

**Purpose**: Audit log of schema evolution events for compliance and debugging

**Configuration**:
```properties
partitions=1  # Single partition for ordered schema history
replication.factor=3
min.insync.replicas=2
retention.ms=31536000000  # 365 days
cleanup.policy=delete
compression.type=gzip
```

**Message Format**:
- **Key**: Table name (keyspace.table)
- **Value**: Schema change event

**Avro Schema** (Value):
```json
{
  "type": "record",
  "name": "SchemaChange",
  "namespace": "com.cdc.kafka",
  "doc": "Schema evolution event",
  "fields": [
    {
      "name": "schema_id",
      "type": "string",
      "doc": "Unique schema version identifier (UUID)"
    },
    {
      "name": "keyspace",
      "type": "string",
      "doc": "Cassandra keyspace"
    },
    {
      "name": "table",
      "type": "string",
      "doc": "Cassandra table"
    },
    {
      "name": "version",
      "type": "int",
      "doc": "Sequential schema version number"
    },
    {
      "name": "change_type",
      "type": {
        "type": "enum",
        "name": "ChangeType",
        "symbols": [
          "TABLE_CREATED",
          "TABLE_DROPPED",
          "COLUMN_ADDED",
          "COLUMN_DROPPED",
          "COLUMN_RENAMED",
          "TYPE_CHANGED",
          "INDEX_ADDED",
          "INDEX_DROPPED"
        ]
      },
      "doc": "Type of schema change"
    },
    {
      "name": "change_details",
      "type": {
        "type": "map",
        "values": "string"
      },
      "doc": "Details about the change (column names, types, etc.)"
    },
    {
      "name": "avro_schema",
      "type": "string",
      "doc": "Complete Avro schema as JSON string"
    },
    {
      "name": "avro_schema_id",
      "type": ["null", "int"],
      "default": null,
      "doc": "Schema Registry schema ID"
    },
    {
      "name": "compatibility_mode",
      "type": {
        "type": "enum",
        "name": "CompatibilityMode",
        "symbols": ["BACKWARD", "FORWARD", "FULL", "NONE"]
      },
      "doc": "Schema compatibility mode"
    },
    {
      "name": "effective_from",
      "type": {
        "type": "long",
        "logicalType": "timestamp-millis"
      },
      "doc": "When this schema version became active"
    },
    {
      "name": "detected_by",
      "type": {
        "type": "enum",
        "name": "DetectionSource",
        "symbols": ["DEBEZIUM_CONNECTOR", "SCHEMA_MONITOR", "MANUAL"]
      },
      "doc": "How schema change was detected"
    }
  ]
}
```

**Example Message**:
```json
{
  "key": "warehouse.users",
  "value": {
    "schema_id": "880fb722-15ce-64g7-d048-779988771333",
    "keyspace": "warehouse",
    "table": "users",
    "version": 3,
    "change_type": "COLUMN_ADDED",
    "change_details": {
      "column_name": "phone_number",
      "column_type": "text",
      "nullable": "true",
      "position": "3"
    },
    "avro_schema": "{\"type\":\"record\",\"name\":\"users\",\"fields\":[...]}",
    "avro_schema_id": 3,
    "compatibility_mode": "BACKWARD",
    "effective_from": 1732089600000,
    "detected_by": "DEBEZIUM_CONNECTOR"
  }
}
```

**Consumer Contract**:
- Schema changes are informational (no action required)
- Used for auditing and debugging schema evolution issues
- Can trigger alerts for breaking changes

---

### 4. Internal Kafka Connect Topics

#### `connect-offsets`
**Purpose**: Store Kafka Connect consumer offsets (checkpoints)

**Configuration**:
```properties
partitions=25
replication.factor=3
cleanup.policy=compact  # Keep only latest offset per key
min.compaction.lag.ms=60000
segment.ms=3600000
```

**Key**: `["connect-cluster", {"connector": "cassandra-source"}]` (JSON array)
**Value**: Offset data (Kafka Connect internal format)

**Notes**:
- Managed automatically by Kafka Connect
- Do not manually produce/consume
- Used for exactly-once delivery semantics

---

#### `connect-configs`
**Purpose**: Store Kafka Connect connector configurations

**Configuration**:
```properties
partitions=1
replication.factor=3
cleanup.policy=compact
```

**Key**: Connector name (e.g., `cassandra-source-connector`)
**Value**: JSON configuration

**Notes**:
- Managed by Kafka Connect REST API
- Used for connector distribution across workers

---

#### `connect-status`
**Purpose**: Store Kafka Connect connector and task status

**Configuration**:
```properties
partitions=5
replication.factor=3
cleanup.policy=compact
```

**Key**: Connector or task identifier
**Value**: Status information (RUNNING, FAILED, PAUSED)

**Notes**:
- Used for health monitoring
- Consumed by Kafka Connect UI and monitoring tools

---

## Topic Monitoring Metrics

### Key Metrics per Topic

| Metric | Description | Threshold |
|--------|-------------|-----------|
| `kafka_log_size` | Total topic size in bytes | < 10GB |
| `kafka_partition_current_offset` | Latest offset per partition | Monotonically increasing |
| `kafka_consumer_lag` | Events waiting to be processed | < 10,000 events |
| `kafka_messages_in_per_sec` | Incoming message rate | 1,000-50,000 msgs/sec |
| `kafka_bytes_in_per_sec` | Incoming data rate | < 100 MB/sec |
| `kafka_under_replicated_partitions` | Partitions below min ISR | = 0 |

### Alerting Rules

```yaml
# Prometheus alerting rules
groups:
  - name: kafka_cdc_topics
    interval: 30s
    rules:
      - alert: HighConsumerLag
        expr: kafka_consumer_lag{topic=~"cdc-events-.*"} > 10000
        for: 5m
        annotations:
          summary: "High consumer lag on {{ $labels.topic }}"
          description: "Consumer lag is {{ $value }} events"

      - alert: UnderReplicatedPartitions
        expr: kafka_under_replicated_partitions > 0
        for: 1m
        annotations:
          summary: "Under-replicated partitions detected"

      - alert: DLQEventsAccumulating
        expr: rate(kafka_messages_in_per_sec{topic="dlq-events"}[5m]) > 10
        for: 5m
        annotations:
          summary: "High rate of DLQ events"
          description: "{{ $value }} DLQ events per second"
```

---

## Schema Evolution Compatibility

### Allowed Changes (BACKWARD Compatible)

| Change | Example | Impact |
|--------|---------|--------|
| Add optional field with default | Add `phone_number TEXT NULL` | Old consumers ignore new field |
| Remove field | Remove `middle_name` | New consumers ignore field in old messages |

### Forbidden Changes (BREAKING)

| Change | Example | Why Breaking |
|--------|---------|--------------|
| Rename field | `email` → `email_address` | Consumers cannot find field |
| Change field type | `age INT` → `age TEXT` | Type mismatch errors |
| Add required field without default | Add `tax_id TEXT NOT NULL` | Old messages missing field |
| Remove enum symbol | Remove `Operation.TRUNCATE` | Consumers cannot deserialize |

### Schema Registry Compatibility Check

```bash
# Register new schema version
curl -X POST http://localhost:8081/subjects/cdc-events-users-value/versions \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  -d '{"schema": "..."}'

# Check compatibility before registering
curl -X POST http://localhost:8081/compatibility/subjects/cdc-events-users-value/versions/latest \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  -d '{"schema": "..."}'

# Response: {"is_compatible": true}
```

---

## Topic Creation Scripts

### Terraform Configuration

```hcl
resource "kafka_topic" "cdc_events_users" {
  name               = "cdc-events-users"
  partitions         = 8
  replication_factor = 3
  config = {
    "retention.ms"           = "604800000"
    "compression.type"       = "snappy"
    "min.insync.replicas"    = "2"
    "cleanup.policy"         = "delete"
    "segment.ms"             = "3600000"
  }
}

resource "kafka_topic" "dlq_events" {
  name               = "dlq-events"
  partitions         = 1
  replication_factor = 3
  config = {
    "retention.ms"           = "2592000000"
    "compression.type"       = "gzip"
    "min.insync.replicas"    = "2"
    "cleanup.policy"         = "delete"
  }
}
```

### Bash Script (for local development)

```bash
#!/bin/bash
# create-topics.sh

KAFKA_BROKER="localhost:9092"

# Create CDC event topics (one per table)
for table in users orders products; do
  kafka-topics --create \
    --bootstrap-server $KAFKA_BROKER \
    --topic cdc-events-$table \
    --partitions 8 \
    --replication-factor 1 \
    --config retention.ms=604800000 \
    --config compression.type=snappy \
    --if-not-exists
done

# Create DLQ topic
kafka-topics --create \
  --bootstrap-server $KAFKA_BROKER \
  --topic dlq-events \
  --partitions 1 \
  --replication-factor 1 \
  --config retention.ms=2592000000 \
  --config compression.type=gzip \
  --if-not-exists

# Create schema changes topic
kafka-topics --create \
  --bootstrap-server $KAFKA_BROKER \
  --topic schema-changes \
  --partitions 1 \
  --replication-factor 1 \
  --config retention.ms=31536000000 \
  --config compression.type=gzip \
  --if-not-exists

echo "Topics created successfully"
kafka-topics --list --bootstrap-server $KAFKA_BROKER
```

---

## Testing Contracts

### Producer Test (Validate Schema)

```python
from confluent_kafka import avro
from confluent_kafka.avro import AvroProducer

# Load schema
value_schema = avro.load('schemas/change_event.avsc')
key_schema = avro.load('schemas/change_event_key.avsc')

# Create producer
producer = AvroProducer({
    'bootstrap.servers': 'localhost:9092',
    'schema.registry.url': 'http://localhost:8081'
}, default_key_schema=key_schema, default_value_schema=value_schema)

# Produce test message
producer.produce(
    topic='cdc-events-users',
    key={'partition_key': '{"id":"test-123"}'},
    value={
        'event_id': 'test-event-001',
        'source': {'keyspace': 'warehouse', 'table': 'users'},
        'operation': 'CREATE',
        'timestamp_micros': 1732092300000000,
        'after': {'id': 'test-123', 'username': 'testuser'},
        'schema_version': 1,
    }
)
producer.flush()
```

### Consumer Test (Validate Consumption)

```python
from confluent_kafka.avro import AvroConsumer

consumer = AvroConsumer({
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'test-consumer',
    'schema.registry.url': 'http://localhost:8081',
    'auto.offset.reset': 'earliest'
})

consumer.subscribe(['cdc-events-users'])

msg = consumer.poll(10.0)
if msg:
    print(f"Key: {msg.key()}")
    print(f"Value: {msg.value()}")
    assert msg.value()['operation'] in ['CREATE', 'UPDATE', 'DELETE']
    consumer.commit()
```

### Contract Test (pytest)

```python
import pytest
from testcontainers.kafka import KafkaContainer
from testcontainers.compose import DockerCompose

def test_cdc_event_schema_compatibility():
    """Test that CDC events conform to Avro schema"""
    with DockerCompose("docker") as compose:
        # Start Kafka + Schema Registry
        compose.wait_for("http://localhost:8081")

        # Register schema
        schema_registry = SchemaRegistry('http://localhost:8081')
        schema_id = schema_registry.register('cdc-events-users-value', CHANGE_EVENT_SCHEMA)

        # Produce event
        producer.produce_event(...)

        # Consume event
        event = consumer.poll()

        # Validate schema
        assert event.schema_id == schema_id
        assert all(field in event.value for field in ['event_id', 'operation', 'timestamp_micros'])
```

---

## Summary

This Kafka topics contract defines:
- **Topic structure**: Per-table event topics, DLQ, schema changes, internal topics
- **Message schemas**: Avro schemas for keys and values with backward compatibility
- **Partitioning**: Hash-based on partition key for ordering guarantees
- **Retention**: 7 days for events, 30 days for DLQ, 365 days for schema changes
- **Monitoring**: Metrics and alerts for lag, throughput, under-replication
- **Schema evolution**: Compatibility rules and validation process
- **Testing**: Contract tests for producers and consumers

All topics support the constitution requirements for exactly-once delivery, comprehensive observability, and enterprise-grade error handling.
