# CDC API - Missing Features & Infrastructure Gap Analysis

**Date**: 2025-11-26
**Analysis Type**: Production Readiness Assessment
**Total Features Analyzed**: 26 identified gaps
**Infrastructure Coverage**: 42% (11/26 features handled by existing infrastructure)

---

## Executive Summary

The CDC API server is **70% complete** with a solid foundation, but requires additional operational, monitoring, and enterprise features for production deployment. This document categorizes missing features by:

1. **Infrastructure Coverage** - What existing services (Kafka Connect, Schema Registry, Prometheus, AlertManager) already provide
2. **Implementation Priority** - Critical vs nice-to-have features
3. **Effort Estimates** - Time required for custom implementation

### Key Findings

- ✅ **Phase 1 Complete**: Critical security fixes and bug fixes (5 items)
- ✅ **11/26 Features**: Already handled by existing infrastructure (just need API wrappers)
- ⚠️ **8/26 Features**: Require thin wrapper layers (4-10 hours each)
- ❌ **7/26 Features**: Require full custom implementation (10-20+ hours each)

**Total Additional Effort**: 100-150 hours (using infrastructure) vs 250-320 hours (fully custom)

---

## Phase 1: Critical Security & Bug Fixes ✅ COMPLETE

All Phase 1 items have been successfully implemented:

### 1. SQL Injection Vulnerability Fix ✅
**File**: [`src/api/routes/gdpr.py`](../src/api/routes/gdpr.py)
**Changes**:
- Added `_validate_identifier()` function with regex validation (lines 163-182)
- Validates keyspace, table, and schema names against `^[a-zA-Z0-9_]+$`
- Prevents SQL injection via path parameters
- Replaced direct string interpolation with validated identifiers

**Impact**: HIGH - Critical security vulnerability eliminated

### 2. Metric Naming Bug Fix ✅
**File**: [`src/services/reconciliation_engine.py`](../src/services/reconciliation_engine.py)
**Changes**:
- Fixed duplicate `cdc_cdc_` prefix to `cdc_` (lines 129, 136, 143)
- Corrected metric names:
  - `cdc_reconciliation_mismatches_total`
  - `cdc_reconciliation_duration_seconds`
  - `cdc_reconciliation_jobs_completed_total`

**Impact**: MEDIUM - Metrics now correctly named and queryable

### 3. Transaction Handling & Compensating Transactions ✅
**File**: [`src/api/routes/gdpr.py`](../src/api/routes/gdpr.py)
**Changes**:
- Implemented backup-before-delete pattern (lines 74-99)
- Automatic Cassandra restore on PostgreSQL deletion failure (lines 130-156)
- Critical logging for failed restores requiring manual intervention
- Handles Cassandra's lack of transaction support

**Impact**: HIGH - Data consistency protection during failures

### 4. AlertService Pushgateway Integration ✅
**File**: [`src/services/alert_service.py`](../src/services/alert_service.py)
**Status**: Verified as already complete
**Features**:
- Prometheus Pushgateway integration (lines 150-207)
- Proper text format, timeout handling, error logging
- Alert push on drift threshold exceeded

**Impact**: MEDIUM - Alert integration already functional

### 5. Structured Logging Migration ✅
**Files Modified**:
- [`src/services/alert_service.py`](../src/services/alert_service.py) - 1 print() statement
- [`src/services/reconciliation_scheduler.py`](../src/services/reconciliation_scheduler.py) - 9 print() statements

**Changes**:
- Replaced all `print()` with `logger.info/warning/error/critical()`
- Added `exc_info=True` for error logging with stack traces
- Proper log levels for different severity events

**Impact**: MEDIUM - Production-grade logging now consistent

---

## Infrastructure Coverage Breakdown

### Existing Infrastructure (from docker-compose.yml)

```yaml
Infrastructure Components:
├── Kafka (Port 9092)
├── Kafka Connect (Port 8083) ← REST API available
├── Schema Registry (Port 8081) ← REST API available
├── Prometheus (Port 9090) ← REST API available
├── AlertManager (Port 9093) ← REST API available
├── Grafana (Port 3000) ← Dashboard UI
├── Debezium Server (Port 8000) ← Health check endpoint
├── Cassandra (Port 9042)
├── PostgreSQL (Port 5432)
└── Vault (Port 8200)
```

---

## Feature Analysis by Category

---

## ✅ TIER 1: Fully Handled by Infrastructure (11 features)

These features require **minimal custom code** - primarily API proxying/wrapping.

### 1. Connector Status & Management [KAFKA CONNECT]
**Infrastructure**: Kafka Connect REST API (Port 8083)
**Coverage**: 100%
**Existing Endpoints**:
```
GET    /connectors                    → List all connectors
GET    /connectors/{name}             → Connector details
GET    /connectors/{name}/status      → Health status
GET    /connectors/{name}/config      → Current configuration
PUT    /connectors/{name}/config      → Update configuration
PUT    /connectors/{name}/pause       → Pause connector
PUT    /connectors/{name}/resume      → Resume connector
POST   /connectors/{name}/restart     → Restart connector
GET    /connectors/{name}/tasks       → Task list
GET    /connectors/{name}/tasks/{id}/status → Task status
```

**Custom Work Required**:
- Proxy endpoints through CDC API with authentication
- Add connector health aggregation (all connectors status)
- Estimated: **2-3 hours**

---

### 2. Schema Management [SCHEMA REGISTRY]
**Infrastructure**: Confluent Schema Registry REST API (Port 8081)
**Coverage**: 90%
**Existing Endpoints**:
```
GET    /subjects                      → List all schemas
GET    /subjects/{subject}/versions   → Schema version history
GET    /subjects/{subject}/versions/{id} → Specific version
POST   /subjects/{subject}/versions   → Register new schema
DELETE /subjects/{subject}/versions/{id} → Delete version
GET    /config                        → Global compatibility config
GET    /config/{subject}              → Subject compatibility
POST   /compatibility/subjects/{subject}/versions/{id} → Test compatibility
```

**Custom Work Required**:
- Proxy endpoints with simplified naming (`/schemas` instead of `/subjects`)
- Add schema evolution visualization
- Estimated: **3-4 hours**

---

### 3. Notification/Alert Query API [ALERTMANAGER]
**Infrastructure**: Prometheus AlertManager API (Port 9093)
**Coverage**: 100%
**Existing Endpoints**:
```
GET    /api/v2/alerts                 → List active alerts
GET    /api/v2/alerts/groups          → Grouped alerts
POST   /api/v2/silences               → Create silence
GET    /api/v2/silences               → List silences
DELETE /api/v2/silence/{id}           → Delete silence
POST   /api/v2/alerts                 → Create alert (testing)
```

**Custom Work Required**:
- Proxy AlertManager API through CDC API
- Add CDC-specific alert filtering
- Estimated: **2-3 hours**

---

### 4. Advanced Metrics Endpoints [PROMETHEUS]
**Infrastructure**: Prometheus API (Port 9090)
**Coverage**: 80%
**Existing Endpoints**:
```
GET    /api/v1/query                  → Instant query
GET    /api/v1/query_range            → Range query
GET    /api/v1/series                 → Series metadata
GET    /api/v1/labels                 → Label names
GET    /api/v1/label/{name}/values    → Label values
GET    /api/v1/targets                → Scrape targets
GET    /api/v1/rules                  → Alert rules
GET    /api/v1/alerts                 → Active alerts
```

**Example PromQL Queries for CDC Metrics**:
```promql
# Latency P95
histogram_quantile(0.95, rate(cdc_latency_bucket[5m]))

# Error rate
rate(cdc_errors_total[5m])

# Throughput
rate(cdc_events_processed_total[1m])

# Consumer lag
sum(kafka_consumer_lag) by (topic)
```

**Custom Work Required**:
- Create user-friendly aggregation endpoints
- Pre-built queries for common metrics
- Estimated: **4-6 hours**

---

### 5. Pipeline Control (Partial) [KAFKA CONNECT]
**Infrastructure**: Kafka Connect API
**Coverage**: 70%
**Existing Capabilities**:
- Pause/resume individual connectors ✅
- Restart individual connectors ✅
- Get connector status ✅

**Missing**:
- Global "pause all" operation
- Global "resume all" operation
- Pipeline-wide health check

**Custom Work Required**:
- Iterate all connectors for bulk operations
- Aggregate health status
- Estimated: **2-3 hours**

---

### 6. Configuration Management (Partial) [KAFKA CONNECT]
**Infrastructure**: Kafka Connect API
**Coverage**: 60%
**Existing Capabilities**:
- Get connector configuration ✅
- Update connector configuration ✅
- Validate configuration before applying ✅

**Missing**:
- Configuration version history
- Rollback to previous configuration
- Hot-reload without restart (Kafka Connect limitation)

**Custom Work Required**:
- Store configuration history in PostgreSQL
- Implement rollback mechanism
- Estimated: **4-6 hours**

---

### 7. Performance Tuning (Partial) [KAFKA CONNECT]
**Infrastructure**: Kafka Connect API
**Coverage**: 50%
**Existing Capabilities**:
- Adjust `max.batch.size` via config ✅
- Adjust `poll.interval.ms` via config ✅
- Adjust `max.tasks` via config ✅

**Missing**:
- Automatic tuning recommendations
- Performance baseline comparison
- A/B testing framework

**Custom Work Required**:
- Performance metrics analysis
- Tuning recommendation engine
- Estimated: **8-10 hours**

---

### 8. Filtering & Transformation Rules (Partial) [KAFKA CONNECT SMTs]
**Infrastructure**: Kafka Connect Single Message Transforms (SMTs)
**Coverage**: 60%
**Existing Capabilities**:
- Add/remove transformations via config ✅
- Chain multiple transformations ✅
- Built-in SMTs (Filter, ReplaceField, etc.) ✅

**Missing**:
- Visual rule builder
- Dry-run testing endpoint
- Custom transformation hot-reload

**Custom Work Required**:
- Transformation testing API
- Rule management UI/API
- Estimated: **6-8 hours**

---

### 9. Data Validation (Schema Validation) [SCHEMA REGISTRY]
**Infrastructure**: Schema Registry
**Coverage**: 70%
**Existing Capabilities**:
- Automatic schema validation ✅
- Compatibility checking ✅
- Schema evolution rules ✅

**Missing**:
- Custom business rule validation
- Validation rule management API
- Validation history tracking

**Custom Work Required**:
- Business rule validation layer
- Validation API endpoints
- Estimated: **6-8 hours**

---

### 10. Grafana Dashboards [GRAFANA]
**Infrastructure**: Grafana (Port 3000)
**Coverage**: 90% (UI only)
**Existing Capabilities**:
- Pre-built CDC dashboards ✅
- Latency visualization ✅
- Throughput charts ✅
- Error rate monitoring ✅

**Missing**:
- Programmatic dashboard access (use Prometheus API instead)

**Custom Work Required**:
- None (use Prometheus API for programmatic access)
- Estimated: **0 hours**

---

### 11. Debezium Server Health [DEBEZIUM SERVER]
**Infrastructure**: Debezium Server (Port 8000)
**Coverage**: 30%
**Existing Endpoints**:
```
GET    /q/health                      → Basic health check
GET    /q/metrics                     → Prometheus metrics
```

**Missing**:
- Detailed connector health
- Record-level tracing
- Connection diagnostics

**Custom Work Required**:
- Enhanced health check aggregation
- Estimated: **2-3 hours**

---

## ⚠️ TIER 2: Require Thin Wrappers (8 features)

These leverage existing infrastructure but need custom orchestration/aggregation.

### 12. Bulk DLQ Operations
**Infrastructure**: PostgreSQL (DLQ records stored in `_cdc_dlq_records`)
**Coverage**: Data exists, need bulk operations
**Estimated**: **4-6 hours**

### 13. Audit Trail API
**Infrastructure**: PostgreSQL (`_cdc_audit_log` table)
**Coverage**: Audit records exist, need query API
**Estimated**: **4-6 hours**

### 14. SSE Stream Endpoint
**Infrastructure**: Kafka topics contain all events
**Coverage**: Data source exists, need SSE wrapper
**Estimated**: **4-6 hours**

### 15. Trace Lookup API
**Infrastructure**: OpenTelemetry tracing framework exists in code
**Coverage**: Need trace storage (add Jaeger) + query API
**Estimated**: **6-8 hours** (includes Jaeger setup)

### 16. Task/Job Management
**Infrastructure**: Kafka Connect task API + reconciliation jobs
**Coverage**: Need aggregation across systems
**Estimated**: **4-6 hours**

### 17. Backfill API
**Infrastructure**: Debezium snapshot capabilities
**Coverage**: Need wrapper to trigger snapshots
**Estimated**: **8-10 hours**

### 18. Batch Operations
**Infrastructure**: All data accessible in databases
**Coverage**: Need orchestration layer
**Estimated**: **6-8 hours**

### 19. Data Quality Reports
**Infrastructure**: PostgreSQL has all target data
**Coverage**: Need aggregation queries
**Estimated**: **8-10 hours**

---

## ❌ TIER 3: Require Custom Implementation (7 features)

No existing infrastructure support - full custom development needed.

### 20. Webhook/Event Subscription System
**Estimated**: **10-12 hours**
**Components**:
- Webhook registration storage
- Event filtering logic
- Delivery queue + retry mechanism
- Webhook health monitoring

### 21. Access Control & Authorization
**Estimated**: **12-14 hours**
**Components**:
- Authentication middleware (JWT/API keys)
- RBAC system (roles: admin, operator, viewer)
- Permission checks on all endpoints
- API key management

### 22. Compliance Reporting
**Estimated**: **10-12 hours**
**Components**:
- GDPR report generation
- Data residency tracking
- Audit export functionality
- Compliance dashboard

### 23. Advanced Diagnostics
**Estimated**: **10-12 hours**
**Components**:
- Record journey tracing
- Cross-system correlation
- Event replay simulation
- Connection diagnostics

### 24. Code-Level Fixes (Issues #22-25)
**Estimated**: **20-24 hours**
**Items**:
- ReconciliationScheduler improvements
- SchemaService incomplete methods
- Error handling gaps
- Connection pool management

### 25. Global Pipeline Control
**Estimated**: **2-3 hours**
**Components**:
- "Pause all" orchestration
- "Resume all" orchestration
- Global health aggregation

### 26. Configuration Hot-Reload & History
**Estimated**: **4-6 hours**
**Components**:
- Configuration version storage
- Rollback mechanism
- Change audit trail

---

## Implementation Roadmap

### Recommended Strategy: Hybrid Approach

**Total Effort**: 100-150 hours (vs 250-320 hours fully custom)

#### Week 1: API Gateway & Infrastructure Proxies (20-30 hours)
- Create unified API gateway
- Proxy Kafka Connect API → `/connectors/*`
- Proxy Schema Registry → `/schemas/*`
- Proxy AlertManager → `/alerts/*`
- Proxy Prometheus → `/metrics/*`
- Add authentication layer

#### Week 2: Thin Wrappers (30-40 hours)
- Bulk DLQ operations
- Audit trail query API
- Pipeline control endpoints
- Task/job management aggregation

#### Week 3: Custom Implementations (30-40 hours)
- Webhook system
- Advanced diagnostics
- SSE streaming endpoint
- Backfill API

#### Week 4: Enterprise Features (30-40 hours)
- RBAC implementation
- Compliance reporting
- Data quality reports
- Code-level fixes

---

## API Gateway Architecture (Recommended)

```
┌─────────────────────────────────────────────────────────────┐
│                     CDC API Gateway                         │
│                    (FastAPI on Port 8080)                   │
├─────────────────────────────────────────────────────────────┤
│  Authentication & Authorization Layer                       │
│  - JWT/API Key validation                                   │
│  - RBAC permission checks                                   │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Proxies:                                    │
│  ├── /connectors/* ────> Kafka Connect (8083)              │
│  ├── /schemas/* ───────> Schema Registry (8081)            │
│  ├── /alerts/* ────────> AlertManager (9093)               │
│  ├── /metrics/* ───────> Prometheus (9090)                 │
│  └── /health/* ────────> Debezium Server (8000)            │
├─────────────────────────────────────────────────────────────┤
│  Custom Business Logic:                                     │
│  ├── /dlq/* ───────────> DLQ Service (bulk operations)     │
│  ├── /reconciliation/* > Reconciliation Engine             │
│  ├── /audit-log/* ─────> PostgreSQL (_cdc_audit_log)       │
│  ├── /gdpr/* ──────────> GDPR Compliance (with TX)         │
│  ├── /pipeline/* ──────> Pipeline Control                  │
│  ├── /webhooks/* ──────> Webhook Management                │
│  └── /diagnostics/* ───> Advanced Diagnostics              │
├─────────────────────────────────────────────────────────────┤
│  OpenAPI Documentation                                      │
│  - Unified API docs                                         │
│  - Interactive Swagger UI                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Effort Comparison

| Approach | Effort (hours) | Pros | Cons |
|----------|---------------|------|------|
| **Fully Custom** | 250-320 | Full control, no dependencies | Reinventing wheel, high maintenance |
| **Hybrid (Recommended)** | 100-150 | Leverages infrastructure, moderate effort | Some infrastructure coupling |
| **Infrastructure-First** | 40-60 | Minimal code, fast delivery | Limited custom features, many proxies |

---

## Prioritized Feature List

### Must-Have (Production Blockers)
1. ✅ SQL injection fix
2. ✅ Transaction handling
3. ✅ Structured logging
4. Authentication & Authorization (TIER 3, #21)
5. Bulk DLQ operations (TIER 2, #12)

### Should-Have (Operational Requirements)
6. Pipeline control (TIER 1, #5)
7. Connector management proxy (TIER 1, #1)
8. Audit trail API (TIER 2, #13)
9. Advanced metrics (TIER 1, #4)
10. Alert query API (TIER 1, #3)

### Nice-to-Have (Enhanced UX)
11. SSE streaming (TIER 2, #14)
12. Webhooks (TIER 3, #20)
13. Data quality reports (TIER 2, #19)
14. Compliance reporting (TIER 3, #22)
15. Advanced diagnostics (TIER 3, #23)

---

## Next Steps

1. **Decide on Approach**: Hybrid recommended (100-150 hours)
2. **Create API Gateway**: Proxy existing infrastructure APIs
3. **Implement Authentication**: JWT or API key based
4. **Add Thin Wrappers**: Audit, DLQ, pipeline control
5. **Custom Features**: Webhooks, diagnostics, compliance

---

## Files Modified in This Session

### Phase 1 Fixes:
- ✅ `src/api/routes/gdpr.py` - SQL injection fix, transaction handling
- ✅ `src/services/reconciliation_engine.py` - Metric naming fix
- ✅ `src/services/alert_service.py` - Logging migration
- ✅ `src/services/reconciliation_scheduler.py` - Logging migration

### Documentation:
- ✅ `docs/CASSANDRA_CDC_CONNECTOR_FINDINGS.md` - Connector investigation
- ✅ `docs/API_MISSING_FEATURES_ANALYSIS.md` - This document

---

**Last Updated**: 2025-11-26
**Status**: Analysis Complete - Ready for Phase 2 Implementation
**Next Action**: Create API Gateway with infrastructure proxies
