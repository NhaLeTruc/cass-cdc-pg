# Quickstart: Cassandra-to-PostgreSQL CDC Pipeline

**Purpose**: Get the CDC pipeline running locally on your laptop in under 10 minutes.

**Prerequisites**:
- Docker 20+ and Docker Compose v2 installed
- 16GB RAM, 4 CPU cores (minimum)
- 20GB free disk space

---

## 1. Clone and Setup (2 minutes)

```bash
# Clone repository
git checkout 001-cass-cdc-pg

# Verify Docker Compose v2
docker compose version  # Should show "Docker Compose version v2.x.x"

# Build worker image (first time only, ~5 minutes)
docker compose build cdc-worker
```

---

## 2. Start Infrastructure (3 minutes)

```bash
# Start all services (Cassandra, Kafka, PostgreSQL, Redis, monitoring stack)
docker compose up -d

# Wait for services to be healthy (check every 10 seconds)
watch -n 10 'docker compose ps'

# Expected output after ~2 minutes:
# NAME                STATUS              PORTS
# cassandra           Up (healthy)        0.0.0.0:9042->9042/tcp
# kafka               Up (healthy)        0.0.0.0:9092->9092/tcp
# postgres            Up (healthy)        0.0.0.0:5432->5432/tcp
# redis               Up (healthy)        0.0.0.0:6379->6379/tcp
# vault               Up                  0.0.0.0:8200->8200/tcp
# prometheus          Up                  0.0.0.0:9090->9090/tcp
# grafana             Up                  0.0.0.0:3000->3000/tcp
# jaeger              Up                  0.0.0.0:16686->16686/tcp
# debezium-connect    Up                  0.0.0.0:8083->8083/tcp
# cdc-worker          Up                  0.0.0.0:8080->8080/tcp
```

---

## 3. Initialize Pipeline (2 minutes)

### 3.1 Create Cassandra Keyspace and Table

```bash
# Connect to Cassandra
docker compose exec cassandra cqlsh

# Run CQL commands
CREATE KEYSPACE IF NOT EXISTS test_keyspace
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

CREATE TABLE IF NOT EXISTS test_keyspace.users (
    user_id uuid PRIMARY KEY,
    email text,
    name text,
    age int,
    created_at timestamp
) WITH cdc = {'enabled': true};

# Insert sample data
INSERT INTO test_keyspace.users (user_id, email, name, age, created_at)
VALUES (uuid(), 'alice@example.com', 'Alice', 30, toTimestamp(now()));

INSERT INTO test_keyspace.users (user_id, email, name, age, created_at)
VALUES (uuid(), 'bob@example.com', 'Bob', 25, toTimestamp(now()));

# Exit cqlsh
exit
```

### 3.2 Create PostgreSQL Target Table

```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U cdc_user -d warehouse

# Create table
CREATE TABLE IF NOT EXISTS users (
    user_id uuid PRIMARY KEY,
    email text NOT NULL,
    name text,
    age integer,
    created_at timestamptz NOT NULL,
    _cdc_updated_at timestamptz DEFAULT now()
);

# Create index
CREATE INDEX IF NOT EXISTS users_email_idx ON users(email);

# Exit psql
\q
```

### 3.3 Configure Debezium Connector

```bash
# Register Cassandra CDC connector with Kafka Connect
curl -X POST http://localhost:8083/connectors \
  -H "Content-Type: application/json" \
  -d '{
    "name": "cassandra-cdc-connector",
    "config": {
      "connector.class": "io.debezium.connector.cassandra.CassandraConnector",
      "tasks.max": "1",
      "cassandra.hosts": "cassandra",
      "cassandra.port": "9042",
      "cassandra.keyspace": "test_keyspace",
      "cassandra.table.whitelist": "test_keyspace.users",
      "kafka.topic.prefix": "cassandra",
      "snapshot.mode": "initial",
      "key.converter": "org.apache.kafka.connect.json.JsonConverter",
      "value.converter": "org.apache.kafka.connect.json.JsonConverter",
      "key.converter.schemas.enable": "false",
      "value.converter.schemas.enable": "false"
    }
  }'

# Verify connector is running
curl http://localhost:8083/connectors/cassandra-cdc-connector/status | jq
# Expected: {"name":"cassandra-cdc-connector","connector":{"state":"RUNNING"},...}
```

---

## 4. Verify Replication (1 minute)

### 4.1 Check Kafka Topics

```bash
# List Kafka topics (should see cassandra.test_keyspace.users)
docker compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Consume messages from CDC topic
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic cassandra.test_keyspace.users \
  --from-beginning \
  --max-messages 5
```

### 4.2 Check PostgreSQL Data

```bash
# Query replicated data
docker compose exec postgres psql -U cdc_user -d warehouse -c "SELECT * FROM users;"

# Expected output:
#               user_id               |       email        | name  | age |         created_at          |      _cdc_updated_at
# ------------------------------------+--------------------+-------+-----+-----------------------------+----------------------------
#  <uuid>                             | alice@example.com  | Alice |  30 | 2025-11-20 10:00:00+00      | 2025-11-20 10:00:05+00
#  <uuid>                             | bob@example.com    | Bob   |  25 | 2025-11-20 10:00:01+00      | 2025-11-20 10:00:06+00
```

### 4.3 Test Real-Time Replication

```bash
# Insert new record in Cassandra
docker compose exec cassandra cqlsh -e "
INSERT INTO test_keyspace.users (user_id, email, name, age, created_at)
VALUES (uuid(), 'charlie@example.com', 'Charlie', 35, toTimestamp(now()));
"

# Wait 5 seconds, then check PostgreSQL
sleep 5
docker compose exec postgres psql -U cdc_user -d warehouse -c "SELECT * FROM users WHERE email = 'charlie@example.com';"

# Should see Charlie's record replicated
```

---

## 5. Access Monitoring Dashboards (1 minute)

### Grafana (Metrics Dashboards)
- URL: http://localhost:3000
- Login: admin / admin
- Navigate to: Dashboards → CDC Pipeline Overview
- Metrics: Throughput, latency, error rates, replication lag

### Jaeger (Distributed Tracing)
- URL: http://localhost:16686
- Service: cdc-pipeline
- View end-to-end traces for sample events

### Prometheus (Raw Metrics)
- URL: http://localhost:9090
- Query: `cdc_events_processed_total`
- See metrics by table and worker

### Admin API (Health Checks)
```bash
# Liveness probe
curl http://localhost:8080/api/v1/health/liveness | jq

# Readiness probe
curl http://localhost:8080/api/v1/health/readiness | jq

# Worker status
curl http://localhost:8080/api/v1/workers | jq
```

---

## 6. Run Integration Tests (2 minutes)

```bash
# Run full test suite (unit + integration + contract tests)
docker compose -f docker-compose.test.yml up --abort-on-container-exit

# Expected output:
# ============================= test session starts ==============================
# collected 45 items
#
# tests/unit/test_validator.py ..................                           [40%]
# tests/unit/test_transformer.py .............                             [68%]
# tests/integration/test_end_to_end.py .........                           [88%]
# tests/contract/test_event_schemas.py .....                               [100%]
#
# ========================= 45 passed in 120.45s ===============================
```

---

## 7. Load Testing (Optional, 3 minutes)

```bash
# Generate 10,000 sample records in Cassandra
docker compose exec cdc-worker python scripts/generate_test_data.py \
  --keyspace test_keyspace \
  --table users \
  --count 10000

# Watch replication progress in Grafana
# Expected: ~1000 events/sec throughput, P95 latency <5 seconds

# Verify record count matches
docker compose exec postgres psql -U cdc_user -d warehouse -c "SELECT COUNT(*) FROM users;"
# Should show 10,002 (original 2 + Charlie + 10,000 generated)
```

---

## 8. Cleanup

```bash
# Stop all services
docker compose down

# Remove all data (start fresh next time)
docker compose down -v

# Remove built images
docker compose down --rmi local
```

---

## Troubleshooting

### Issue: Debezium connector not starting

**Symptom**: `curl http://localhost:8083/connectors/cassandra-cdc-connector/status` shows `FAILED`

**Solution**:
```bash
# Check connector logs
docker compose logs debezium-connect | tail -50

# Common fix: Cassandra CDC not enabled
docker compose exec cassandra cqlsh -e "ALTER TABLE test_keyspace.users WITH cdc = {'enabled': true};"

# Restart connector
curl -X POST http://localhost:8083/connectors/cassandra-cdc-connector/restart
```

### Issue: No data appearing in PostgreSQL

**Symptom**: Kafka has events, but PostgreSQL table empty

**Solution**:
```bash
# Check CDC worker logs
docker compose logs cdc-worker | tail -100

# Verify worker is consuming Kafka
curl http://localhost:8080/api/v1/metrics/pipeline | jq '.events_per_second'

# Check for errors in dead letter queue
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic cassandra.cdc.dlq \
  --from-beginning
```

### Issue: High replication lag

**Symptom**: Grafana shows lag >2 minutes

**Solution**:
```bash
# Scale up workers
docker compose up -d --scale cdc-worker=3

# Check PostgreSQL connection pool
curl http://localhost:8080/api/v1/workers | jq '.workers[] | {id: .worker_id, partitions: .assigned_partitions | length}'

# Increase batch size (edit docker-compose.yml env vars)
# CDC_BATCH_SIZE=2000  # default 1000
docker compose up -d cdc-worker
```

### Issue: Out of memory errors

**Symptom**: Worker crashes with `OutOfMemoryError`

**Solution**:
```bash
# Increase worker memory limit in docker-compose.yml
# mem_limit: 2g  # change from 1g

# Reduce batch size to lower memory footprint
# CDC_BATCH_SIZE=500

# Restart services
docker compose up -d
```

---

## Next Steps

1. **Read Architecture Docs**: `docs/architecture.md` for system design
2. **Review Runbooks**: `docs/runbooks/` for operational procedures
3. **Explore Code**: Start with `src/cdc_pipeline/workers/replication_worker.py`
4. **Write Tests**: Follow TDD methodology - see `tests/` for examples
5. **Customize Configuration**: Edit `config/dev/.env.dev` for tuning parameters

---

## Key Configuration Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Local development stack |
| `config/dev/.env.dev` | Development environment variables |
| `config/debezium/cassandra-connector.json` | Debezium connector config |
| `monitoring/prometheus/prometheus.yml` | Prometheus scrape targets |
| `monitoring/grafana/dashboards/pipeline_overview.json` | Grafana dashboard |

---

## Useful Commands

```bash
# View logs for specific service
docker compose logs -f cdc-worker

# Execute command in running container
docker compose exec cdc-worker python -m cdc_pipeline.cli status

# Restart single service
docker compose restart cdc-worker

# Check resource usage
docker stats

# Access Vault (dev mode)
export VAULT_ADDR='http://localhost:8200'
export VAULT_TOKEN='dev-root-token'
docker compose exec vault vault kv get secret/cdc-pipeline/dev/postgres
```

---

## Success Criteria Checklist

After completing quickstart, verify:

- [ ] All services healthy (`docker compose ps` shows no errors)
- [ ] Debezium connector RUNNING (`curl http://localhost:8083/connectors/...`)
- [ ] Events flowing through Kafka (`kafka-console-consumer` shows messages)
- [ ] Data replicated to PostgreSQL (row counts match)
- [ ] Grafana dashboards display metrics
- [ ] Admin API health checks return 200
- [ ] Integration tests pass (45/45 tests)
- [ ] Real-time replication working (<30 second lag)

---

**Total Time**: ~10 minutes (assuming Docker images pre-downloaded)

**Questions?** See `docs/troubleshooting.md` or open an issue.
