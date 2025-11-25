# Runbook: Schema Mismatch Between Cassandra and PostgreSQL

**Alert**: None (detected via connector errors or reconciliation drift)
**Severity**: Medium to Critical (depending on impact)
**SLO Impact**: May cause data loss if events rejected

## Symptoms

- Kafka Connect JDBC Sink errors: `Column does not exist` or `Type mismatch`
- Events routed to DLQ topic (`dlq-events`)
- `cdc_dlq_events_total` metric increasing
- Reconciliation jobs show DATA_MISMATCH or MISSING_IN_POSTGRES
- `cdc_type_conversion_errors_total` metric increasing

## Diagnosis

### Step 1: Identify the Mismatch

Check DLQ for schema-related errors:
```bash
curl "http://localhost:8080/dlq/records?error_type=SCHEMA_MISMATCH&limit=10" | jq '.'
```

### Step 2: Compare Schemas

Get Cassandra schema:
```bash
docker exec -it cdc-cassandra cqlsh -e "DESCRIBE TABLE warehouse.users"
```

Get PostgreSQL schema:
```bash
docker exec -it cdc-postgres psql -U admin -d warehouse -c "\d+ cdc_users"
```

### Step 3: Check Schema Registry

Query registered schemas:
```bash
curl http://localhost:8081/subjects/cdc-events-users-value/versions/latest | jq '.schema | fromjson'
```

## Root Causes & Solutions

### Cause 1: New Column Added to Cassandra (Not in PostgreSQL)

**Symptom**: `ERROR: column "phone_number" of relation "cdc_users" does not exist`

**Solution**:
```bash
# Option 1: Enable auto.evolve in JDBC Sink (recommended)
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/config \
  -H "Content-Type: application/json" \
  -d '{
    "auto.evolve": "true"
  }'

# Wait for connector to auto-create column, then restart
curl -X POST http://localhost:8083/connectors/postgres-sink-connector/restart

# Option 2: Manually alter PostgreSQL table
docker exec -it cdc-postgres psql -U admin -d warehouse << 'EOF'
ALTER TABLE cdc_users
ADD COLUMN phone_number VARCHAR(255);
EOF

# Replay DLQ events
curl -X POST http://localhost:8080/dlq/replay \
  -H "Content-Type: application/json" \
  -d '{"error_type": "SCHEMA_MISMATCH", "limit": 1000}'
```

### Cause 2: Column Type Changed in Cassandra

**Symptom**: `ERROR: column "age" is of type integer but expression is of type text`

**Solution**:
```bash
# This requires careful handling as type changes are not backward compatible

# Step 1: Pause sink connector
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/pause

# Step 2: Alter PostgreSQL table type
docker exec -it cdc-postgres psql -U admin -d warehouse << 'EOF'
BEGIN;
-- Convert existing data first
ALTER TABLE cdc_users ALTER COLUMN age TYPE TEXT USING age::TEXT;
COMMIT;
EOF

# Step 3: Resume connector
curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/resume

# Step 4: Replay DLQ events
curl -X POST http://localhost:8080/dlq/replay \
  -H "Content-Type: application/json" \
  -d '{"error_type": "TYPE_CONVERSION_ERROR", "limit": 1000}'
```

### Cause 3: Column Dropped from Cassandra (Still in PostgreSQL)

**Symptom**: No direct error, but reconciliation shows DATA_MISMATCH

**Solution**:
```bash
# Safe approach: Keep column in PostgreSQL (backward compatible)
# Data will be NULL for new records

# Alternative: Drop column if confirmed not needed
docker exec -it cdc-postgres psql -U admin -d warehouse << 'EOF'
ALTER TABLE cdc_users DROP COLUMN deprecated_column;
EOF
```

### Cause 4: Complex Type Mapping Issue (UDT, Map, Set)

**Symptom**: `ERROR: cannot cast type jsonb to user_defined_type`

**Solution**:
```bash
# Cassandra UDTs are mapped to PostgreSQL JSONB by default

# Check current PostgreSQL column type
docker exec -it cdc-postgres psql -U admin -d warehouse -c "
SELECT column_name, data_type, udt_name
FROM information_schema.columns
WHERE table_name = 'cdc_users' AND column_name = 'address';
"

# If type is not JSONB, alter to JSONB
docker exec -it cdc-postgres psql -U admin -d warehouse << 'EOF'
ALTER TABLE cdc_users ALTER COLUMN address TYPE JSONB USING address::JSONB;
EOF
```

## Prevention

### Enable Schema Evolution in Connectors

Update connector configuration:
```json
{
  "auto.create": "true",
  "auto.evolve": "true",
  "schema.evolution": "BACKWARD"
}
```

### Implement Schema Change Workflow

1. **Pre-deployment validation**:
   ```bash
   # Test schema change in dev environment first
   ./scripts/validate-schema-change.sh warehouse.users
   ```

2. **Update PostgreSQL schema before Cassandra**:
   ```bash
   # Add column to PostgreSQL first (backward compatible)
   docker exec -it cdc-postgres psql -U admin -d warehouse -c "
   ALTER TABLE cdc_users ADD COLUMN new_column VARCHAR(255);
   "

   # Then add to Cassandra
   docker exec -it cdc-cassandra cqlsh -e "
   ALTER TABLE warehouse.users ADD new_column text;
   "
   ```

3. **Monitor schema metadata table**:
   ```sql
   SELECT * FROM _cdc_schema_metadata
   WHERE source_table = 'users'
   ORDER BY version DESC LIMIT 5;
   ```

### Set Up Schema Change Alerts

Add Prometheus alert for schema changes:
```yaml
- alert: SchemaChangeDetected
  expr: increase(cdc_schema_changes_total[5m]) > 0
  labels:
    severity: info
  annotations:
    summary: "Schema change detected for {{ $labels.table }}"
    description: "{{ $labels.change_type }} change detected"
```

## Escalation

If schema mismatch cannot be resolved:

1. **Pause pipeline** to prevent data loss:
   ```bash
   curl -X PUT http://localhost:8083/connectors/postgres-sink-connector/pause
   ```

2. **Engage DBA team** for PostgreSQL schema changes

3. **Create schema migration plan**:
   - Document current vs desired schema
   - Test migration in staging
   - Schedule maintenance window

4. **Communicate impact** to stakeholders

## Post-Resolution Validation

```bash
# 1. Verify connector running
curl http://localhost:8083/connectors/postgres-sink-connector/status

# 2. Check DLQ cleared
curl http://localhost:8080/dlq/records?error_type=SCHEMA_MISMATCH

# 3. Run reconciliation
curl -X POST http://localhost:8080/reconciliation/trigger \
  -H "Content-Type: application/json" \
  -d '{"tables": ["users"], "validation_strategy": "CHECKSUM"}'

# 4. Verify no drift
curl "http://localhost:8080/reconciliation/jobs?table=users&limit=1"
```

## Related Runbooks

- [Connector Failure](./connector-failure.md)
- [Type Conversion Errors](./type-conversion-errors.md)
