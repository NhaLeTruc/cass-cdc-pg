"""
Prometheus metrics definitions following RED method (Rate, Errors, Duration).
See FR-026 in spec.md for complete requirements.
"""
from prometheus_client import Counter, Gauge, Histogram

# Rate: Events processed
cdc_events_processed_total = Counter(
    'cdc_events_processed_total',
    'Total number of CDC events processed',
    ['table', 'operation']
)

# Errors: Error count by type
cdc_errors_total = Counter(
    'cdc_errors_total',
    'Total number of errors encountered',
    ['error_type']
)

# Duration: Processing latency (P50, P95, P99)
cdc_processing_latency_seconds = Histogram(
    'cdc_processing_latency_seconds',
    'CDC processing latency in seconds',
    ['stage'],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

# Saturation: Backlog depth (Kafka consumer lag in event count)
cdc_backlog_depth = Gauge(
    'cdc_backlog_depth',
    'Kafka consumer lag in event count',
    ['topic']
)

# DLQ metrics
cdc_dlq_events_total = Counter(
    'cdc_dlq_events_total',
    'Total number of events moved to DLQ',
    ['table', 'error_type']
)

cdc_dlq_replay_success_total = Counter(
    'cdc_dlq_replay_success_total',
    'Total number of successful DLQ replays',
    ['table']
)

cdc_dlq_replay_failed_total = Counter(
    'cdc_dlq_replay_failed_total',
    'Total number of failed DLQ replays',
    ['table']
)

# Out-of-order event metrics
cdc_out_of_order_events_total = Counter(
    'cdc_out_of_order_events_total',
    'Total number of out-of-order events detected',
    ['table']
)

cdc_conflict_resolution_rejections_total = Counter(
    'cdc_conflict_resolution_rejections_total',
    'Total number of events rejected due to conflict resolution',
    ['table']
)

# Reconciliation metrics
cdc_reconciliation_drift_percentage = Gauge(
    'cdc_reconciliation_drift_percentage',
    'Percentage of records out of sync',
    ['table']
)

cdc_reconciliation_cassandra_rows = Gauge(
    'cdc_reconciliation_cassandra_rows',
    'Total rows in Cassandra table',
    ['table']
)

cdc_reconciliation_postgres_rows = Gauge(
    'cdc_reconciliation_postgres_rows',
    'Total rows in PostgreSQL table',
    ['table']
)

cdc_reconciliation_mismatches_total = Counter(
    'cdc_reconciliation_mismatches_total',
    'Count of mismatches by type',
    ['table', 'type']
)

cdc_reconciliation_jobs_completed_total = Counter(
    'cdc_reconciliation_jobs_completed_total',
    'Reconciliation job outcomes',
    ['table', 'status']
)

cdc_reconciliation_duration_seconds = Histogram(
    'cdc_reconciliation_duration_seconds',
    'Time to complete reconciliation',
    ['table'],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0)
)

# User Story 1 Specific Metrics (T044)

# Cassandra metrics
cassandra_connection_errors_total = Counter(
    'cassandra_connection_errors_total',
    'Total Cassandra connection errors',
    []
)

cassandra_query_duration_seconds = Histogram(
    'cassandra_query_duration_seconds',
    'Cassandra query execution time',
    ['operation'],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)
)

cassandra_active_connections = Gauge(
    'cassandra_active_connections',
    'Number of active Cassandra connections',
    []
)

# PostgreSQL metrics
postgresql_connection_errors_total = Counter(
    'postgresql_connection_errors_total',
    'Total PostgreSQL connection errors',
    []
)

postgresql_query_duration_seconds = Histogram(
    'postgresql_query_duration_seconds',
    'PostgreSQL query execution time',
    ['operation'],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)
)

postgresql_active_connections = Gauge(
    'postgresql_active_connections',
    'Number of active PostgreSQL connections',
    []
)

# Vault metrics
vault_connection_errors_total = Counter(
    'vault_connection_errors_total',
    'Total Vault connection errors',
    []
)

# Schema evolution metrics
cdc_schema_changes_total = Counter(
    'cdc_schema_changes_total',
    'Total schema changes detected',
    ['table', 'change_type']
)

cdc_schema_versions = Gauge(
    'cdc_schema_versions',
    'Current schema version by table',
    ['table']
)

# Type mapping metrics
cdc_type_conversion_errors_total = Counter(
    'cdc_type_conversion_errors_total',
    'Total type conversion errors',
    ['cassandra_type', 'postgres_type']
)

# TTL preservation metrics
cdc_ttl_records_total = Counter(
    'cdc_ttl_records_total',
    'Total records with TTL set',
    ['table']
)

cdc_ttl_expired_records_total = Counter(
    'cdc_ttl_expired_records_total',
    'Total records deleted due to TTL expiration',
    ['table']
)

# Conflict resolution metrics
cdc_events_rejected_total = Counter(
    'cdc_events_rejected_total',
    'Total events rejected by conflict resolution',
    ['table', 'reason']
)

cdc_conflict_resolution_total = Counter(
    'cdc_conflict_resolution_total',
    'Total conflict resolutions performed',
    ['resolution']
)

# Kafka Connect metrics
kafka_connect_task_failures_total = Counter(
    'kafka_connect_task_failures_total',
    'Total Kafka Connect task failures',
    ['connector']
)

kafka_connect_connector_state = Gauge(
    'kafka_connect_connector_state',
    'Connector state (1=RUNNING, 0=STOPPED/FAILED)',
    ['connector']
)
