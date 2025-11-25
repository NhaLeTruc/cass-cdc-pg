# Runbook: Kafka Connect Connector Failure

**Alert**: `KafkaConnectTaskFailure`
**Severity**: Critical
**Threshold**: Connector state = FAILED or STOPPED for 2 minutes
**SLO Impact**: Direct impact on data replication SLO (no events processed)

## Symptoms

- Prometheus alert `KafkaConnectTaskFailure` fires
- Kafka Connect REST API shows connector state as `FAILED`
- No new events being written to PostgreSQL
- Grafana dashboard shows flatlined `cdc_events_processed_total` metric

## Diagnosis

### Step 1: Identify Failed Connector

Query Kafka Connect API:
```bash
curl http://localhost:8083/connectors | jq '.[]'

# Check specific connector status
curl http://localhost:8083/connectors/cassandra-source-connector/status | jq '.'
curl http://localhost:8083/connectors/postgres-sink-connector/status | jq '.'
```

Expected output:
```json
{
  "name": "postgres-sink-connector",
  "connector": {
    "state": "RUNNING",  // Should be RUNNING
    "worker_id": "kafka-connect:8083"
  },
  "tasks": [
    {
      "id": 0,
      "state": "RUNNING",  // Should be RUNNING
      "worker_id": "kafka-connect:8083"
    }
  ]
}
```

### Step 2: Retrieve Error Details

Get connector trace:
```bash
curl http://localhost:8083/connectors/postgres-sink-connector/status | jq '.tasks[].trace'
```

### Step 3: Check Connector Logs

```bash
docker logs cdc-kafka-connect --tail=200 | grep -A 10 "ERROR\|FAILED"
```

Common error patterns:
- `Connection refused` → Database unavailable
- `Authentication failed` → Credential rotation issue
- `Schema mismatch` → Schema Registry or table DDL issue
- `Timeout` → Network or database performance issue

## Root Causes & Solutions

### Cause 1: Database Connection Failure

**Symptom**:
- Error: `java.sql.SQLException: Connection refused`
- Connector state: `FAILED`

**Diagnosis**:
```bash
# Test Cassandra connectivity
docker exec -it cdc-cassandra cqlsh -e "DESCRIBE KEYSPACES"

# Test PostgreSQL connectivity
docker exec -it cdc-postgres psql -U admin -d warehouse -c "SELECT 1"
```

**Solution**:
```bash
# If Cassandra is down
docker-compose restart cassandra

# If PostgreSQL is down
docker-compose restart postgres

# Wait for databases to be healthy (30-60 seconds)
# Then restart failed connector
curl -X POST http://localhost:8083/connectors/cassandra-source-connector/restart
curl -X POST http://localhost:8083/connectors/postgres-sink-connector/restart

# Verify connector recovered
curl http://localhost:8083/connectors/postgres-sink-connector/status
```

### Cause 2: Authentication/Credential Failure

**Symptom**:
- Error: `Authentication failed for user`
- Error: `Invalid credentials`

**Diagnosis**:
```bash
# Check if credentials expired (Vault dynamic credentials have 24h TTL)
docker logs cdc-api | grep "vault_credentials_expired"

# Verify Vault is accessible
curl http://localhost:8200/v1/sys/health
```

**Solution**:
```bash
# Rotate credentials via Vault
docker exec -it cdc-vault vault login root

# Renew lease for PostgreSQL credentials
docker exec -it cdc-vault vault lease renew database/creds/postgresql-writer/<lease_id>

# Or restart CDC API to fetch fresh credentials
docker-compose restart cdc-api

# Update connector configuration with new credentials
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/config \
  -H "Content-Type: application/json" \
  -d @docker/connectors/postgres-sink.json

# Restart connector
curl -X POST http://localhost:8083/connectors/postgres-sink-connector/restart
```

### Cause 3: Schema Registry Unavailable

**Symptom**:
- Error: `Schema registry not available`
- Error: `Failed to retrieve schema for id <schema_id>`

**Diagnosis**:
```bash
# Check Schema Registry health
curl http://localhost:8081/subjects
```

**Solution**:
```bash
# Restart Schema Registry
docker-compose restart schema-registry

# Wait for Schema Registry to be ready (10-15 seconds)
sleep 15

# Restart connectors
curl -X POST http://localhost:8083/connectors/cassandra-source-connector/restart
curl -X POST http://localhost:8083/connectors/postgres-sink-connector/restart
```

### Cause 4: PostgreSQL Table Schema Mismatch

**Symptom**:
- Error: `Column 'new_column' does not exist`
- Error: `Type mismatch for column 'age': expected INTEGER, got TEXT`

**Diagnosis**:
```bash
# Get latest Cassandra schema
docker exec -it cdc-cassandra cqlsh -e "DESCRIBE TABLE warehouse.users"

# Get PostgreSQL table schema
docker exec -it cdc-postgres psql -U admin -d warehouse -c "\d cdc_users"
```

**Solution**:
```bash
# Option 1: Enable auto.evolve in JDBC Sink
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/config \
  -H "Content-Type: application/json" \
  -d '{
    "auto.evolve": "true"
  }'

# Option 2: Manually alter PostgreSQL table
docker exec -it cdc-postgres psql -U admin -d warehouse -c "
ALTER TABLE cdc_users ADD COLUMN new_column VARCHAR(255);
"

# Restart connector
curl -X POST http://localhost:8083/connectors/postgres-sink-connector/restart
```

### Cause 5: DLQ Topic Full / Error Tolerance Exceeded

**Symptom**:
- Error: `Tolerance exceeded in error handler`
- DLQ topic partition full

**Diagnosis**:
```bash
# Check DLQ event count
curl http://localhost:9090/api/v1/query?query=cdc_dlq_events_total | jq '.'

# Query DLQ records
curl http://localhost:8080/dlq/records?limit=10
```

**Solution**:
```bash
# Increase error tolerance temporarily
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/config \
  -H "Content-Type: application/json" \
  -d '{
    "errors.tolerance": "all",
    "errors.deadletterqueue.topic.replication.factor": "1"
  }'

# Investigate DLQ records to find root cause
curl http://localhost:8080/dlq/records?error_type=TYPE_CONVERSION_ERROR

# Fix root cause (e.g., add missing column, fix type mismatch)
# Then replay DLQ events
curl -X POST http://localhost:8080/dlq/replay \
  -H "Content-Type: application/json" \
  -d '{
    "error_type": "TYPE_CONVERSION_ERROR",
    "limit": 1000
  }'
```

### Cause 6: Kafka Connect Worker Failure

**Symptom**:
- All connector tasks assigned to same worker
- Worker process crashed

**Diagnosis**:
```bash
# Check Kafka Connect worker health
docker ps | grep kafka-connect

# Check worker logs
docker logs cdc-kafka-connect --tail=100
```

**Solution**:
```bash
# Restart Kafka Connect
docker-compose restart kafka-connect

# Wait for Kafka Connect to be ready (30 seconds)
sleep 30

# Verify connectors auto-recovered
curl http://localhost:8083/connectors
```

## Emergency Procedures

### Pause Pipeline (Stop All Processing)

```bash
# Pause source connector (stops reading from Cassandra)
curl -X PUT http://localhost:8083/connectors/cassandra-source-connector/pause

# Pause sink connector (stops writing to PostgreSQL)
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/pause
```

### Resume Pipeline

```bash
# Resume source connector
curl -X PUT http://localhost:8083/connectors/cassandra-source-connector/resume

# Resume sink connector
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/resume
```

### Delete and Recreate Connector (Last Resort)

```bash
# Delete failed connector
curl -X DELETE http://localhost:8083/connectors/postgres-sink-connector

# Recreate from configuration file
curl -X POST http://localhost:8083/connectors \
  -H "Content-Type: application/json" \
  -d @docker/connectors/postgres-sink.json

# Note: This will lose offset history. Connector will resume from Kafka consumer group offset.
```

## Escalation

If connector does not recover after 15 minutes:

1. **Check Kafka broker health**:
   ```bash
   docker exec -it cdc-kafka kafka-broker-api-versions --bootstrap-server localhost:9092
   ```

2. **Review Kafka Connect configuration**: Verify `docker/kafka/connect-distributed.properties`

3. **Page on-call infrastructure engineer** if Kafka/PostgreSQL/Cassandra issues suspected

4. **Failover to backup connector** (if available in DR region)

## Prevention

- Monitor connector health with Prometheus alert
- Set up automated connector restart on failure (Kubernetes restart policy)
- Enable connector health check endpoints
- Implement circuit breaker for database connections
- Use Vault dynamic credentials with auto-renewal
- Test connector failure scenarios in staging environment

## Post-Incident Review

- Document error trace and root cause
- Review connector configuration for improvements
- Update error handling strategy
- Add monitoring for newly identified failure mode

## Related Runbooks

- [High Consumer Lag](./high-consumer-lag.md)
- [Schema Mismatch](./schema-mismatch.md)
- [Vault Sealed](./vault-sealed.md)
