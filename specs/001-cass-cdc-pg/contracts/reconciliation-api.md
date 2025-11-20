# Reconciliation API Contract

**Feature**: Cassandra to PostgreSQL CDC Pipeline - Data Reconciliation
**Created**: 2025-11-20
**Status**: Extension to original CDC pipeline

## Overview

This contract defines the REST API endpoints for data reconciliation between Cassandra (source) and PostgreSQL (target). Reconciliation ensures data consistency through periodic validation and provides visibility into sync drift.

## Base URL

```
http://localhost:8080/api/v1
```

Production: `https://cdc-pipeline.company.com/api/v1`

---

## Endpoints

### 1. Trigger Manual Reconciliation

**POST /reconciliation/trigger**

Trigger on-demand reconciliation for one or more tables.

**Request**:
```json
{
  "tables": ["users", "orders", "products"],
  "validation_strategy": "CHECKSUM",
  "priority": "HIGH"
}
```

**Request Schema**:
- `tables` (array[string], required): List of table names to reconcile. Empty array = all tables
- `validation_strategy` (enum, required): Validation method
  - `ROW_COUNT`: Quick count comparison only
  - `CHECKSUM`: Sample-based checksum comparison (default)
  - `TIMESTAMP_RANGE`: Validate records modified in last hour
  - `SAMPLE`: Deep comparison of random sample (1000 records)
- `priority` (enum, optional): Job priority (default: NORMAL)
  - `LOW`: Run when queue is empty
  - `NORMAL`: Run in order
  - `HIGH`: Jump to front of queue

**Response 202 Accepted**:
```json
{
  "job_ids": [
    "550e8400-e29b-41d4-a716-446655440000",
    "550e8400-e29b-41d4-a716-446655440001",
    "550e8400-e29b-41d4-a716-446655440002"
  ],
  "status": "RUNNING",
  "message": "Reconciliation jobs queued for 3 tables",
  "estimated_completion": "2025-11-20T15:05:00Z"
}
```

**Response 400 Bad Request** (invalid table name):
```json
{
  "error": "INVALID_TABLE",
  "message": "Table 'invalid_table' does not exist or is not configured for replication",
  "valid_tables": ["users", "orders", "products"]
}
```

**Response 503 Service Unavailable** (reconciliation disabled):
```json
{
  "error": "RECONCILIATION_DISABLED",
  "message": "Reconciliation service is disabled. Set RECONCILIATION_ENABLED=true in configuration"
}
```

**Rate Limiting**: 10 requests per minute per API key

---

### 2. Query Reconciliation Jobs

**GET /reconciliation/jobs**

Query reconciliation job history with filters.

**Query Parameters**:
- `table` (string, optional): Filter by table name
- `status` (enum, optional): Filter by job status (RUNNING, COMPLETED, FAILED)
- `job_type` (enum, optional): Filter by type (HOURLY_SCHEDULED, MANUAL_ONDEMAND)
- `from_date` (ISO 8601, optional): Start date (inclusive)
- `to_date` (ISO 8601, optional): End date (inclusive)
- `page` (integer, optional): Page number (default: 1)
- `page_size` (integer, optional): Items per page (default: 50, max: 100)

**Example Request**:
```
GET /reconciliation/jobs?table=users&status=COMPLETED&from_date=2025-11-01T00:00:00Z&page=1&page_size=20
```

**Response 200 OK**:
```json
{
  "jobs": [
    {
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "table_name": "users",
      "job_type": "MANUAL_ONDEMAND",
      "validation_strategy": "CHECKSUM",
      "started_at": "2025-11-20T14:00:00Z",
      "completed_at": "2025-11-20T14:02:15Z",
      "duration_seconds": 135,
      "status": "COMPLETED",
      "cassandra_row_count": 1000000,
      "postgres_row_count": 999950,
      "mismatch_count": 50,
      "drift_percentage": 0.005,
      "alert_fired": false
    },
    {
      "job_id": "550e8400-e29b-41d4-a716-446655440001",
      "table_name": "users",
      "job_type": "HOURLY_SCHEDULED",
      "validation_strategy": "ROW_COUNT",
      "started_at": "2025-11-20T13:00:00Z",
      "completed_at": "2025-11-20T13:00:05Z",
      "duration_seconds": 5,
      "status": "COMPLETED",
      "cassandra_row_count": 999800,
      "postgres_row_count": 999800,
      "mismatch_count": 0,
      "drift_percentage": 0.0,
      "alert_fired": false
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_pages": 5,
    "total_items": 87
  }
}
```

---

### 3. Get Reconciliation Job Details

**GET /reconciliation/jobs/{job_id}**

Get detailed results for a specific reconciliation job, including mismatches.

**Path Parameters**:
- `job_id` (UUID, required): Reconciliation job identifier

**Response 200 OK**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "table_name": "users",
  "job_type": "MANUAL_ONDEMAND",
  "validation_strategy": "CHECKSUM",
  "started_at": "2025-11-20T14:00:00Z",
  "completed_at": "2025-11-20T14:02:15Z",
  "duration_seconds": 135,
  "status": "COMPLETED",
  "cassandra_row_count": 1000000,
  "postgres_row_count": 999950,
  "mismatch_count": 50,
  "drift_percentage": 0.005,
  "validation_errors": null,
  "alert_fired": false,
  "mismatches_summary": {
    "MISSING_IN_POSTGRES": 30,
    "MISSING_IN_CASSANDRA": 10,
    "DATA_MISMATCH": 10
  },
  "sample_mismatches": [
    {
      "mismatch_id": "660e8400-e29b-41d4-a716-446655440000",
      "primary_key_value": "user-12345",
      "mismatch_type": "MISSING_IN_POSTGRES",
      "detected_at": "2025-11-20T14:01:23Z",
      "resolution_status": "PENDING"
    },
    {
      "mismatch_id": "660e8400-e29b-41d4-a716-446655440001",
      "primary_key_value": "user-67890",
      "mismatch_type": "DATA_MISMATCH",
      "cassandra_checksum": "a1b2c3d4e5f6",
      "postgres_checksum": "f6e5d4c3b2a1",
      "detected_at": "2025-11-20T14:01:45Z",
      "resolution_status": "PENDING"
    }
  ]
}
```

**Response 404 Not Found**:
```json
{
  "error": "JOB_NOT_FOUND",
  "message": "Reconciliation job with ID '550e8400-e29b-41d4-a716-446655440000' not found"
}
```

---

### 4. Query Mismatched Records

**GET /reconciliation/mismatches**

Query mismatched records across all reconciliation jobs.

**Query Parameters**:
- `table` (string, optional): Filter by table name
- `mismatch_type` (enum, optional): Filter by mismatch type
  - `MISSING_IN_POSTGRES`: Record exists in Cassandra but not PostgreSQL
  - `MISSING_IN_CASSANDRA`: Record exists in PostgreSQL but not Cassandra
  - `DATA_MISMATCH`: Record exists in both but data differs
- `resolution_status` (enum, optional): Filter by resolution status
  - `PENDING`: Not yet resolved
  - `AUTO_RESOLVED`: Automatically resolved by subsequent replication
  - `MANUAL_RESOLVED`: Manually marked as resolved
  - `IGNORED`: Marked as expected difference
- `job_id` (UUID, optional): Filter by specific job
- `from_date` (ISO 8601, optional): Mismatches detected after this date
- `to_date` (ISO 8601, optional): Mismatches detected before this date
- `page` (integer, optional): Page number (default: 1)
- `page_size` (integer, optional): Items per page (default: 50, max: 100)

**Example Request**:
```
GET /reconciliation/mismatches?table=users&mismatch_type=DATA_MISMATCH&resolution_status=PENDING&page=1
```

**Response 200 OK**:
```json
{
  "mismatches": [
    {
      "mismatch_id": "660e8400-e29b-41d4-a716-446655440001",
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "table_name": "users",
      "primary_key_value": "user-67890",
      "mismatch_type": "DATA_MISMATCH",
      "cassandra_checksum": "a1b2c3d4e5f6",
      "postgres_checksum": "f6e5d4c3b2a1",
      "cassandra_data": {
        "user_id": "user-67890",
        "email": "john@example.com",
        "name": "John Doe",
        "updated_at": "2025-11-20T13:30:00Z"
      },
      "postgres_data": {
        "user_id": "user-67890",
        "email": "john@example.com",
        "name": "John Smith",
        "updated_at": "2025-11-20T12:00:00Z"
      },
      "detected_at": "2025-11-20T14:01:45Z",
      "resolution_status": "PENDING",
      "resolution_notes": null,
      "resolved_at": null
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total_pages": 1,
    "total_items": 10
  }
}
```

---

### 5. Resolve Mismatch

**POST /reconciliation/mismatches/{mismatch_id}/resolve**

Mark a mismatch as resolved or ignored with notes.

**Path Parameters**:
- `mismatch_id` (UUID, required): Mismatch identifier

**Request**:
```json
{
  "resolution_status": "MANUAL_RESOLVED",
  "resolution_notes": "Manually synced user data from Cassandra to PostgreSQL. Name change was legitimate."
}
```

**Request Schema**:
- `resolution_status` (enum, required): Resolution status
  - `MANUAL_RESOLVED`: Manually fixed the discrepancy
  - `IGNORED`: Difference is expected (e.g., soft delete in one system)
- `resolution_notes` (string, optional): Free-text explanation (max 1000 chars)

**Response 200 OK**:
```json
{
  "mismatch_id": "660e8400-e29b-41d4-a716-446655440001",
  "resolution_status": "MANUAL_RESOLVED",
  "resolution_notes": "Manually synced user data from Cassandra to PostgreSQL. Name change was legitimate.",
  "resolved_at": "2025-11-20T15:30:00Z",
  "resolved_by": "admin@company.com"
}
```

**Response 404 Not Found**:
```json
{
  "error": "MISMATCH_NOT_FOUND",
  "message": "Mismatch with ID '660e8400-e29b-41d4-a716-446655440001' not found"
}
```

**Response 400 Bad Request** (invalid status transition):
```json
{
  "error": "INVALID_STATUS_TRANSITION",
  "message": "Cannot change resolution_status from 'MANUAL_RESOLVED' to 'PENDING'"
}
```

---

## Prometheus Metrics Endpoint

**GET /metrics**

Prometheus scrape endpoint exposing reconciliation metrics.

**Response 200 OK** (Prometheus text format):
```
# HELP cdc_reconciliation_drift_percentage Percentage of records out of sync
# TYPE cdc_reconciliation_drift_percentage gauge
cdc_reconciliation_drift_percentage{table="users"} 0.005
cdc_reconciliation_drift_percentage{table="orders"} 0.0
cdc_reconciliation_drift_percentage{table="products"} 0.12

# HELP cdc_reconciliation_cassandra_rows Total rows in Cassandra table
# TYPE cdc_reconciliation_cassandra_rows gauge
cdc_reconciliation_cassandra_rows{table="users"} 1000000
cdc_reconciliation_cassandra_rows{table="orders"} 5000000

# HELP cdc_reconciliation_postgres_rows Total rows in PostgreSQL table
# TYPE cdc_reconciliation_postgres_rows gauge
cdc_reconciliation_postgres_rows{table="users"} 999950
cdc_reconciliation_postgres_rows{table="orders"} 5000000

# HELP cdc_reconciliation_mismatches_total Count of mismatches by type
# TYPE cdc_reconciliation_mismatches_total counter
cdc_reconciliation_mismatches_total{table="users",type="MISSING_IN_POSTGRES"} 30
cdc_reconciliation_mismatches_total{table="users",type="DATA_MISMATCH"} 10

# HELP cdc_reconciliation_jobs_completed_total Reconciliation job outcomes
# TYPE cdc_reconciliation_jobs_completed_total counter
cdc_reconciliation_jobs_completed_total{table="users",status="COMPLETED"} 156
cdc_reconciliation_jobs_completed_total{table="users",status="FAILED"} 2

# HELP cdc_reconciliation_duration_seconds Time to complete reconciliation
# TYPE cdc_reconciliation_duration_seconds histogram
cdc_reconciliation_duration_seconds_bucket{table="users",le="10"} 45
cdc_reconciliation_duration_seconds_bucket{table="users",le="30"} 120
cdc_reconciliation_duration_seconds_bucket{table="users",le="60"} 150
cdc_reconciliation_duration_seconds_bucket{table="users",le="+Inf"} 156
cdc_reconciliation_duration_seconds_sum{table="users"} 4200
cdc_reconciliation_duration_seconds_count{table="users"} 156
```

---

## Error Responses

All endpoints may return these common error responses:

### 401 Unauthorized
```json
{
  "error": "UNAUTHORIZED",
  "message": "Invalid or missing API key"
}
```

### 429 Too Many Requests
```json
{
  "error": "RATE_LIMIT_EXCEEDED",
  "message": "Rate limit exceeded. Try again in 60 seconds.",
  "retry_after": 60
}
```

### 500 Internal Server Error
```json
{
  "error": "INTERNAL_SERVER_ERROR",
  "message": "An unexpected error occurred",
  "request_id": "req-abc123",
  "contact": "support@company.com"
}
```

---

## Authentication

All endpoints require API key authentication via header:

```
Authorization: Bearer <api-key>
```

API keys can be generated via `/auth/api-keys` endpoint (separate auth service).

---

## Webhooks (Future Enhancement)

Future versions may support webhook notifications for:
- Reconciliation job completion
- High drift detected
- Reconciliation job failures

**Webhook Payload Example**:
```json
{
  "event": "reconciliation.drift_detected",
  "timestamp": "2025-11-20T14:02:15Z",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "table": "users",
    "drift_percentage": 5.2,
    "severity": "CRITICAL"
  }
}
```

---

## Contract Testing

Contract tests should validate:
- Request/response schema compliance
- HTTP status code correctness
- Error response format consistency
- Pagination behavior
- Filter parameter combinations

**Test Framework**: pytest with `requests` library and JSON schema validation

**Sample Test**:
```python
def test_trigger_reconciliation_contract():
    response = requests.post(
        "http://localhost:8080/api/v1/reconciliation/trigger",
        json={"tables": ["users"], "validation_strategy": "CHECKSUM"},
        headers={"Authorization": "Bearer test-api-key"}
    )
    assert response.status_code == 202
    data = response.json()
    assert "job_ids" in data
    assert isinstance(data["job_ids"], list)
    assert len(data["job_ids"]) == 1
```

---

**Version**: 1.0.0
**Last Updated**: 2025-11-20
