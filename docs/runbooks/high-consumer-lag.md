# Runbook: High Kafka Consumer Lag

**Alert**: `HighConsumerLag`
**Severity**: Warning
**Threshold**: Consumer lag > 10,000 events for 5 minutes
**SLO Impact**: May cause data freshness SLO violation (> 5 minute lag)

## Symptoms

- Prometheus alert `HighConsumerLag` fires
- Grafana dashboard shows increasing `cdc_backlog_depth` metric
- Data lag reported in reconciliation jobs
- Customers report stale data in analytics queries

## Diagnosis

### Step 1: Verify the Alert

Query Prometheus:
```promql
cdc_backlog_depth{topic=~"cdc-events-.*"}
```

Expected: < 10,000 events per topic
Actual: > 10,000 events (alert threshold)

### Step 2: Identify the Bottleneck

Check Kafka Connect task status:
```bash
curl http://localhost:8083/connectors/postgres-sink-connector/status | jq '.'
```

Look for:
- `state`: Should be `RUNNING`, not `PAUSED` or `FAILED`
- `worker_id`: Verify tasks distributed across workers
- `errors_logged`: Check for error messages

### Step 3: Check PostgreSQL Performance

Query PostgreSQL connection count:
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'warehouse';
```

Check for locks:
```sql
SELECT * FROM pg_stat_activity
WHERE state = 'active' AND wait_event_type = 'Lock';
```

Check slow queries:
```sql
SELECT pid, now() - query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active' AND now() - query_start > interval '30 seconds';
```

### Step 4: Review Kafka Connect Logs

```bash
docker logs cdc-kafka-connect --tail=100 | grep ERROR
```

Common error patterns:
- `java.sql.SQLException: Connection refused` → PostgreSQL unavailable
- `org.apache.kafka.connect.errors.ConnectException: Tolerance exceeded` → DLQ full
- `java.lang.OutOfMemoryError` → Increase Kafka Connect heap size

## Root Causes & Solutions

### Cause 1: JDBC Sink Connector Paused/Failed

**Symptom**: Connector state = `PAUSED` or `FAILED`

**Solution**:
```bash
# Restart connector
curl -X POST http://localhost:8083/connectors/postgres-sink-connector/restart

# Verify state
curl http://localhost:8083/connectors/postgres-sink-connector/status
```

### Cause 2: PostgreSQL Connection Pool Exhausted

**Symptom**:
- PostgreSQL `max_connections` reached
- Kafka Connect logs: `Connection refused` or `Too many connections`

**Solution**:
```bash
# Increase PostgreSQL max_connections
docker exec -it cdc-postgres psql -U admin -d warehouse -c "ALTER SYSTEM SET max_connections = 200;"
docker restart cdc-postgres

# Or increase Kafka Connect worker count to distribute load
docker-compose up -d --scale kafka-connect=3
```

### Cause 3: Slow PostgreSQL Writes (Lock Contention)

**Symptom**:
- High `cdc_processing_latency_seconds` metric
- PostgreSQL locks visible in `pg_stat_activity`

**Solution**:
```bash
# Identify blocking queries
docker exec -it cdc-postgres psql -U admin -d warehouse -c "
SELECT
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
"

# Terminate blocking query (use with caution)
docker exec -it cdc-postgres psql -U admin -d warehouse -c "SELECT pg_terminate_backend(<blocking_pid>);"
```

### Cause 4: Large Batch Backlog (Spike in Traffic)

**Symptom**:
- Sudden spike in `cdc_backlog_depth`
- Recent high volume of Cassandra writes

**Solution**:
```bash
# Temporarily increase JDBC Sink batch size for faster processing
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/config \
  -H "Content-Type: application/json" \
  -d '{
    "batch.size": "2000",
    "consumer.max.poll.records": "2000"
  }'

# Monitor lag reduction
watch -n 5 'curl -s http://localhost:9090/api/v1/query?query=cdc_backlog_depth | jq ".data.result[].value[1]"'

# After lag recovered, restore default batch size
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/config \
  -H "Content-Type: application/json" \
  -d '{
    "batch.size": "1000",
    "consumer.max.poll.records": "1000"
  }'
```

### Cause 5: Kafka Connect Out of Memory

**Symptom**:
- Kafka Connect container restarts frequently
- Logs: `java.lang.OutOfMemoryError: Java heap space`

**Solution**:
```bash
# Increase Kafka Connect heap size in docker-compose.yml
# Edit docker-compose.yml:
# environment:
#   KAFKA_HEAP_OPTS: "-Xms2G -Xmx2G"  # Increase from 1G to 2G

docker-compose up -d kafka-connect
```

## Escalation

If lag does not reduce after 30 minutes:

1. **Pause source connector** to stop new events:
   ```bash
   curl -X PUT http://localhost:8083/connectors/cassandra-source-connector/pause
   ```

2. **Scale up JDBC Sink workers**:
   ```bash
   docker-compose up -d --scale kafka-connect=5
   ```

3. **Contact DBA** to check PostgreSQL query performance and table bloat

4. **Page on-call engineer** if data freshness SLO at risk

## Prevention

- Set up autoscaling for Kafka Connect workers (Kubernetes HPA)
- Increase PostgreSQL connection pool size preemptively
- Monitor `cdc_backlog_depth` trend and alert on sustained growth
- Implement read replicas for PostgreSQL to offload analytics queries
- Schedule high-volume Cassandra writes during off-peak hours

## Post-Incident Review

- Document root cause in incident report
- Review Grafana dashboard for lag trend leading up to incident
- Update alerting thresholds if false positive
- Add monitoring for newly identified bottleneck

## Related Runbooks

- [Connector Failure](./connector-failure.md)
- [PostgreSQL Performance Issues](./postgres-performance.md)
- [Kafka Broker Failure](./kafka-broker-failure.md)
