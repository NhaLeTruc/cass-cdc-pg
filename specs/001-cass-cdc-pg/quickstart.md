# Quickstart Guide: Cassandra CDC to PostgreSQL Pipeline

**Feature**: 001-cass-cdc-pg
**Date**: 2025-11-20
**Target Audience**: Developers setting up local environment

## Prerequisites

### Required Software

| Software | Version | Installation |
|----------|---------|--------------|
| Docker | 24.0+ | https://docs.docker.com/get-docker/ |
| Docker Compose | 2.23+ | Bundled with Docker Desktop |
| Git | 2.30+ | https://git-scm.com/downloads |
| Python | 3.11+ | https://www.python.org/downloads/ |
| Make | Any | macOS: `xcode-select --install`, Linux: `apt install build-essential` |

### System Requirements

- **RAM**: 8GB minimum (4.5GB allocated to Docker)
- **CPU**: 4 cores minimum
- **Disk**: 10GB free space
- **OS**: macOS 11+, Ubuntu 20.04+, Windows 11 with WSL2

### Verify Prerequisites

```bash
# Check Docker version
docker --version
# Expected: Docker version 24.0.0 or higher

# Check Docker Compose version
docker compose --version
# Expected: Docker Compose version 2.23.0 or higher

# Check Docker is running
docker ps
# Expected: No errors (empty table is fine)

# Check Python version
python3 --version
# Expected: Python 3.11.0 or higher

# Check available memory
docker info | grep "Total Memory"
# Expected: 8GB or higher
```

---

## Quick Start (5 Minutes)

### 1. Clone Repository

```bash
# Clone the CDC pipeline repository
git clone https://github.com/company/cass-cdc-pg.git
cd cass-cdc-pg

# Checkout feature branch (if not already on it)
git checkout 001-cass-cdc-pg
```

### 2. One-Command Setup (Recommended)

```bash
# Run the automated setup script - it does everything!
bash scripts/setup_local_env.sh

# This script will:
# 1. Check prerequisites (Docker, Python, etc.)
# 2. Create .env from .env.example
# 3. Start all Docker services
# 4. Wait for services to become healthy
# 5. Deploy Kafka Connect connectors
# 6. Generate 10,000 test records
# 7. Verify replication is working

# Expected final output:
# ==========================================
# Local CDC Environment Ready!
# ==========================================
#
# Services:
#   • Cassandra:       localhost:9042
#   • PostgreSQL:      localhost:5432
#   • Kafka:           localhost:9092 (internal), localhost:9093 (external)
#   • Schema Registry: http://localhost:8081
#   • Kafka Connect:   http://localhost:8083
#   • Vault:           http://localhost:8200 (token: dev-root-token)
#   • Prometheus:      http://localhost:9090
#   • Grafana:         http://localhost:3000 (admin/admin)
#   • Jaeger:          http://localhost:16686
```

**Total Setup Time**: ~3-5 minutes (longer on first run due to image downloads)

### 3. Manual Setup (Alternative)

If you prefer manual control, follow these steps:

```bash
# Start entire CDC pipeline stack
docker compose up -d

# Wait for services to become healthy (~60-90 seconds)
bash scripts/health-check-cassandra.sh
bash scripts/health-check-postgres.sh
bash scripts/health-check-kafka.sh
bash scripts/health-check-vault.sh

# Generate test data
python3 scripts/generate_test_data.py --users 10000 --orders 10000 --sessions 1000

# Expected output:
# ✓ Connected to Cassandra at localhost:9042
# Generating 10000 users...
#   Progress: 10000/10000 users (100%)
# ✓ Generated 10000 users
# Generating 10000 orders...
#   Progress: 10000/10000 orders (100%)
# ✓ Generated 10000 orders
# ...
```

### 4. Verify Services

```bash
# Check all containers are running
docker compose ps

# Expected output:
# NAME                   STATUS              PORTS
# cdc-cassandra          Up (healthy)        9042->9042
# cdc-postgres           Up (healthy)        5432->5432
# cdc-kafka              Up                  9092->9092, 9093->9093
# cdc-schema-registry    Up                  8081->8081
# cdc-kafka-connect      Up                  8083->8083
# cdc-vault              Up                  8200->8200
# cdc-prometheus         Up                  9090->9090
# cdc-grafana            Up                  3000->3000
# cdc-jaeger             Up                  16686->16686, 5775->5775, ...

# Or use individual health check scripts
bash scripts/health-check-cassandra.sh  # ✓ Cassandra is healthy
bash scripts/health-check-postgres.sh   # ✓ PostgreSQL is healthy
bash scripts/health-check-kafka.sh      # ✓ Kafka is healthy
bash scripts/health-check-vault.sh      # ✓ Vault is healthy and unsealed
```

### 5. Verify Replication

```bash
# Check data replicated to PostgreSQL
docker exec -it cdc-postgres psql -U cdc_user -d warehouse -c "
  SELECT COUNT(*) FROM cdc_users;
"

# Expected output:
#  count
# --------
#  10000
# (1 row)

# View sample replicated data
docker exec -it cdc-postgres psql -U cdc_user -d warehouse -c "
  SELECT id, username, email, created_at
  FROM cdc_users
  ORDER BY created_at DESC
  LIMIT 5;
"

# Expected output: 5 user records with realistic data
```

**If you see 10,000+ records in PostgreSQL, replication is working!**

---

## Detailed Setup

### Directory Structure

```
cass-cdc-pg/
├── docker/
│   ├── docker-compose.yml           # Main orchestration file
│   ├── .env.example                 # Template for environment variables
│   ├── cassandra/
│   │   ├── cassandra.yaml           # Cassandra configuration
│   │   ├── init-schema.cql          # Keyspace and table creation
│   │   └── enable-cdc.sh            # Enable CDC on tables
│   ├── postgres/
│   │   ├── postgresql.conf          # PostgreSQL configuration
│   │   └── init-db.sql              # Schema creation
│   ├── kafka/
│   │   └── create-topics.sh         # Kafka topic creation
│   ├── vault/
│   │   ├── config.hcl               # Vault configuration
│   │   └── init-secrets.sh          # Populate secrets
│   ├── monitoring/
│   │   ├── prometheus.yml           # Prometheus scrape config
│   │   └── grafana/
│   │       └── dashboards/          # Pre-built dashboards
│   └── connectors/
│       ├── cassandra-source.json    # Debezium source connector
│       └── postgres-sink.json       # JDBC sink connector
├── src/                             # Pipeline source code (future)
├── tests/                           # Test suite (future)
├── Makefile                         # Convenience commands
└── README.md                        # Project documentation
```

### Environment Configuration

```bash
# Copy environment template
cp docker/.env.example docker/.env

# Edit environment variables (optional for local dev)
nano docker/.env
```

**Key Environment Variables** (defaults work for local dev):

```bash
# Cassandra
CASSANDRA_CLUSTER_NAME=cdc-cluster
CASSANDRA_DC=dc1
CASSANDRA_SEEDS=cassandra

# PostgreSQL
POSTGRES_DB=warehouse
POSTGRES_USER=admin
POSTGRES_PASSWORD=secret

# Kafka
KAFKA_BROKER_ID=1
KAFKA_ADVERTISED_HOST_NAME=localhost

# Vault (dev mode)
VAULT_DEV_ROOT_TOKEN_ID=root

# Monitoring
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
```

### Service Startup Order

Docker Compose handles dependencies automatically, but for reference:

1. **Infrastructure**: Vault, Zookeeper (optional)
2. **Data Stores**: Cassandra, PostgreSQL, Kafka
3. **Schema Registry**: After Kafka is healthy
4. **Kafka Connect**: After Cassandra, PostgreSQL, Kafka, Schema Registry
5. **Monitoring**: Prometheus, Grafana, Jaeger
6. **Init Container**: Deploy connectors after Kafka Connect

### Makefile Commands

```bash
# Start all services
make start

# Stop all services (preserves data)
make stop

# Restart all services
make restart

# Remove all services and volumes (clean slate)
make clean

# View logs from all services
make logs

# View logs from specific service
make logs-cassandra
make logs-postgres
make logs-kafka-connect

# Check service health
make health

# Generate test data (100 records)
make generate-data

# Run full test suite
make test

# Deploy connectors
make deploy-connectors

# View connector status
make connector-status

# Delete connectors
make delete-connectors
```

---

## Test Data Generation

### Manual Insert (Cassandra)

```bash
# Connect to Cassandra
docker exec -it cdc-cassandra cqlsh

# Insert data
cqlsh> USE warehouse;
cqlsh:warehouse> INSERT INTO users (id, username, email, created_at, updated_at)
               > VALUES ('user-123', 'testuser', 'test@example.com', toTimestamp(now()), toTimestamp(now()));

# Update data
cqlsh:warehouse> UPDATE users
               > SET email = 'newemail@example.com', updated_at = toTimestamp(now())
               > WHERE id = 'user-123';

# Delete data
cqlsh:warehouse> DELETE FROM users WHERE id = 'user-123';

# Verify data
cqlsh:warehouse> SELECT * FROM users LIMIT 10;
```

### Automated Test Data Script

```bash
# Generate test data with default counts (10,000 users, 10,000 orders, 1,000 sessions)
python3 scripts/generate_test_data.py

# Generate custom counts
python3 scripts/generate_test_data.py --users 50000 --orders 25000 --sessions 5000

# Generate with specific batch size for performance
python3 scripts/generate_test_data.py --users 100000 --batch-size 500

# Clear existing data before generating
python3 scripts/generate_test_data.py --clear

# Skip data generation during setup
bash scripts/setup_local_env.sh --no-data
```

**Script Options**:
- `--host`: Cassandra host (default: localhost)
- `--port`: Cassandra port (default: 9042)
- `--users`: Number of users to generate (default: 10000)
- `--orders`: Number of orders to generate (default: 10000)
- `--sessions`: Number of sessions to generate (default: 1000)
- `--batch-size`: Batch size for inserts (default: 100)
- `--clear`: Clear existing data before generating

**Expected Output**:

```
✓ Connected to Cassandra at localhost:9042

============================================================
GENERATING TEST DATA
============================================================
Generating 10000 users...
  Progress: 10000/10000 users (100%)
✓ Generated 10000 users
Generating 10000 orders...
  Progress: 10000/10000 orders (100%)
✓ Generated 10000 orders
Generating 1000 sessions...
  Progress: 1000/1000 sessions (100%)
✓ Generated 1000 sessions

============================================================
Verifying data counts...
  users: 10000 records
  orders: 10000 records
  sessions: 1000 records
============================================================

✓ Test data generation complete!
```

---

## Verification Steps

### 1. Verify Cassandra CDC Enabled

```bash
# Check CDC directory exists and is writable
docker exec -it cdc-cassandra ls -la /var/lib/cassandra/cdc_raw/

# Expected output:
# drwxr-xr-x  2 cassandra cassandra 4096 Nov 20 08:45 .
# (Should show some .log files after data insertion)

# Verify CDC enabled on table
docker exec -it cdc-cassandra cqlsh -e "DESCRIBE TABLE warehouse.users;"

# Expected output should include:
# AND cdc = true
```

### 2. Verify Kafka Topics Created

```bash
# List all Kafka topics
docker exec -it cdc-kafka kafka-topics --list --bootstrap-server localhost:9092

# Expected output:
# cdc-events-users
# cdc-events-orders
# dlq-events
# schema-changes
# connect-offsets
# connect-configs
# connect-status

# Describe specific topic
docker exec -it cdc-kafka kafka-topics --describe --topic cdc-events-users --bootstrap-server localhost:9092

# Check topic message count
docker exec -it cdc-kafka kafka-run-class kafka.tools.GetOffsetShell \
  --broker-list localhost:9092 \
  --topic cdc-events-users
```

### 3. Verify Connectors Deployed

```bash
# List connectors
curl http://localhost:8083/connectors | jq

# Expected output:
# ["cassandra-source-connector", "postgresql-sink-connector"]

# Check connector status
curl http://localhost:8083/connectors/cassandra-source-connector/status | jq

# Expected output:
# {
#   "name": "cassandra-source-connector",
#   "connector": {
#     "state": "RUNNING",
#     "worker_id": "kafka-connect:8083"
#   },
#   "tasks": [
#     {
#       "id": 0,
#       "state": "RUNNING",
#       "worker_id": "kafka-connect:8083"
#     }
#   ]
# }
```

### 4. Verify Schema Registry

```bash
# List registered schemas
curl http://localhost:8081/subjects | jq

# Expected output:
# ["cdc-events-users-value", "cdc-events-orders-value"]

# Get schema details
curl http://localhost:8081/subjects/cdc-events-users-value/versions/latest | jq
```

### 5. Verify End-to-End Replication

```bash
# Insert record in Cassandra
docker exec -it cdc-cassandra cqlsh -e "
  INSERT INTO warehouse.users (id, username, email, created_at)
  VALUES ('e2e-test', 'e2etester', 'e2e@test.com', toTimestamp(now()));
"

# Wait 5 seconds
sleep 5

# Check PostgreSQL
docker exec -it cdc-postgres psql -U admin -d warehouse -c "
  SELECT * FROM cdc_users WHERE id = 'e2e-test';
"

# Expected output:
#     id     | username  |      email      |          created_at
# -----------+-----------+-----------------+-------------------------------
#  e2e-test  | e2etester | e2e@test.com    | 2025-11-20 08:45:10.123+00
```

---

## Monitoring and Observability

### Access Web UIs

| Service | URL | Credentials | Purpose |
|---------|-----|-------------|---------|
| Grafana | http://localhost:3000 | admin / admin | Metrics dashboards |
| Prometheus | http://localhost:9090 | None | Metrics query |
| Jaeger | http://localhost:16686 | None | Distributed tracing |
| Kafka Connect | http://localhost:8083 | None | Connector management |
| Schema Registry | http://localhost:8081 | None | Schema management |

### Grafana Dashboards

1. Open http://localhost:3000 (admin / admin)
2. Navigate to Dashboards
3. Pre-configured dashboards:
   - **CDC Pipeline Overview**: High-level metrics (throughput, latency, errors)
   - **Kafka Metrics**: Broker health, topic lag, consumer groups
   - **Database Metrics**: Cassandra and PostgreSQL connection pools, query latency

### View Prometheus Metrics

```bash
# Query metrics via command line
curl http://localhost:9090/api/v1/query?query=cdc_events_processed_total

# Or open Prometheus UI
open http://localhost:9090/graph

# Example queries:
# - cdc_events_processed_total
# - rate(cdc_events_processed_total[5m])
# - cdc_backlog_depth
# - cdc_processing_latency_seconds_bucket
```

### View Distributed Traces

1. Open http://localhost:16686
2. Select Service: `cdc-pipeline`
3. Click "Find Traces"
4. Click on a trace to see:
   - Cassandra read time
   - Kafka publish time
   - PostgreSQL write time
   - Total end-to-end latency

---

## Troubleshooting

### Services Won't Start

**Problem**: `docker compose up` fails or containers exit immediately

**Solutions**:

```bash
# Check Docker resources (need 4.5GB RAM, 4 CPUs)
docker info | grep -E "CPUs|Total Memory"

# Increase Docker memory/CPU in Docker Desktop:
# Settings → Resources → Adjust Memory to 8GB, CPUs to 4

# Check for port conflicts
lsof -i :9042  # Cassandra
lsof -i :5432  # PostgreSQL
lsof -i :9092  # Kafka

# Kill conflicting processes or change ports in .env

# Check logs for specific service
docker compose logs cassandra
docker compose logs postgres
```

### Cassandra CDC Not Working

**Problem**: Data inserted in Cassandra but not appearing in Kafka

**Solutions**:

```bash
# Verify CDC enabled on table
docker exec -it cdc-cassandra cqlsh -e "DESCRIBE TABLE warehouse.users;"
# Should show: AND cdc = true

# Check CDC directory has files
docker exec -it cdc-cassandra ls -la /var/lib/cassandra/cdc_raw/
# Should show .log files after inserts

# Check Debezium connector logs
docker compose logs kafka-connect | grep -i cassandra

# Restart connector
curl -X POST http://localhost:8083/connectors/cassandra-source-connector/restart
```

### Kafka Consumer Lag Growing

**Problem**: Events piling up in Kafka, not reaching PostgreSQL

**Solutions**:

```bash
# Check consumer lag
docker exec -it cdc-kafka kafka-consumer-groups \
  --bootstrap-server localhost:9092 \
  --describe --group connect-cluster

# Check JDBC sink connector status
curl http://localhost:8083/connectors/postgresql-sink-connector/status | jq

# If connector failed, check error:
docker compose logs kafka-connect | grep -i error

# Check PostgreSQL connection
docker exec -it cdc-postgres pg_isready

# Increase batch size for faster consumption (edit connector config):
curl -X PUT http://localhost:8083/connectors/postgresql-sink-connector/config \
  -H "Content-Type: application/json" \
  -d '{"batch.size": "2000", ...}'
```

### Schema Registry Errors

**Problem**: "Schema not found" or compatibility errors

**Solutions**:

```bash
# List registered schemas
curl http://localhost:8081/subjects | jq

# Delete incompatible schema (allows re-registration)
curl -X DELETE http://localhost:8081/subjects/cdc-events-users-value/versions/latest

# Change compatibility mode (if needed)
curl -X PUT http://localhost:8081/config/cdc-events-users-value \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  -d '{"compatibility": "NONE"}'
```

### PostgreSQL Table Not Created

**Problem**: JDBC sink connector running but PostgreSQL table doesn't exist

**Solutions**:

```bash
# Check if auto.create is enabled
curl http://localhost:8083/connectors/postgresql-sink-connector/config | jq .auto.create

# If false, manually create table
docker exec -it cdc-postgres psql -U admin -d warehouse -f /docker-entrypoint-initdb.d/init-db.sql

# Or enable auto.create:
curl -X PUT http://localhost:8083/connectors/postgresql-sink-connector/config \
  -H "Content-Type: application/json" \
  -d '{"auto.create": "true", ...}'
```

### High Memory Usage

**Problem**: Docker containers consuming > 4GB RAM

**Solutions**:

```bash
# Check memory usage per container
docker stats --no-stream

# Tune Cassandra heap (docker-compose.yml):
# MAX_HEAP_SIZE=512M
# HEAP_NEWSIZE=100M

# Tune Kafka memory (docker-compose.yml):
# KAFKA_HEAP_OPTS=-Xmx512M -Xms512M

# Restart services after changes
docker compose restart
```

---

## Running Tests

### Unit Tests

```bash
# Run all unit tests
make test-unit

# Or with pytest directly:
pytest tests/unit/ -v
```

### Integration Tests

```bash
# Run integration tests (requires Docker)
make test-integration

# Or with pytest:
pytest tests/integration/ -v --tb=short
```

### Contract Tests

```bash
# Run contract tests (API/Kafka schemas)
make test-contract

# Or with pytest:
pytest tests/contract/ -v
```

### End-to-End Test

```bash
# Run full E2E test
make test-e2e

# This will:
# 1. Start all services
# 2. Insert test data
# 3. Verify replication
# 4. Check metrics
# 5. Test DLQ replay
# 6. Clean up
```

---

## Common Development Tasks

### Add New Table for Replication

1. **Create Cassandra table with CDC enabled**:
```sql
CREATE TABLE warehouse.products (
    id text PRIMARY KEY,
    name text,
    price decimal,
    created_at timestamp
) WITH cdc = true;
```

2. **Add replication rule to source connector**:
```bash
# Edit docker/connectors/cassandra-source.json
# Add "warehouse.products" to cassandra.table.include.list
```

3. **Restart connector**:
```bash
curl -X POST http://localhost:8083/connectors/cassandra-source-connector/restart
```

4. **Verify topic created**:
```bash
docker exec -it cdc-kafka kafka-topics --list --bootstrap-server localhost:9092 | grep products
# Expected: cdc-events-products
```

### View Kafka Messages

```bash
# Consume messages from topic (plain text)
docker exec -it cdc-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic cdc-events-users \
  --from-beginning \
  --max-messages 10

# Consume with Avro deserialization
docker exec -it cdc-kafka kafka-avro-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic cdc-events-users \
  --from-beginning \
  --property schema.registry.url=http://localhost:8081 \
  --max-messages 10
```

### Simulate Failures for Testing

```bash
# Stop PostgreSQL to test retry logic
docker compose stop postgres

# Insert data in Cassandra (will fail to replicate)
docker exec -it cdc-cassandra cqlsh -e "
  INSERT INTO warehouse.users (id, username, email, created_at)
  VALUES ('retry-test', 'retryuser', 'retry@test.com', toTimestamp(now()));
"

# Check errors in connector logs
docker compose logs kafka-connect | tail -50

# Restart PostgreSQL
docker compose start postgres

# Wait for auto-retry and verify replication
sleep 30
docker exec -it cdc-postgres psql -U admin -d warehouse -c "SELECT * FROM cdc_users WHERE id = 'retry-test';"
```

---

## Cleanup

### Stop Services (Keep Data)

```bash
# Stop all containers but keep volumes
docker compose down

# Or with Makefile:
make stop
```

### Full Cleanup (Delete Everything)

```bash
# Remove containers, networks, and volumes
docker compose down -v

# Or with Makefile:
make clean

# Verify cleanup
docker volume ls | grep cdc
# Should return nothing
```

### Partial Cleanup (Specific Service)

```bash
# Remove only Cassandra data
docker volume rm cdc_cassandra-data

# Remove only PostgreSQL data
docker volume rm cdc_postgres-data
```

---

## Next Steps

After completing this quickstart:

1. **Read Implementation Plan**: Review `/home/bob/WORK/cass-cdc-pg/specs/001-cass-cdc-pg/plan.md`
2. **Explore Data Model**: Review `/home/bob/WORK/cass-cdc-pg/specs/001-cass-cdc-pg/data-model.md`
3. **Review API Contracts**: Check `/home/bob/WORK/cass-cdc-pg/specs/001-cass-cdc-pg/contracts/`
4. **Run Full Test Suite**: `make test` to ensure everything works
5. **Customize Configuration**: Edit `docker/.env` and connector configs
6. **Add Your Tables**: Follow "Add New Table for Replication" guide above

---

## Getting Help

- **Documentation**: `/home/bob/WORK/cass-cdc-pg/specs/001-cass-cdc-pg/`
- **Logs**: `docker compose logs <service-name>`
- **Health Checks**: `make health` or `curl http://localhost:8080/api/v1/health`
- **Metrics**: http://localhost:3000 (Grafana)
- **Traces**: http://localhost:16686 (Jaeger)

---

## Summary

This quickstart guide covered:
- Prerequisites and system requirements
- 5-minute quick start (start services, insert data, verify replication)
- Detailed setup and configuration
- Test data generation
- Verification steps for each component
- Monitoring and observability tools
- Comprehensive troubleshooting
- Running test suites
- Common development tasks
- Cleanup procedures

**You should now have a fully functional local CDC pipeline running!**
