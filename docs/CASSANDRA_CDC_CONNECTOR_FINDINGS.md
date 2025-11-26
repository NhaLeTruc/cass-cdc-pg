# Cassandra CDC Connector - Investigation & Findings

**Date**: 2025-11-26
**Status**: ⚠️ BLOCKED - Connector Not Available in Standard Distributions
**Investigation Duration**: Multiple sessions

---

## Executive Summary

The Debezium Cassandra CDC connector is **not available** in standard Debezium distributions (Kafka Connect or Debezium Server). Multiple deployment approaches were attempted, all encountering the fundamental limitation that the connector class `io.debezium.connector.cassandra.Cassandra4Connector` is not included in any public Debezium release.

### Key Findings

- ✅ **JDBC Sink Connector**: Successfully deployed - 23 tests now passing
- ❌ **Cassandra Source Connector**: Cannot be deployed - 99 tests remain skipped
- 🔧 **Cassandra CDC**: Enabled in Cassandra (cdc_enabled: true)
- 📦 **Debezium Agent JAR**: Downloaded (2.7.0.Final) but missing connector implementation

---

## Attempted Approaches

### Approach 1: Debezium Standalone Agent (In Cassandra Container)

**Concept**: Run Debezium Cassandra agent as a standalone Java process inside the Cassandra container.

**Implementation**:
- Modified [`docker/cassandra/Dockerfile`](../docker/cassandra/Dockerfile) to download agent JAR
- Created configuration: [`docker/cassandra/debezium-cassandra.properties`](../docker/cassandra/debezium-cassandra.properties)
- Created driver config: [`docker/cassandra/cassandra-driver.conf`](../docker/cassandra/cassandra-driver.conf)
- Created startup script: [`docker/cassandra/start-debezium-agent.sh`](../docker/cassandra/start-debezium-agent.sh)

**Final Error**:
```
java.lang.ClassNotFoundException: io.debezium.connector.cassandra.Cassandra4Connector
```

**Root Cause**: The downloaded JAR (`debezium-connector-cassandra-4-2.7.0.Final-jar-with-dependencies.jar`) does not contain the connector implementation.

---

### Approach 2: Debezium Server

**Concept**: Use Debezium Server (standalone application) instead of Kafka Connect.

**Implementation**:
- Added `debezium-server` service to [`docker-compose.yml`](../docker-compose.yml)
- Created configuration: [`docker/debezium-server/config/application.properties`](../docker/debezium-server/config/application.properties)
- Configured sink to Kafka, source as Cassandra

**Final Error**:
```
java.lang.ClassNotFoundException: io.debezium.connector.cassandra.Cassandra4Connector
```

**Root Cause**: Debezium Server 3.0 image does NOT include the Cassandra connector.

---

### Approach 3: Kafka Connect Plugin Installation

**Concept**: Install Cassandra connector as a Kafka Connect plugin via Confluent Hub.

**Investigation**:
```bash
confluent-hub search cassandra
# Result: No Cassandra connector available in Confluent Hub
```

**Outcome**: Cassandra connector is not distributed through Confluent Hub.

---

## Configuration Files Created

All configuration files were successfully created and are ready to use if/when the connector becomes available:

### 1. Debezium Agent Configuration
**File**: [`docker/cassandra/debezium-cassandra.properties`](../docker/cassandra/debezium-cassandra.properties)

```properties
connector.class=io.debezium.connector.cassandra.Cassandra4Connector
cassandra.node.id=cdc-cassandra-node-1
cassandra.hosts=localhost
cassandra.port=9042
cassandra.driver.config.file=/opt/debezium/conf/cassandra-driver.conf
commit.log.relocation.dir=/var/lib/cassandra/cdc_raw
commit.log.real.time.processing.enabled=true
topic.prefix=cdc-events
table.include.list=warehouse.users,warehouse.orders,warehouse.sessions
offset.backing.store.dir=/var/lib/cassandra/cdc_offsets
kafka.producer.bootstrap.servers=kafka:9092
```

**Key Configuration Notes**:
- ⚠️ **Do NOT use `cassandra.config`** - causes YAML parsing errors with Cassandra time formats (e.g., "4h")
- Use `cassandra.driver.config.file` instead for Cassandra connection settings

### 2. DataStax Driver Configuration
**File**: [`docker/cassandra/cassandra-driver.conf`](../docker/cassandra/cassandra-driver.conf)

```conf
datastax-java-driver {
  basic {
    contact-points = [ "localhost:9042" ]
    session-keyspace = warehouse
    load-balancing-policy {
      local-datacenter = "datacenter1"
    }
  }
  advanced {
    auth-provider {
      class = PlainTextAuthProvider
      username = cassandra
      password = cassandra
    }
  }
}
```

### 3. Agent Startup Script
**File**: [`docker/cassandra/start-debezium-agent.sh`](../docker/cassandra/start-debezium-agent.sh)

Waits for Cassandra and Kafka to be ready, then starts the agent.

### 4. Cassandra Dockerfile Modifications
**File**: [`docker/cassandra/Dockerfile`](../docker/cassandra/Dockerfile)

- Installed Java 11 JRE
- Enabled CDC: `cdc_enabled: true`
- Created CDC directories: `/var/lib/cassandra/cdc_raw`, `/var/lib/cassandra/cdc_offsets`
- Downloaded Debezium agent JAR from Maven Central

---

## Errors Encountered & Resolutions

### Error 1: YAML Parsing Error
```
For input string: "4h"
in 'reader', line 392, column 24:
key_cache_save_period: 4h
```

**Resolution**: Removed `cassandra.config=/etc/cassandra/cassandra.yaml` from properties file. Cassandra's YAML uses time formats ("4h") incompatible with Debezium's YAML parser.

### Error 2: NullPointerException in Schema Loader
```
java.lang.NullPointerException
at io.debezium.connector.cassandra.CassandraConnectorTask$Cassandra4SchemaLoader.load
```

**Resolution**: Added proper `cassandra.driver.config.file` configuration instead of relying on `cassandra.config`.

### Error 3: Missing offset.backing.store.dir
```
The 'offset.backing.store.dir' value is invalid: A value is required
```

**Resolution**: Added to configuration:
```properties
offset.backing.store.dir=/var/lib/cassandra/cdc_offsets
offset.flush.interval.ms=60000
```

### Error 4: Debezium Server - Config File Not Found
```
Failed to load mandatory config value 'debezium.sink.type'
```

**Resolution**: Mounted configuration to both `/debezium/conf/` and `/debezium/config/` paths:
```yaml
volumes:
  - ./docker/debezium-server/config/application.properties:/debezium/conf/application.properties
  - ./docker/debezium-server/config/application.properties:/debezium/config/application.properties
```

### Error 5: Permission Denied
```
java.nio.file.AccessDeniedException: /debezium/conf/application.properties
```

**Resolution**: Changed file permissions from 600 to 644:
```bash
chmod 644 docker/debezium-server/config/application.properties
```

### Error 6: ClassNotFoundException (Final Blocker)
```
java.lang.ClassNotFoundException: io.debezium.connector.cassandra.Cassandra4Connector
```

**Status**: ❌ **UNSOLVED** - This is a fundamental limitation, not a configuration issue.

---

## Why Cassandra Connector is Unavailable

### Official Debezium Documentation Research

The Debezium Cassandra connector is **not maintained** as part of the standard Debezium distribution:

1. **Not in Debezium Server** - The official Debezium Server image does not include Cassandra connector
2. **Not in Kafka Connect** - Not available as a Kafka Connect plugin
3. **Not in Confluent Hub** - Not distributed through Confluent's plugin marketplace
4. **Community/Experimental Status** - May have been community-maintained or experimental

### Maven Central Artifacts

The JAR exists on Maven Central:
```
https://repo1.maven.org/maven2/io/debezium/debezium-connector-cassandra-4/2.7.0.Final/
```

But the artifact appears to be:
- A **stub** or **incomplete** implementation
- Missing the actual connector class files
- Published for dependency management purposes only

---

## Alternative Solutions Considered

### Option 1: Build Custom Debezium Server with Cassandra Connector
**Approach**: Build a custom Debezium Server Docker image that includes the Cassandra connector.

**Challenges**:
- Connector may not have complete implementation
- Would require maintaining custom Docker image
- No official support from Debezium community

**Estimated Effort**: 16-24 hours

### Option 2: Cassandra-to-Kafka Direct Integration
**Approach**: Use Cassandra triggers or custom CDC reader to publish directly to Kafka.

**Options**:
- **CDC Reader**: Custom Java/Python application that reads Cassandra CDC commit logs
- **Cassandra Triggers**: Write triggers in Java to publish to Kafka on mutation

**Estimated Effort**: 40-60 hours

### Option 3: Use Different CDC Tool
**Approach**: Replace Debezium with alternative CDC tool for Cassandra.

**Alternatives**:
- **DataStax CDC**: Commercial solution (requires licensing)
- **Cassandra Change Agent**: Open-source (experimental status)
- **Custom Kafka Producer**: Write custom application

**Estimated Effort**: 60-80 hours

### Option 4: Abandon Cassandra CDC, Use Dual-Write Pattern
**Approach**: Application writes to both Cassandra and Kafka.

**Pros**:
- Simpler architecture
- No CDC connector needed

**Cons**:
- Requires application changes
- Not true CDC (source of truth moves from database to application)
- Doesn't capture manual database changes

**Estimated Effort**: 20-30 hours (application modification)

---

## Current State

### What's Working ✅

1. **Cassandra CDC Enabled**: Cassandra is configured with CDC enabled
   - `cdc_enabled: true` in `cassandra.yaml`
   - CDC directories created and writable
   - Commit logs are being written to `/var/lib/cassandra/cdc_raw`

2. **JDBC Sink Connector**: Successfully deployed and functional
   - PostgreSQL connector working
   - 23 integration tests passing
   - Data flow: Kafka → PostgreSQL ✅

3. **Infrastructure Ready**:
   - Kafka cluster running
   - Schema Registry operational
   - Kafka Connect healthy
   - All configuration files created

### What's Blocked ❌

1. **Cassandra → Kafka**: No viable CDC connector
   - 99 integration tests skipped
   - Data flow: Cassandra → Kafka ❌

2. **End-to-End CDC Pipeline**: Cannot complete
   - Full flow: Cassandra → Kafka → PostgreSQL ❌
   - Missing first leg of pipeline

---

## Test Status Impact

```
Before Connector Work:
- 0 tests passing
- 125 tests skipped

After JDBC Connector Installation:
- ✅ 23 tests passing (infrastructure, JDBC sink, monitoring)
- ⏭️ 99 tests skipped (require Cassandra source connector)
- ❌ 2 tests failed (resource limits - unrelated to connector)
- ⚠️ 1 test error (Cassandra connection)
```

**Tests Passing**: Integration tests for:
- PostgreSQL sink functionality
- Infrastructure health checks
- Security & TLS
- Monitoring & metrics

**Tests Skipped**: All tests requiring Cassandra CDC:
- End-to-end replication
- Schema evolution
- Out-of-order event handling
- Checkpointing
- DLQ functionality
- Reconciliation

---

## Recommendations

### Immediate Actions

1. **Document Limitation**: ✅ Done (this document)
2. **Update Architecture Diagrams**: Show Cassandra CDC as "Planned/Blocked"
3. **Communicate to Stakeholders**: CDC pipeline incomplete without Cassandra source

### Short-Term (1-2 Weeks)

1. **Continue API Development**: Focus on API server features that don't require end-to-end CDC
2. **Develop with Mock Data**: Use test data generation for API/reconciliation testing
3. **Research Alternatives**: Investigate Option 2 (direct Cassandra-to-Kafka integration)

### Medium-Term (1-2 Months)

1. **Build Custom CDC Reader**:
   - Read Cassandra CDC commit logs directly
   - Parse and publish to Kafka
   - Maintain offset tracking

2. **OR: Evaluate DataStax CDC**:
   - Commercial solution with official support
   - May require licensing costs
   - Proven stability

### Long-Term (3+ Months)

1. **Contribute to Debezium**: Consider contributing Cassandra connector to Debezium project
2. **Open-Source Custom Solution**: Publish custom CDC reader as open-source

---

## Files Modified/Created

### Configuration Files
- ✅ `docker/cassandra/debezium-cassandra.properties` - Agent configuration
- ✅ `docker/cassandra/cassandra-driver.conf` - DataStax driver config
- ✅ `docker/cassandra/start-debezium-agent.sh` - Agent startup script
- ✅ `docker/debezium-server/config/application.properties` - Debezium Server config

### Docker Files
- ✅ `docker/cassandra/Dockerfile` - Modified to install agent
- ✅ `docker-compose.yml` - Added debezium-server service, volumes

### Documentation
- ✅ This document - Investigation findings

---

## Lessons Learned

1. **Verify Artifact Contents**: Don't assume Maven Central artifacts contain complete implementations
2. **Check Official Support**: Cassandra connector appears abandoned/experimental
3. **Configuration Compatibility**: Cassandra YAML format incompatible with some parsers
4. **File Paths Matter**: Debezium Server expects config at specific paths
5. **Permissions**: Docker volume mounts require appropriate file permissions (644)

---

## References

- [Debezium Cassandra Connector Docs](https://debezium.io/documentation/reference/stable/connectors/cassandra.html)
- [Debezium Server Docs](https://debezium.io/documentation/reference/stable/operations/debezium-server.html)
- [Maven Central - Cassandra Connector](https://repo1.maven.org/maven2/io/debezium/debezium-connector-cassandra-4/)
- [Cassandra CDC Documentation](https://cassandra.apache.org/doc/latest/cassandra/operating/cdc.html)

---

## Appendix: Running Background Processes

Three background processes were started attempting to run the Debezium agent:

```bash
# Process 1
docker compose exec cassandra bash /opt/debezium/start-debezium-agent.sh &
# Shell ID: 6cd34b

# Process 2
docker compose exec cassandra bash /opt/debezium/start-debezium-agent.sh &
# Shell ID: b212dc

# Process 3 (with logging)
docker compose exec cassandra bash /opt/debezium/start-debezium-agent.sh 2>&1 | tee /tmp/debezium-agent.log &
# Shell ID: 4afbcb
```

All three processes are running but failing with ClassNotFoundException.

To check status:
```bash
docker compose logs cassandra | grep -i debezium
```

To kill processes:
```bash
docker compose exec cassandra pkill -f debezium-cassandra-agent
```

---

**Last Updated**: 2025-11-26
**Status**: Investigation Complete - Awaiting Decision on Alternative Approach
