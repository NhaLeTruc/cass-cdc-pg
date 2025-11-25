# Data Reconciliation Guide

**Feature**: 001-cass-cdc-pg
**Version**: 1.0.0
**Date**: 2025-11-25

## Overview

The CDC pipeline includes automated data reconciliation to detect and alert on drift between Cassandra (source) and PostgreSQL (target) databases. Reconciliation validates data consistency and ensures exactly-once delivery semantics are maintained.

## Features

### Automated Reconciliation

- **Hourly Scheduled Jobs**: Automatic reconciliation runs every hour for configured tables
- **Manual On-Demand Triggers**: REST API endpoints for triggering reconciliation jobs
- **Multiple Validation Strategies**:
  - Row count validation
  - Checksum-based content validation
  - Timestamp range validation
  - Random sampling validation

### Drift Detection

- **Drift Percentage Calculation**: Measures percentage of records out of sync
- **Configurable Thresholds**:
  - Warning threshold: 1% drift (default)
  - Critical threshold: 5% drift (default)
- **Mismatch Types**:
  - `MISSING_IN_POSTGRES`: Records exist in Cassandra but not PostgreSQL
  - `MISSING_IN_CASSANDRA`: Records exist in PostgreSQL but not Cassandra
  - `DATA_MISMATCH`: Record exists in both but data content differs

### Alerting & Monitoring

- **Prometheus Metrics**:
  - `cdc_reconciliation_drift_percentage`: Current drift percentage per table
  - `cdc_reconciliation_cassandra_rows`: Row count in Cassandra
  - `cdc_reconciliation_postgres_rows`: Row count in PostgreSQL
  - `cdc_reconciliation_mismatches_total`: Mismatch count by type
  - `cdc_reconciliation_jobs_completed_total`: Job completion status
  - `cdc_reconciliation_duration_seconds`: Job execution time

- **AlertManager Alerts**:
  - `ReconciliationDriftWarning`: Fired when drift > 1%
  - `ReconciliationDriftCritical`: Fired when drift > 5%
  - `ReconciliationJobFailed`: Fired when > 3 jobs fail in 1 hour

- **Grafana Dashboard**: Real-time visualization of drift trends and job metrics

## Configuration

### Environment Variables

```bash
# Enable/disable reconciliation scheduler
RECONCILIATION_ENABLED=true

# Interval between scheduled reconciliation runs (minutes)
RECONCILIATION_INTERVAL_MINUTES=60

# Drift alert thresholds (percentage)
RECONCILIATION_DRIFT_WARNING_THRESHOLD=1.0
RECONCILIATION_DRIFT_CRITICAL_THRESHOLD=5.0

# Sample size for checksum validation
RECONCILIATION_SAMPLE_SIZE=1000

# Tables to reconcile (comma-separated)
RECONCILIATION_TABLES=users,orders,sessions
```

### Configuration in `config/settings.py`

```python
from src.config.settings import settings

# Access reconciliation settings
enabled = settings.reconciliation.enabled
interval = settings.reconciliation.interval_minutes
warning_threshold = settings.reconciliation.drift_warning_threshold
critical_threshold = settings.reconciliation.drift_critical_threshold
tables = settings.reconciliation.tables
```

## API Endpoints

### Trigger Manual Reconciliation

**POST** `/reconciliation/trigger`

Manually trigger reconciliation for specific tables.

**Request Body**:
```json
{
  "tables": ["users", "orders"],
  "validation_strategy": "ROW_COUNT"
}
```

**Response**:
```json
{
  "job_ids": [
    "550e8400-e29b-41d4-a716-446655440000",
    "660f9500-f3ac-42e5-b826-557766550111"
  ],
  "status": "RUNNING"
}
```

### List Reconciliation Jobs

**GET** `/reconciliation/jobs`

Query reconciliation job history with filters.

**Query Parameters**:
- `table` (optional): Filter by table name
- `status` (optional): Filter by status (`RUNNING`, `COMPLETED`, `FAILED`)
- `from_date` (optional): Filter by start date (ISO 8601)
- `to_date` (optional): Filter by end date (ISO 8601)
- `limit` (default: 100): Page size
- `offset` (default: 0): Page offset

**Response**:
```json
{
  "jobs": [
    {
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "table_name": "users",
      "job_type": "HOURLY_SCHEDULED",
      "validation_strategy": "ROW_COUNT",
      "started_at": "2025-11-25T10:00:00Z",
      "completed_at": "2025-11-25T10:00:45Z",
      "status": "COMPLETED",
      "cassandra_row_count": 1000000,
      "postgres_row_count": 995000,
      "mismatch_count": 5000,
      "drift_percentage": 0.5,
      "alert_fired": false
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

### Get Reconciliation Job Details

**GET** `/reconciliation/jobs/{job_id}`

Retrieve detailed reconciliation job results including mismatches.

**Response**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "table_name": "users",
  "drift_percentage": 0.5,
  "mismatches": [
    {
      "mismatch_id": "770fa611-04bd-53f6-c937-668877660222",
      "primary_key_value": "user-123",
      "mismatch_type": "MISSING_IN_POSTGRES",
      "cassandra_checksum": "a1b2c3d4...",
      "postgres_checksum": null,
      "detected_at": "2025-11-25T10:00:30Z",
      "resolution_status": "PENDING"
    }
  ]
}
```

### List Reconciliation Mismatches

**GET** `/reconciliation/mismatches`

Query data mismatches detected during reconciliation.

**Query Parameters**:
- `table` (optional): Filter by table name
- `mismatch_type` (optional): Filter by type
- `resolution_status` (optional): Filter by resolution status
- `limit` (default: 1000): Page size
- `offset` (default: 0): Page offset

**Response**:
```json
{
  "mismatches": [
    {
      "mismatch_id": "770fa611-04bd-53f6-c937-668877660222",
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "table_name": "users",
      "primary_key_value": "user-123",
      "mismatch_type": "DATA_MISMATCH",
      "cassandra_data": {"id": "user-123", "email": "old@example.com"},
      "postgres_data": {"id": "user-123", "email": "new@example.com"},
      "resolution_status": "PENDING"
    }
  ],
  "total": 1,
  "limit": 1000,
  "offset": 0
}
```

### Resolve Mismatch

**POST** `/reconciliation/mismatches/{mismatch_id}/resolve`

Mark a data mismatch as resolved with notes.

**Request Body**:
```json
{
  "resolution_status": "MANUAL_RESOLVED",
  "resolution_notes": "Fixed by manual data sync"
}
```

**Response**:
```json
{
  "status": "success",
  "mismatch": {
    "mismatch_id": "770fa611-04bd-53f6-c937-668877660222",
    "resolution_status": "MANUAL_RESOLVED",
    "resolved_at": "2025-11-25T11:00:00Z"
  }
}
```

## Validation Strategies

### 1. Row Count Validation

Compares total row counts between Cassandra and PostgreSQL tables.

**Use case**: Fast drift detection for large tables
**Performance**: O(1) - Uses COUNT(*) queries
**Accuracy**: Detects missing records but not data content mismatches

### 2. Checksum Validation

Calculates SHA-256 checksums of record contents and compares.

**Use case**: Detecting data content mismatches
**Performance**: O(n) - Processes sampled records
**Accuracy**: High - Detects both missing records and content differences

### 3. Timestamp Range Validation

Validates records modified within a specific time window.

**Use case**: Incremental validation of recent changes
**Performance**: O(n) - Filtered by timestamp range
**Accuracy**: High for recent data

### 4. Sample Validation

Randomly samples records for deep comparison.

**Use case**: Quick validation with statistical confidence
**Performance**: O(sample_size)
**Accuracy**: Statistical - confidence increases with sample size

## Monitoring & Observability

### Prometheus Queries

**Current drift percentage**:
```promql
cdc_reconciliation_drift_percentage{table="users"}
```

**Reconciliation job success rate**:
```promql
rate(cdc_reconciliation_jobs_completed_total{status="COMPLETED"}[1h])
/
rate(cdc_reconciliation_jobs_completed_total[1h])
```

**Average reconciliation duration (P95)**:
```promql
histogram_quantile(0.95,
  rate(cdc_reconciliation_duration_seconds_bucket[5m])
)
```

### Grafana Dashboard

Access the pre-configured reconciliation dashboard:

**URL**: http://localhost:3000/d/reconciliation

**Panels**:
- Drift percentage by table (time series)
- Row count comparison (Cassandra vs PostgreSQL)
- Mismatch count by type
- Job success rate
- Reconciliation duration (P50, P95, P99)
- Recent reconciliation jobs (table)

### AlertManager Alerts

**Slack/Email Notifications**: Configure receivers in `docker/monitoring/alertmanager.yml`

```yaml
receivers:
  - name: 'team-alerts'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#cdc-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

## Troubleshooting

### High Drift Detected

**Symptoms**: ReconciliationDriftCritical alert fires, drift > 5%

**Possible Causes**:
1. Kafka Connect source/sink connector failure
2. Network partition between Cassandra and PostgreSQL
3. Pipeline backlog accumulation
4. Manual data modification bypassing CDC

**Resolution**:
1. Check Kafka Connect connector status: `curl http://localhost:8083/connectors`
2. Check consumer lag: `cdc_backlog_depth` metric
3. Review DLQ for failed events: `GET /dlq/records`
4. Query mismatches for pattern analysis: `GET /reconciliation/mismatches`
5. Re-sync missing records using DLQ replay API

### Reconciliation Job Failures

**Symptoms**: ReconciliationJobFailed alert fires, jobs completing with FAILED status

**Possible Causes**:
1. Database connection errors (Cassandra or PostgreSQL)
2. Permission issues accessing tables
3. Table schema changes
4. Resource exhaustion (memory, connections)

**Resolution**:
1. Check reconciliation job errors: `GET /reconciliation/jobs?status=FAILED`
2. Review application logs for error stack traces
3. Verify database connectivity and credentials
4. Check table permissions for `cdc_user`
5. Monitor resource utilization (Grafana system metrics)

### False Positive Alerts

**Symptoms**: Alerts fire but manual verification shows no drift

**Possible Causes**:
1. Temporary network lag during row count query
2. Concurrent writes during reconciliation
3. TTL expiration happening between queries

**Resolution**:
1. Increase alert `for` duration in `prometheus-alerts.yml` (default: 5m)
2. Schedule reconciliation during low-traffic periods
3. Adjust drift thresholds for volatile tables

## Performance Tuning

### Large Table Optimization

For tables with > 10 million rows:

- Use **SAMPLE validation** instead of full checksum
- Increase `RECONCILIATION_SAMPLE_SIZE` to 10,000 for better coverage
- Schedule reconciliation during maintenance windows
- Enable table partitioning in PostgreSQL

### Reducing False Positives

- Increase `drift_critical_threshold` from 5% to 10% for volatile tables
- Use timestamp range validation for append-only tables
- Exclude tables with high TTL churn rate from reconciliation

### Resource Management

- Limit concurrent reconciliation jobs to 3-5 tables
- Set PostgreSQL connection pool size appropriately
- Monitor reconciliation duration and adjust sample sizes

## Best Practices

1. **Start with row count validation** for initial drift detection
2. **Use checksum validation** for critical tables requiring data integrity
3. **Configure alerts** based on table criticality (adjust thresholds)
4. **Review mismatches weekly** to identify pipeline issues
5. **Document resolutions** in mismatch resolution notes
6. **Monitor reconciliation metrics** in Grafana dashboard
7. **Test reconciliation** on dev/staging before production
8. **Schedule reconciliation** during off-peak hours for large tables

## GDPR Compliance

### Data Erasure

The reconciliation system supports GDPR "right to erasure" (Article 17):

**DELETE** `/records/{keyspace}/{table}/{primary_key}`

Deletes a record from both Cassandra and PostgreSQL with full audit trail.

**Example**:
```bash
curl -X DELETE \
  http://localhost:8080/records/warehouse/users/user-123 \
  -H "Authorization: Bearer $TOKEN"
```

**Audit Trail**: All deletions are logged in `_cdc_audit_log` table with:
- Requester identification
- Deletion reason
- Timestamp
- Success/failure status for both databases

## References

- [Reconciliation API Specification](../specs/001-cass-cdc-pg/contracts/reconciliation-api.md)
- [Prometheus Metrics Reference](../specs/001-cass-cdc-pg/spec.md#FR-026)
- [AlertManager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Grafana Dashboard JSON](../docker/monitoring/grafana/dashboards/reconciliation.json)

## Support

For issues or questions:
- GitHub Issues: https://github.com/your-org/cass-cdc-pg/issues
- Internal Documentation: Confluence CDC Pipeline space
- On-call Rotation: PagerDuty #cdc-pipeline
