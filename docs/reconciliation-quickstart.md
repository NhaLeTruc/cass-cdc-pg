# Reconciliation Quick Start Guide

**5-Minute Setup Guide**

## Prerequisites

- CDC pipeline running (Cassandra, PostgreSQL, Kafka)
- Docker Compose with monitoring stack
- Python 3.11+ environment

## Step 1: Enable Reconciliation (30 seconds)

Edit `.env` file:

```bash
# Enable reconciliation scheduler
RECONCILIATION_ENABLED=true

# Configure tables to reconcile
RECONCILIATION_TABLES=users,orders

# Set drift thresholds
RECONCILIATION_DRIFT_WARNING_THRESHOLD=1.0
RECONCILIATION_DRIFT_CRITICAL_THRESHOLD=5.0

# Set interval (minutes)
RECONCILIATION_INTERVAL_MINUTES=60
```

## Step 2: Start Services (2 minutes)

```bash
# Start monitoring stack with AlertManager
docker-compose up -d prometheus alertmanager pushgateway grafana

# Start CDC API with reconciliation scheduler
docker-compose up -d cdc-api

# Verify services are running
docker-compose ps
```

Expected output:
```
cdc-prometheus      Up      9090/tcp
cdc-alertmanager    Up      9093/tcp
cdc-pushgateway     Up      9091/tcp
cdc-grafana         Up      3000/tcp
cdc-api             Up      8080/tcp
```

## Step 3: Verify Reconciliation (1 minute)

### Check Scheduler Status

```bash
curl http://localhost:8080/health
```

Expected response:
```json
{
  "status": "healthy",
  "reconciliation_scheduler": "running",
  "scheduled_tables": ["users", "orders"]
}
```

### Trigger Manual Reconciliation

```bash
curl -X POST http://localhost:8080/reconciliation/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "tables": ["users"],
    "validation_strategy": "ROW_COUNT"
  }'
```

Expected response:
```json
{
  "job_ids": ["550e8400-e29b-41d4-a716-446655440000"],
  "status": "RUNNING"
}
```

### View Reconciliation Results

```bash
curl http://localhost:8080/reconciliation/jobs?limit=5
```

## Step 4: Monitor Metrics (1 minute)

### Prometheus Metrics

Open http://localhost:9090 and query:

```promql
cdc_reconciliation_drift_percentage
```

### Grafana Dashboard

1. Open http://localhost:3000 (admin/admin)
2. Navigate to "CDC Reconciliation Dashboard"
3. View drift percentage, row counts, and job status

### AlertManager Alerts

Open http://localhost:9093 to view active alerts.

## Common Commands

### List All Reconciliation Jobs

```bash
curl "http://localhost:8080/reconciliation/jobs?status=COMPLETED&limit=10"
```

### Get Job Details

```bash
JOB_ID="550e8400-e29b-41d4-a716-446655440000"
curl "http://localhost:8080/reconciliation/jobs/$JOB_ID"
```

### List Mismatches

```bash
curl "http://localhost:8080/reconciliation/mismatches?table=users&resolution_status=PENDING"
```

### Resolve a Mismatch

```bash
MISMATCH_ID="770fa611-04bd-53f6-c937-668877660222"
curl -X POST "http://localhost:8080/reconciliation/mismatches/$MISMATCH_ID/resolve" \
  -H "Content-Type: application/json" \
  -d '{
    "resolution_status": "MANUAL_RESOLVED",
    "resolution_notes": "Fixed by manual data sync"
  }'
```

## Testing Drift Detection

### Create Artificial Drift

```bash
# Delete records from PostgreSQL to create drift
docker exec -it cdc-postgres psql -U cdc_user -d warehouse -c \
  "DELETE FROM cdc_users WHERE id IN (
    SELECT id FROM cdc_users LIMIT 100
  )"

# Trigger reconciliation
curl -X POST http://localhost:8080/reconciliation/trigger \
  -H "Content-Type: application/json" \
  -d '{"tables": ["users"], "validation_strategy": "ROW_COUNT"}'

# Wait 30 seconds for job to complete
sleep 30

# Check drift percentage
curl http://localhost:8080/reconciliation/jobs?table=users&limit=1
```

Expected: Drift percentage should be > 0%

### Verify Alert Fires

```bash
# Check AlertManager for active alerts
curl http://localhost:9093/api/v2/alerts | jq '.[] | select(.labels.alertname=="ReconciliationDriftWarning")'
```

## Troubleshooting

### Scheduler Not Starting

**Check logs**:
```bash
docker-compose logs cdc-api | grep reconciliation
```

**Common fixes**:
- Verify `RECONCILIATION_ENABLED=true` in `.env`
- Check database connectivity
- Ensure tables exist in both Cassandra and PostgreSQL

### No Metrics in Prometheus

**Check pushgateway**:
```bash
curl http://localhost:9091/metrics | grep cdc_reconciliation
```

**Common fixes**:
- Verify Prometheus is scraping pushgateway: http://localhost:9090/targets
- Check `prometheus.yml` includes pushgateway scrape config
- Restart Prometheus: `docker-compose restart prometheus`

### Alerts Not Firing

**Check alert rules**:
```bash
curl http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name=="cdc_pipeline")'
```

**Common fixes**:
- Verify `prometheus-alerts.yml` is mounted in Prometheus container
- Check AlertManager is running: `docker-compose ps alertmanager`
- Verify Prometheus alertmanager config: http://localhost:9090/config

## Next Steps

1. **Configure Slack/Email Notifications**: Edit `docker/monitoring/alertmanager.yml`
2. **Customize Drift Thresholds**: Adjust per table in `.env`
3. **Schedule Maintenance Reconciliation**: Set cron jobs for large tables
4. **Review Mismatches**: Query `/reconciliation/mismatches` API weekly
5. **Export Metrics**: Integrate with Datadog/New Relic

## Production Checklist

- [ ] Configure proper authentication for API endpoints
- [ ] Set up Slack/PagerDuty alert receivers
- [ ] Enable TLS for all HTTP endpoints
- [ ] Configure Vault for credential management
- [ ] Set up log aggregation (ELK/Splunk)
- [ ] Create runbooks for drift resolution
- [ ] Schedule reconciliation during off-peak hours
- [ ] Test failover scenarios
- [ ] Document escalation procedures
- [ ] Train on-call engineers

## Additional Resources

- [Full Reconciliation Guide](./reconciliation.md)
- [API Reference](../specs/001-cass-cdc-pg/contracts/reconciliation-api.md)
- [Prometheus Queries](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [AlertManager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
