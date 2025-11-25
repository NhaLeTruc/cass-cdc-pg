# ADR 001: Use Debezium for Change Data Capture

## Status

**Accepted** - 2025-11-20

## Context

We need a reliable solution for capturing changes from Cassandra tables and replicating them to PostgreSQL in real-time. The solution must support:

- High throughput (≥10,000 events/second)
- Low latency (P95 ≤2 seconds end-to-end)
- Exactly-once delivery semantics
- Schema evolution
- Operational simplicity

### Options Considered

1. **Debezium Cassandra CDC Connector**
2. **Custom CDC using Cassandra CommitLog tailing**
3. **Query-based CDC with timestamps**
4. **Cassandra triggers with external queue**

## Decision

We will use **Debezium Cassandra CDC Connector** with Kafka Connect for change data capture.

## Rationale

### Why Debezium?

#### Pros ✅

1. **Industry-Proven Solution**
   - Used in production by major companies (LinkedIn, Netflix, Uber)
   - 7+ years of active development and community support
   - Well-documented edge cases and failure modes

2. **Built-in Features**
   - **Checkpoint management**: Automatic offset tracking, resume from failure
   - **Schema evolution**: Integrated with Confluent Schema Registry
   - **Exactly-once semantics**: Kafka transactions for guaranteed delivery
   - **Dead Letter Queue**: Automatic routing of failed records

3. **Operational Simplicity**
   - Declarative JSON configuration (no code)
   - REST API for management
   - Prometheus metrics out-of-the-box
   - Health checks and monitoring

4. **Ecosystem Integration**
   - Native Kafka Connect framework integration
   - Works with existing Kafka infrastructure
   - Standard SMT (Single Message Transforms) support
   - Compatible with Schema Registry

5. **Scalability**
   - Horizontal scaling via Kafka Connect workers
   - Partitioned offset storage for parallelism
   - Handles backpressure automatically

#### Cons ⚠️

1. **Limited Cassandra 4.x Support**
   - Debezium Cassandra connector is less mature than MySQL/PostgreSQL
   - Requires CDC enabled on Cassandra tables
   - Some advanced Cassandra features (UDTs, collections) require custom mapping

2. **Additional Infrastructure**
   - Requires Kafka cluster (adds complexity)
   - Requires Schema Registry for Avro serialization
   - Adds operational overhead

3. **Vendor Lock-in (Minor)**
   - Tied to Kafka ecosystem
   - Migration to other solutions would require significant effort

### Why Not Custom CDC?

#### Custom CommitLog Tailing

```
Pros: Full control, no external dependencies
Cons:
  - Reinventing the wheel
  - Complex offset management
  - No schema evolution support
  - High maintenance burden
  - Need to handle all edge cases ourselves
```

#### Query-Based CDC

```
Pros: Simple to implement
Cons:
  - Cannot capture DELETE operations
  - High database load from polling
  - Race conditions with concurrent writes
  - Cannot guarantee exactly-once delivery
  - Latency >10 seconds (unacceptable)
```

#### Cassandra Triggers

```
Pros: Real-time capture
Cons:
  - Performance impact on Cassandra writes
  - Complex trigger logic
  - No built-in checkpoint management
  - Requires external queue (back to Kafka anyway)
```

## Implementation Details

### Architecture

```
Cassandra (CDC enabled)
    ↓
Debezium Cassandra Source Connector
    ↓
Kafka Topics (cdc-events-*)
    ↓
Confluent Schema Registry (Avro schemas)
    ↓
JDBC Sink Connector
    ↓
PostgreSQL (target tables)
```

### Configuration

```json
{
  "connector.class": "io.debezium.connector.cassandra.CassandraConnector",
  "cassandra.hosts": "cassandra:9042",
  "cassandra.table.include.list": "warehouse.users,warehouse.orders",
  "kafka.topic.prefix": "cdc-events",
  "snapshot.mode": "initial",
  "tombstones.on.delete": "true"
}
```

### Trade-offs Accepted

1. **Infrastructure Complexity** vs **Feature Completeness**
   - Accept: Need to run Kafka cluster
   - Gain: Mature CDC solution with proven scalability

2. **Vendor Ecosystem** vs **Operational Simplicity**
   - Accept: Tied to Kafka ecosystem
   - Gain: Standard tooling, monitoring, and best practices

3. **Learning Curve** vs **Long-term Maintainability**
   - Accept: Team needs to learn Debezium/Kafka Connect
   - Gain: Lower maintenance burden, community support

## Consequences

### Positive

1. **Faster Time-to-Market**
   - No need to build custom CDC from scratch
   - Leverage existing Kafka infrastructure
   - Standard patterns and documentation

2. **Reduced Maintenance**
   - Bug fixes and features from Debezium community
   - Standard upgrade path
   - Well-known troubleshooting procedures

3. **Better Reliability**
   - Battle-tested in production environments
   - Handles edge cases we haven't thought of
   - Proven scalability

### Negative

1. **Infrastructure Overhead**
   - Need to maintain Kafka cluster (3+ brokers)
   - Need Schema Registry (2+ instances)
   - Increased operational complexity

2. **Resource Consumption**
   - Additional memory (Kafka: ~1GB, Kafka Connect: ~512MB per worker)
   - Additional storage (Kafka topics: 7-day retention)
   - Network bandwidth for replication

3. **Team Training**
   - Need to learn Kafka Connect concepts
   - Need to understand Debezium configuration
   - Operational runbooks required

## Mitigation Strategies

1. **Infrastructure Complexity**
   - Use managed Kafka service (Confluent Cloud, Amazon MSK) for production
   - Document standard operating procedures
   - Automate deployment with Helm charts

2. **Limited Cassandra 4.x Support**
   - Thoroughly test schema evolution scenarios
   - Implement custom SMTs for complex type mappings
   - Monitor Debezium project for Cassandra improvements

3. **Team Training**
   - Create comprehensive runbooks
   - Document common failure scenarios
   - Provide hands-on training sessions

## References

- [Debezium Architecture](https://debezium.io/documentation/reference/architecture.html)
- [Debezium Cassandra Connector](https://debezium.io/documentation/reference/connectors/cassandra.html)
- [Kafka Connect Documentation](https://docs.confluent.io/platform/current/connect/)
- [Netflix Blog: Change Data Capture with Kafka](https://netflixtechblog.com/kafka-inside-keystone-pipeline-dd5aeabaf6bb)

## Revision History

- 2025-11-20: Initial decision - Use Debezium
- 2025-11-25: Implementation complete, decision validated in production

## Related ADRs

- ADR 002: Use Kafka as Message Bus (pending)
- ADR 003: Use Confluent Schema Registry for Schema Management (pending)
- ADR 004: Use HashiCorp Vault for Secrets Management (pending)
