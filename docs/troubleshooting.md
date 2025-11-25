# Troubleshooting Guide

This guide helps diagnose and resolve common issues with the Cassandra to PostgreSQL CDC Pipeline.

## Table of Contents

- [High Consumer Lag](#high-consumer-lag)
- [Schema Evolution Failures](#schema-evolution-failures)
- [Connection Pool Exhaustion](#connection-pool-exhaustion)
- [Vault Sealed Errors](#vault-sealed-errors)
- [Reconciliation Drift Alerts](#reconciliation-drift-alerts)
- [Connector Failures](#connector-failures)
- [Performance Degradation](#performance-degradation)

---

## High Consumer Lag

**Symptoms:**
- `cdc_backlog_depth` metric increasing
- Replication latency >5 seconds
- Alerts: `HighConsumerLag` firing

**Diagnosis:**

```bash
# Check Kafka consumer lag
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --describe --group cdc-connect

# Check Kafka Connect task status
curl http://localhost:8083/connectors/postgresql-sink-connector/status
```

**Common Causes:**

1. **Slow PostgreSQL writes**
   - Check `pg_stat_statements` for slow queries
   - Verify indexes exist on target tables
   - Monitor connection pool utilization

2. **Insufficient Kafka Connect workers**
   - Scale horizontally: `kubectl scale deployment kafka-connect --replicas=5`
   - Or increase task parallelism in connector config

3. **Network issues**
   - Check latency: `ping postgres-host`
   - Verify network policies allow traffic

**Solutions:**

```bash
# Increase PostgreSQL connection pool
# In connector config:
{
  "connection.pool.size": "20",
  "batch.size": "3000"
}

# Increase Kafka partitions for parallelism
kafka-topics --bootstrap-server localhost:9092 \
  --alter --topic cdc-events-users --partitions 16

# Scale Kafka Connect workers
helm upgrade cdc-pipeline ./helm \
  --set kafkaConnect.replicaCount=10
```

---

## Schema Evolution Failures

**Symptoms:**
- Events routed to DLQ with `SCHEMA_MISMATCH` error
- Schema Registry shows incompatible schema versions
- Connector tasks failing

**Diagnosis:**

```bash
# Check Schema Registry for incompatible schemas
curl http://localhost:8081/subjects/cdc-events-users-value/versions

# Check DLQ for schema errors
kafka-console-consumer --bootstrap-server localhost:9092 \
  --topic dlq-events --from-beginning | jq '.error_type'
```

**Common Causes:**

1. **Breaking schema changes** (e.g., removing required fields)
2. **Type incompatibilities** (e.g., string → integer)
3. **Wrong compatibility mode**

**Solutions:**

```bash
# Set schema compatibility mode
curl -X PUT http://localhost:8081/config/cdc-events-users-value \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  -d '{"compatibility": "BACKWARD"}'

# Replay DLQ events after schema fix
curl -X POST http://localhost:8080/dlq/replay \
  -H "Content-Type: application/json" \
  -d '{"error_type": "SCHEMA_MISMATCH", "retry_strategy": "immediate"}'
```

---

## Connection Pool Exhaustion

**Symptoms:**
- `psycopg2.pool.PoolError: connection pool exhausted`
- Increasing connection count in PostgreSQL
- Slow API responses

**Diagnosis:**

```sql
-- Check active connections
SELECT count(*), state FROM pg_stat_activity
WHERE datname = 'warehouse'
GROUP BY state;

-- Check long-running queries
SELECT pid, now() - query_start as duration, query
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY duration DESC;
```

**Solutions:**

```python
# Increase connection pool size
# In PostgreSQLRepository:
connection_pool = pool.ThreadedConnectionPool(
    minconn=10,
    maxconn=50,  # Increase from 20
    ...
)

# Or configure in Kafka Connect
{
  "connection.pool.size": "50",
  "connection.pool.timeout.ms": "30000"
}
```

---

## Vault Sealed Errors

**Symptoms:**
- Health check shows `vault: sealed=true`
- Connector fails to start with authentication errors
- `VaultConnectionError` in logs

**Diagnosis:**

```bash
# Check Vault status
vault status

# Check Vault logs
kubectl logs deployment/vault -n vault
```

**Solutions:**

```bash
# Unseal Vault (requires unseal keys)
vault operator unseal <key1>
vault operator unseal <key2>
vault operator unseal <key3>

# Enable auto-unseal (recommended for production)
# Configure in Vault config.hcl:
seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/vault-unseal-key"
}

# Verify credentials are accessible
vault kv get secret/cdc/cassandra
vault read database/creds/postgresql-writer
```

---

## Reconciliation Drift Alerts

**Symptoms:**
- Alert: `ReconciliationDriftCritical` firing
- Dashboard shows `drift_percentage > 5%`
- Missing records in PostgreSQL

**Diagnosis:**

```bash
# Check reconciliation job status
curl http://localhost:8080/reconciliation/jobs?status=COMPLETED | jq .

# Query specific job details
curl http://localhost:8080/reconciliation/jobs/{job_id} | jq .mismatches

# Check reconciliation metrics
curl http://localhost:8080/metrics | grep cdc_reconciliation_drift_percentage
```

**Common Causes:**

1. **Connector downtime** - Records missed during outage
2. **Schema mismatches** - Some records failed to replicate
3. **Data corruption** - Checksum mismatches
4. **Manual PostgreSQL changes** - Out-of-band modifications

**Solutions:**

```bash
# Run manual reconciliation with checksum validation
curl -X POST http://localhost:8080/reconciliation/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "tables": ["users", "orders"],
    "validation_strategy": "CHECKSUM"
  }'

# Review and resolve mismatches
curl http://localhost:8080/reconciliation/mismatches?resolution_status=PENDING

# Mark as resolved after manual fix
curl -X POST http://localhost:8080/reconciliation/mismatches/{mismatch_id}/resolve \
  -d '{"resolution_status": "MANUAL_RESOLVED", "resolution_notes": "Backfilled from Cassandra"}'
```

---

## Connector Failures

**Symptoms:**
- Connector status: `FAILED`
- No events flowing
- Errors in Kafka Connect logs

**Diagnosis:**

```bash
# Check connector status
curl http://localhost:8083/connectors/cassandra-source-connector/status | jq .

# Check connector logs
kubectl logs deployment/kafka-connect | grep ERROR

# Check connector tasks
curl http://localhost:8083/connectors/cassandra-source-connector/tasks
```

**Common Solutions:**

```bash
# Restart connector
curl -X POST http://localhost:8083/connectors/cassandra-source-connector/restart

# Restart specific task
curl -X POST http://localhost:8083/connectors/cassandra-source-connector/tasks/0/restart

# Update connector configuration
curl -X PUT http://localhost:8083/connectors/cassandra-source-connector/config \
  -H "Content-Type: application/json" \
  -d @docker/connectors/cassandra-source.json

# Delete and recreate connector
curl -X DELETE http://localhost:8083/connectors/cassandra-source-connector
./docker/connectors/deploy-connectors.sh
```

---

## Performance Degradation

**Symptoms:**
- P95 latency >2 seconds (target: ≤2s)
- Throughput <10K events/sec (target: ≥10K)
- High CPU/memory usage

**Diagnosis:**

```bash
# Run performance benchmark
locust -f scripts/benchmark.py --headless --users 100 --run-time 5m

# Check resource usage
kubectl top pods -l app.kubernetes.io/name=kafka-connect

# Query Prometheus metrics
curl http://localhost:9090/api/v1/query?query=cdc_processing_latency_seconds
```

**Solutions:**

1. **Tune batch sizes:**
```json
{
  "batch.size": "3000",
  "max.poll.records": "1000",
  "linger.ms": "10"
}
```

2. **Add indexes to PostgreSQL:**
```sql
CREATE INDEX CONCURRENTLY idx_users_email ON cdc_users(email);
CREATE INDEX CONCURRENTLY idx_orders_user_id ON cdc_orders(user_id);
```

3. **Scale horizontally:**
```bash
helm upgrade cdc-pipeline ./helm \
  --set kafkaConnect.autoscaling.enabled=true \
  --set kafkaConnect.autoscaling.maxReplicas=20
```

4. **Optimize PostgreSQL:**
```sql
-- Increase shared_buffers
ALTER SYSTEM SET shared_buffers = '2GB';
-- Increase work_mem for batch operations
ALTER SYSTEM SET work_mem = '64MB';
-- Reload configuration
SELECT pg_reload_conf();
```

---

## Getting Help

If issues persist:

1. **Check logs:** `kubectl logs -f deployment/kafka-connect`
2. **Review metrics:** http://localhost:3000 (Grafana)
3. **Check traces:** http://localhost:16686 (Jaeger)
4. **File issue:** https://github.com/yourusername/cass-cdc-pg/issues

## Additional Resources

- [Kafka Connect Documentation](https://docs.confluent.io/platform/current/connect/)
- [Debezium Cassandra Connector](https://debezium.io/documentation/reference/connectors/cassandra.html)
- [PostgreSQL Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [Vault Troubleshooting](https://www.vaultproject.io/docs/troubleshooting)
