-- CDC Pipeline Control Tables

-- Schema metadata storage (FR-018)
CREATE TABLE IF NOT EXISTS _cdc_schema_metadata (
    schema_id UUID PRIMARY KEY,
    source_keyspace VARCHAR(48) NOT NULL,
    source_table VARCHAR(48) NOT NULL,
    version INTEGER NOT NULL,
    columns JSONB NOT NULL,
    primary_key JSONB NOT NULL,
    avro_schema JSONB NOT NULL,
    avro_schema_id INTEGER,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    compatibility_mode VARCHAR(20) NOT NULL,
    change_type VARCHAR(50) NOT NULL,
    change_description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_keyspace, source_table, version)
);

CREATE INDEX idx_schema_table_effective ON _cdc_schema_metadata (source_table, effective_from);

-- Checkpoint storage (FR-005)
CREATE TABLE IF NOT EXISTS _cdc_checkpoints (
    checkpoint_id UUID PRIMARY KEY,
    source_keyspace VARCHAR(48) NOT NULL,
    source_table VARCHAR(48) NOT NULL,
    partition_key_hash VARCHAR(64) NOT NULL,
    partition_key_range_start TEXT,
    partition_key_range_end TEXT,
    last_processed_event_id UUID NOT NULL,
    last_processed_timestamp_micros BIGINT NOT NULL,
    checkpoint_timestamp TIMESTAMPTZ NOT NULL,
    events_processed_count BIGINT DEFAULT 0,
    kafka_offset BIGINT,
    kafka_partition INTEGER,
    status VARCHAR(20) NOT NULL,
    last_error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_table, partition_key_hash)
);

CREATE INDEX idx_checkpoint_table_status ON _cdc_checkpoints (source_table, status);

-- DLQ record storage (FR-021)
CREATE TABLE IF NOT EXISTS _cdc_dlq_records (
    dlq_id UUID PRIMARY KEY,
    original_event JSONB NOT NULL,
    error_type VARCHAR(50) NOT NULL,
    error_message TEXT NOT NULL,
    error_stack_trace TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    first_failed_at TIMESTAMPTZ NOT NULL,
    last_retry_at TIMESTAMPTZ NOT NULL,
    dlq_timestamp TIMESTAMPTZ NOT NULL,
    source_component VARCHAR(50) NOT NULL,
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'UNRESOLVED',
    resolution_notes TEXT,
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dlq_status_timestamp ON _cdc_dlq_records (resolution_status, dlq_timestamp DESC);
CREATE INDEX idx_dlq_error_type ON _cdc_dlq_records (error_type);

-- Audit log table (Constitution VI - 1 year retention)
CREATE TABLE IF NOT EXISTS _cdc_audit_log (
    audit_id UUID PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    requester VARCHAR(100),
    table_name VARCHAR(100),
    record_identifier TEXT,
    action VARCHAR(50) NOT NULL,
    reason TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_event_timestamp ON _cdc_audit_log (event_timestamp DESC);
CREATE INDEX idx_audit_table_name ON _cdc_audit_log (table_name);

-- Auto-delete audit logs older than 1 year
CREATE OR REPLACE FUNCTION delete_old_audit_logs()
RETURNS void AS $$
BEGIN
    DELETE FROM _cdc_audit_log WHERE event_timestamp < NOW() - INTERVAL '1 year';
END;
$$ LANGUAGE plpgsql;

-- Reconciliation jobs table
CREATE TABLE IF NOT EXISTS _cdc_reconciliation_jobs (
    job_id UUID PRIMARY KEY,
    table_name VARCHAR(255) NOT NULL,
    job_type VARCHAR(50) NOT NULL,
    validation_strategy VARCHAR(50) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR(50) NOT NULL,
    cassandra_row_count BIGINT,
    postgres_row_count BIGINT,
    mismatch_count INTEGER,
    drift_percentage DECIMAL(5,2),
    validation_errors JSONB,
    alert_fired BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reconciliation_jobs_table_status ON _cdc_reconciliation_jobs(table_name, status);
CREATE INDEX idx_reconciliation_jobs_started_at ON _cdc_reconciliation_jobs(started_at);

-- Reconciliation mismatches table
CREATE TABLE IF NOT EXISTS _cdc_reconciliation_mismatches (
    mismatch_id UUID PRIMARY KEY,
    job_id UUID REFERENCES _cdc_reconciliation_jobs(job_id),
    table_name VARCHAR(255) NOT NULL,
    primary_key_value TEXT NOT NULL,
    mismatch_type VARCHAR(50) NOT NULL,
    cassandra_checksum VARCHAR(64),
    postgres_checksum VARCHAR(64),
    cassandra_data JSONB,
    postgres_data JSONB,
    detected_at TIMESTAMPTZ NOT NULL,
    resolution_status VARCHAR(50) DEFAULT 'PENDING',
    resolution_notes TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_reconciliation_mismatches_job_id ON _cdc_reconciliation_mismatches(job_id);
CREATE INDEX idx_reconciliation_mismatches_table_status ON _cdc_reconciliation_mismatches(table_name, resolution_status);

-- APScheduler jobs table
CREATE TABLE IF NOT EXISTS _apscheduler_jobs (
    id VARCHAR(191) PRIMARY KEY,
    next_run_time DOUBLE PRECISION,
    job_state BYTEA NOT NULL
);

CREATE INDEX idx_apscheduler_jobs_next_run_time ON _apscheduler_jobs(next_run_time);

-- Replicated tables (created by connectors)
CREATE TABLE IF NOT EXISTS cdc_users (
    id UUID PRIMARY KEY,
    username VARCHAR(255),
    email VARCHAR(255),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    _cdc_inserted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    _cdc_updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cdc_orders (
    id UUID PRIMARY KEY,
    user_id UUID,
    total_amount NUMERIC,
    status VARCHAR(50),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    _cdc_inserted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    _cdc_updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO cdc_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO cdc_user;
