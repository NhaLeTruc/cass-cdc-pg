# REST API Contract

**Feature**: 001-cass-cdc-pg
**Date**: 2025-11-20
**Status**: Approved

## Overview

This document defines the REST API endpoints for the CDC pipeline management, monitoring, and DLQ operations. The API follows REST principles, uses JSON for request/response payloads, and includes comprehensive error handling.

## Base URL

```
Development:  http://localhost:8080/api/v1
Production:   https://cdc-pipeline.company.com/api/v1
```

## Authentication

**Local Development**: No authentication required
**Production**: Bearer token authentication (JWT)

```http
Authorization: Bearer <jwt_token>
```

## API Endpoints

### 1. Health Check

#### GET `/health`

**Purpose**: Check overall pipeline health and component status

**Authentication**: None required

**Request**:
```http
GET /api/v1/health HTTP/1.1
Host: localhost:8080
Accept: application/json
```

**Response** (200 OK):
```json
{
  "status": "healthy",
  "timestamp": "2025-11-20T08:45:00.123456Z",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "components": {
    "cassandra": {
      "status": "healthy",
      "response_time_ms": 5,
      "connected_nodes": 3,
      "cluster_name": "cdc-cluster",
      "details": {
        "keyspace": "warehouse",
        "consistency_level": "QUORUM"
      }
    },
    "postgresql": {
      "status": "healthy",
      "response_time_ms": 8,
      "connection_pool": {
        "active": 12,
        "idle": 8,
        "max": 50
      },
      "details": {
        "database": "warehouse",
        "version": "16.1"
      }
    },
    "kafka": {
      "status": "healthy",
      "response_time_ms": 3,
      "broker_count": 3,
      "topics_healthy": 10,
      "consumer_lag": {
        "cdc-events-users": 42,
        "cdc-events-orders": 15
      }
    },
    "schema_registry": {
      "status": "healthy",
      "response_time_ms": 2,
      "registered_schemas": 5
    },
    "vault": {
      "status": "healthy",
      "response_time_ms": 4,
      "sealed": false
    }
  }
}
```

**Response** (503 Service Unavailable - degraded state):
```json
{
  "status": "degraded",
  "timestamp": "2025-11-20T08:45:00.123456Z",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "components": {
    "cassandra": {
      "status": "healthy",
      "response_time_ms": 5
    },
    "postgresql": {
      "status": "unhealthy",
      "response_time_ms": null,
      "error": "Connection refused: could not connect to server",
      "last_successful_check": "2025-11-20T08:40:00Z"
    },
    "kafka": {
      "status": "healthy",
      "response_time_ms": 3
    },
    "schema_registry": {
      "status": "healthy",
      "response_time_ms": 2
    },
    "vault": {
      "status": "healthy",
      "response_time_ms": 4
    }
  }
}
```

**Status Codes**:
- `200 OK`: All components healthy
- `503 Service Unavailable`: One or more components unhealthy

**Component Status Values**:
- `healthy`: Component responding normally
- `degraded`: Component responding but with issues (high latency, warnings)
- `unhealthy`: Component not responding or critically failed

**Contract Tests**:
```python
def test_health_endpoint_returns_all_components():
    response = requests.get("http://localhost:8080/api/v1/health")
    assert response.status_code in [200, 503]
    data = response.json()
    assert "status" in data
    assert "components" in data
    assert "cassandra" in data["components"]
    assert "postgresql" in data["components"]
    assert "kafka" in data["components"]

def test_health_endpoint_includes_kafka_consumer_lag():
    response = requests.get("http://localhost:8080/api/v1/health")
    data = response.json()
    assert "consumer_lag" in data["components"]["kafka"]
    assert isinstance(data["components"]["kafka"]["consumer_lag"], dict)
```

---

### 2. Metrics

#### GET `/metrics`

**Purpose**: Expose Prometheus metrics for monitoring and alerting

**Authentication**: None required (metrics endpoint)

**Request**:
```http
GET /api/v1/metrics HTTP/1.1
Host: localhost:8080
Accept: text/plain
```

**Response** (200 OK - Prometheus format):
```prometheus
# HELP cdc_events_processed_total Total number of CDC events processed
# TYPE cdc_events_processed_total counter
cdc_events_processed_total{table="users",operation="CREATE"} 1234
cdc_events_processed_total{table="users",operation="UPDATE"} 5678
cdc_events_processed_total{table="users",operation="DELETE"} 90
cdc_events_processed_total{table="orders",operation="CREATE"} 2345
cdc_events_processed_total{table="orders",operation="UPDATE"} 3456

# HELP cdc_processing_latency_seconds Event processing latency distribution
# TYPE cdc_processing_latency_seconds histogram
cdc_processing_latency_seconds_bucket{stage="capture",le="0.001"} 150
cdc_processing_latency_seconds_bucket{stage="capture",le="0.01"} 800
cdc_processing_latency_seconds_bucket{stage="capture",le="0.1"} 950
cdc_processing_latency_seconds_bucket{stage="capture",le="1.0"} 990
cdc_processing_latency_seconds_bucket{stage="capture",le="+Inf"} 1000
cdc_processing_latency_seconds_sum{stage="capture"} 15.234
cdc_processing_latency_seconds_count{stage="capture"} 1000

# HELP cdc_backlog_depth Number of events waiting to be processed
# TYPE cdc_backlog_depth gauge
cdc_backlog_depth{topic="cdc-events-users"} 42
cdc_backlog_depth{topic="cdc-events-orders"} 15

# HELP cdc_errors_total Total number of errors by type
# TYPE cdc_errors_total counter
cdc_errors_total{error_type="SCHEMA_MISMATCH"} 5
cdc_errors_total{error_type="TYPE_CONVERSION_ERROR"} 12
cdc_errors_total{error_type="NETWORK_TIMEOUT"} 3

# HELP cdc_dlq_events_total Total number of events sent to DLQ
# TYPE cdc_dlq_events_total counter
cdc_dlq_events_total{table="users"} 8
cdc_dlq_events_total{table="orders"} 2

# HELP cdc_schema_versions Current schema version per table
# TYPE cdc_schema_versions gauge
cdc_schema_versions{table="users"} 3
cdc_schema_versions{table="orders"} 1

# HELP cdc_checkpoint_lag_seconds Time since last checkpoint
# TYPE cdc_checkpoint_lag_seconds gauge
cdc_checkpoint_lag_seconds{table="users",partition="0"} 2.5
cdc_checkpoint_lag_seconds{table="users",partition="1"} 1.8

# HELP cdc_database_connection_pool_active Active database connections
# TYPE cdc_database_connection_pool_active gauge
cdc_database_connection_pool_active{database="cassandra"} 8
cdc_database_connection_pool_active{database="postgresql"} 12

# HELP cdc_database_connection_pool_idle Idle database connections
# TYPE cdc_database_connection_pool_idle gauge
cdc_database_connection_pool_idle{database="cassandra"} 17
cdc_database_connection_pool_idle{database="postgresql"} 8
```

**Key Metrics**:

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `cdc_events_processed_total` | Counter | table, operation | Total events processed |
| `cdc_processing_latency_seconds` | Histogram | stage | Latency per pipeline stage |
| `cdc_backlog_depth` | Gauge | topic | Events waiting to be processed |
| `cdc_errors_total` | Counter | error_type | Total errors by category |
| `cdc_dlq_events_total` | Counter | table | Events sent to DLQ |
| `cdc_schema_versions` | Gauge | table | Current schema version |
| `cdc_checkpoint_lag_seconds` | Gauge | table, partition | Time since last checkpoint |
| `cdc_database_connection_pool_active` | Gauge | database | Active DB connections |
| `cdc_database_connection_pool_idle` | Gauge | database | Idle DB connections |

**Status Codes**:
- `200 OK`: Metrics successfully generated

---

### 3. DLQ Replay

#### POST `/dlq/replay`

**Purpose**: Replay failed events from Dead Letter Queue after resolution

**Authentication**: Required (Production)

**Request**:
```http
POST /api/v1/dlq/replay HTTP/1.1
Host: localhost:8080
Content-Type: application/json
Authorization: Bearer <token>

{
  "dlq_ids": [
    "990fc833-26df-75h8-e159-88aa99882444",
    "aa1gd944-37eg-86i9-f260-99bb00993555"
  ],
  "resolution_notes": "Fixed schema mismatch by adding missing column phone_number",
  "retry_strategy": "immediate",
  "target_topic": null,
  "transform_rules": []
}
```

**Request Body Schema**:
```json
{
  "type": "object",
  "properties": {
    "dlq_ids": {
      "type": "array",
      "items": {"type": "string", "format": "uuid"},
      "minItems": 1,
      "maxItems": 1000,
      "description": "List of DLQ record IDs to replay"
    },
    "resolution_notes": {
      "type": "string",
      "maxLength": 1000,
      "description": "Human-readable explanation of how issue was resolved"
    },
    "retry_strategy": {
      "type": "string",
      "enum": ["immediate", "scheduled", "rate_limited"],
      "description": "How to replay events (immediate: all at once, scheduled: delayed, rate_limited: throttled)"
    },
    "target_topic": {
      "type": ["string", "null"],
      "description": "Override target topic (default: original topic)"
    },
    "transform_rules": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "field": {"type": "string"},
          "operation": {"type": "string", "enum": ["cast", "mask", "replace"]},
          "value": {"type": "string"}
        }
      },
      "description": "Optional transformations to apply before replay"
    }
  },
  "required": ["dlq_ids", "resolution_notes", "retry_strategy"]
}
```

**Response** (202 Accepted):
```json
{
  "replay_id": "bb2he055-48fh-97j0-g371-00cc11004666",
  "status": "queued",
  "dlq_ids_count": 2,
  "estimated_completion_time": "2025-11-20T08:46:00Z",
  "retry_strategy": "immediate",
  "message": "Replay request accepted and queued for processing"
}
```

**Response** (400 Bad Request - Invalid Request):
```json
{
  "error": "INVALID_REQUEST",
  "message": "One or more DLQ IDs do not exist",
  "details": {
    "invalid_ids": [
      "aa1gd944-37eg-86i9-f260-99bb00993555"
    ],
    "valid_ids": [
      "990fc833-26df-75h8-e159-88aa99882444"
    ]
  },
  "timestamp": "2025-11-20T08:45:00.123456Z"
}
```

**Response** (409 Conflict - Already Resolved):
```json
{
  "error": "ALREADY_RESOLVED",
  "message": "One or more DLQ records have already been resolved",
  "details": {
    "resolved_ids": [
      "990fc833-26df-75h8-e159-88aa99882444"
    ],
    "resolved_at": "2025-11-20T07:30:00Z"
  },
  "timestamp": "2025-11-20T08:45:00.123456Z"
}
```

**Status Codes**:
- `202 Accepted`: Replay request queued successfully
- `400 Bad Request`: Invalid request (unknown IDs, invalid strategy)
- `401 Unauthorized`: Missing or invalid authentication
- `409 Conflict`: DLQ records already resolved
- `500 Internal Server Error`: Replay service failure

**Retry Strategies**:

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| `immediate` | Replay all events immediately in parallel | Small batches, urgent fixes |
| `scheduled` | Schedule replay for future time (specify `scheduled_time`) | Maintenance windows |
| `rate_limited` | Replay at controlled rate (e.g., 100 events/sec) | Large batches, avoid overwhelming target |

---

#### GET `/dlq/replay/{replay_id}`

**Purpose**: Check status of replay request

**Authentication**: Required (Production)

**Request**:
```http
GET /api/v1/dlq/replay/bb2he055-48fh-97j0-g371-00cc11004666 HTTP/1.1
Host: localhost:8080
Accept: application/json
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "replay_id": "bb2he055-48fh-97j0-g371-00cc11004666",
  "status": "completed",
  "dlq_ids_count": 2,
  "started_at": "2025-11-20T08:45:05Z",
  "completed_at": "2025-11-20T08:45:12Z",
  "duration_seconds": 7,
  "results": {
    "success": 2,
    "failed": 0,
    "skipped": 0
  },
  "failed_events": [],
  "resolution_notes": "Fixed schema mismatch by adding missing column phone_number"
}
```

**Response** (200 OK - In Progress):
```json
{
  "replay_id": "bb2he055-48fh-97j0-g371-00cc11004666",
  "status": "in_progress",
  "dlq_ids_count": 100,
  "started_at": "2025-11-20T08:45:05Z",
  "progress": {
    "processed": 65,
    "remaining": 35,
    "percent_complete": 65.0
  },
  "results": {
    "success": 63,
    "failed": 2,
    "skipped": 0
  },
  "estimated_completion_time": "2025-11-20T08:46:00Z"
}
```

**Status Codes**:
- `200 OK`: Replay status retrieved
- `404 Not Found`: Replay ID does not exist

**Replay Status Values**:
- `queued`: Request accepted, waiting to start
- `in_progress`: Actively replaying events
- `completed`: All events replayed successfully
- `partially_completed`: Some events succeeded, some failed
- `failed`: Replay operation failed

---

#### GET `/dlq/records`

**Purpose**: Query DLQ records with filtering and pagination

**Authentication**: Required (Production)

**Request**:
```http
GET /api/v1/dlq/records?error_type=TYPE_CONVERSION_ERROR&resolution_status=UNRESOLVED&limit=50&offset=0 HTTP/1.1
Host: localhost:8080
Accept: application/json
Authorization: Bearer <token>
```

**Query Parameters**:

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `error_type` | String | No | Filter by error type | `SCHEMA_MISMATCH` |
| `resolution_status` | String | No | Filter by resolution status | `UNRESOLVED` |
| `table` | String | No | Filter by source table | `users` |
| `start_date` | ISO 8601 | No | Filter by date range (start) | `2025-11-01T00:00:00Z` |
| `end_date` | ISO 8601 | No | Filter by date range (end) | `2025-11-20T23:59:59Z` |
| `limit` | Integer | No | Max records to return (default 50, max 1000) | `100` |
| `offset` | Integer | No | Pagination offset (default 0) | `50` |

**Response** (200 OK):
```json
{
  "total_count": 123,
  "limit": 50,
  "offset": 0,
  "records": [
    {
      "dlq_id": "990fc833-26df-75h8-e159-88aa99882444",
      "source_table": "users",
      "error_type": "TYPE_CONVERSION_ERROR",
      "error_message": "Failed to convert column 'age' value 'not-a-number' to PostgreSQL type INTEGER",
      "retry_count": 10,
      "first_failed_at": "2025-11-20T08:30:00Z",
      "dlq_timestamp": "2025-11-20T08:35:05Z",
      "resolution_status": "UNRESOLVED",
      "original_event_summary": {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "operation": "INSERT",
        "partition_key": "{\"id\":\"user-999\"}"
      }
    },
    {
      "dlq_id": "cc3if166-59gi-a8k1-h482-11dd22115777",
      "source_table": "orders",
      "error_type": "TYPE_CONVERSION_ERROR",
      "error_message": "Failed to convert column 'total_amount' value 'invalid' to PostgreSQL type NUMERIC",
      "retry_count": 10,
      "first_failed_at": "2025-11-20T07:45:00Z",
      "dlq_timestamp": "2025-11-20T07:50:05Z",
      "resolution_status": "UNRESOLVED",
      "original_event_summary": {
        "event_id": "660f9500-f3ac-42e5-b826-557766550111",
        "operation": "UPDATE",
        "partition_key": "{\"id\":\"order-555\"}"
      }
    }
  ],
  "pagination": {
    "next_offset": 50,
    "has_more": true
  }
}
```

**Status Codes**:
- `200 OK`: Query successful
- `400 Bad Request`: Invalid query parameters

---

### 4. Configuration Management

#### GET `/config`

**Purpose**: Get current pipeline configuration

**Authentication**: Required (Production)

**Request**:
```http
GET /api/v1/config HTTP/1.1
Host: localhost:8080
Accept: application/json
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "config_id": "aa0fd944-37eg-86i9-f260-99bb00993555",
  "config_name": "warehouse-to-analytics",
  "version": 1,
  "enabled": true,
  "replication_rules": [
    {
      "source_keyspace": "warehouse",
      "source_table": "users",
      "target_schema": "public",
      "target_table": "cdc_users",
      "snapshot_mode": "initial"
    }
  ],
  "performance_tuning": {
    "max_batch_size": 1000,
    "connection_pool_size": 20
  },
  "updated_at": "2025-11-20T07:00:00Z"
}
```

---

#### PATCH `/config`

**Purpose**: Update pipeline configuration (requires restart)

**Authentication**: Required (Production)

**Request**:
```http
PATCH /api/v1/config HTTP/1.1
Host: localhost:8080
Content-Type: application/json
Authorization: Bearer <token>

{
  "performance_tuning": {
    "max_batch_size": 2000
  }
}
```

**Response** (200 OK):
```json
{
  "message": "Configuration updated successfully",
  "config_id": "aa0fd944-37eg-86i9-f260-99bb00993555",
  "version": 2,
  "requires_restart": true
}
```

---

### 5. Schema Management

#### GET `/schemas/{table}`

**Purpose**: Get schema versions for a table

**Authentication**: Optional

**Request**:
```http
GET /api/v1/schemas/users HTTP/1.1
Host: localhost:8080
Accept: application/json
```

**Response** (200 OK):
```json
{
  "keyspace": "warehouse",
  "table": "users",
  "current_version": 3,
  "versions": [
    {
      "version": 3,
      "effective_from": "2025-11-20T08:00:00Z",
      "effective_to": null,
      "change_type": "COLUMN_ADDED",
      "change_description": "Added phone_number column",
      "columns": [
        {"name": "id", "type": "text", "nullable": false},
        {"name": "username", "type": "text", "nullable": false},
        {"name": "email", "type": "text", "nullable": true},
        {"name": "phone_number", "type": "text", "nullable": true}
      ]
    },
    {
      "version": 2,
      "effective_from": "2025-06-15T10:00:00Z",
      "effective_to": "2025-11-20T08:00:00Z",
      "change_type": "COLUMN_ADDED",
      "change_description": "Added email column",
      "columns": [
        {"name": "id", "type": "text", "nullable": false},
        {"name": "username", "type": "text", "nullable": false},
        {"name": "email", "type": "text", "nullable": true}
      ]
    }
  ]
}
```

---

## Error Response Format

All error responses follow this structure:

```json
{
  "error": "ERROR_CODE",
  "message": "Human-readable error message",
  "details": {
    "field": "additional context"
  },
  "timestamp": "2025-11-20T08:45:00.123456Z",
  "request_id": "req-12345-67890"
}
```

**Common Error Codes**:
- `INVALID_REQUEST`: Malformed request body or parameters
- `UNAUTHORIZED`: Missing or invalid authentication
- `FORBIDDEN`: Insufficient permissions
- `NOT_FOUND`: Resource does not exist
- `CONFLICT`: Resource state conflict
- `INTERNAL_ERROR`: Unexpected server error
- `SERVICE_UNAVAILABLE`: Dependent service unavailable

---

## Rate Limiting

**Local Development**: No rate limiting
**Production**: 1000 requests per minute per API key

**Rate Limit Headers**:
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 987
X-RateLimit-Reset: 1732092600
```

**Response** (429 Too Many Requests):
```json
{
  "error": "RATE_LIMIT_EXCEEDED",
  "message": "API rate limit exceeded",
  "details": {
    "limit": 1000,
    "reset_at": "2025-11-20T09:00:00Z"
  }
}
```

---

## API Client Examples

### Python (requests)

```python
import requests

BASE_URL = "http://localhost:8080/api/v1"

# Health check
response = requests.get(f"{BASE_URL}/health")
print(response.json())

# Replay DLQ events
replay_request = {
    "dlq_ids": ["990fc833-26df-75h8-e159-88aa99882444"],
    "resolution_notes": "Fixed schema mismatch",
    "retry_strategy": "immediate"
}
response = requests.post(f"{BASE_URL}/dlq/replay", json=replay_request)
replay_id = response.json()["replay_id"]

# Check replay status
response = requests.get(f"{BASE_URL}/dlq/replay/{replay_id}")
print(response.json())
```

### cURL

```bash
# Health check
curl http://localhost:8080/api/v1/health

# Metrics
curl http://localhost:8080/api/v1/metrics

# Query DLQ records
curl "http://localhost:8080/api/v1/dlq/records?error_type=TYPE_CONVERSION_ERROR&limit=10"

# Replay DLQ events
curl -X POST http://localhost:8080/api/v1/dlq/replay \
  -H "Content-Type: application/json" \
  -d '{
    "dlq_ids": ["990fc833-26df-75h8-e159-88aa99882444"],
    "resolution_notes": "Fixed schema mismatch",
    "retry_strategy": "immediate"
  }'
```

---

## Contract Testing

### Pytest Examples

```python
import pytest
import requests

BASE_URL = "http://localhost:8080/api/v1"

def test_health_endpoint_returns_200_or_503():
    response = requests.get(f"{BASE_URL}/health")
    assert response.status_code in [200, 503]
    assert "status" in response.json()

def test_metrics_endpoint_returns_prometheus_format():
    response = requests.get(f"{BASE_URL}/metrics")
    assert response.status_code == 200
    assert "cdc_events_processed_total" in response.text

def test_dlq_replay_validates_input():
    invalid_request = {"dlq_ids": [], "resolution_notes": ""}
    response = requests.post(f"{BASE_URL}/dlq/replay", json=invalid_request)
    assert response.status_code == 400

def test_dlq_replay_returns_replay_id():
    valid_request = {
        "dlq_ids": ["990fc833-26df-75h8-e159-88aa99882444"],
        "resolution_notes": "Test replay",
        "retry_strategy": "immediate"
    }
    response = requests.post(f"{BASE_URL}/dlq/replay", json=valid_request)
    assert response.status_code == 202
    assert "replay_id" in response.json()
```

---

## OpenAPI Specification

Full OpenAPI 3.0 specification available at:
- Development: `http://localhost:8080/api/v1/openapi.json`
- Swagger UI: `http://localhost:8080/api/v1/docs`

---

## Summary

This REST API contract defines:
- **Health Check**: Comprehensive component health monitoring
- **Metrics**: Prometheus-format metrics for observability
- **DLQ Replay**: Failed event recovery with multiple strategies
- **Configuration**: Runtime configuration management
- **Schema Management**: Schema version history querying
- **Error Handling**: Consistent error response format
- **Authentication**: JWT bearer tokens (production)
- **Rate Limiting**: 1000 req/min per API key (production)

All endpoints support the constitution requirements for comprehensive observability, enterprise-grade error handling, and operational excellence.
