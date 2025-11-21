# Cassandra to PostgreSQL CDC Pipeline

A production-grade Change Data Capture (CDC) pipeline that replicates data from Apache Cassandra to PostgreSQL in near real-time.

## Features

- **Real-time Replication**: Captures and replicates data changes within 2 seconds (P95 latency)
- **High Throughput**: Processes 10,000+ events per second per instance
- **Exactly-Once Delivery**: Guarantees no data loss or duplication
- **Schema Evolution**: Automatically handles schema changes
- **Production Ready**: Comprehensive monitoring, error handling, and security
- **Locally Testable**: Full Docker Compose stack for development

## Architecture

```
Cassandra CDC → Debezium → Kafka → JDBC Sink → PostgreSQL
                    ↓
            Schema Registry
                    ↓
        Monitoring (Prometheus, Grafana, Jaeger)
```

## Quick Start

### Prerequisites

- Docker Desktop (8GB RAM, 4 CPU cores)
- Python 3.11+
- Poetry

### One-Command Setup

```bash
make setup-local
```

This will:
1. Start all services (Cassandra, PostgreSQL, Kafka, monitoring)
2. Deploy CDC connectors
3. Generate test data
4. Verify replication

### Manual Setup

```bash
# Install dependencies
make install

# Start infrastructure
make start

# Deploy connectors
make deploy-connectors

# Generate test data
make generate-data

# Check health
make health
```

### Access Services

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Jaeger**: http://localhost:16686
- **Kafka Connect**: http://localhost:8083
- **REST API**: http://localhost:8080

## Development

### Run Tests

```bash
# All tests
make test

# Unit tests only
make test-unit

# Integration tests
make test-integration

# With coverage
make test-coverage
```

### Code Quality

```bash
# Lint code
make lint

# Auto-fix issues
make lint-fix

# Security scan
make security
```

### Local Development Workflow

1. Make code changes
2. Run tests: `make test`
3. Check linting: `make lint`
4. Commit changes (pre-commit hooks run automatically)

## Project Structure

```
cass-cdc-pg/
├── src/                    # Application code
│   ├── connectors/         # Custom Kafka Connect components
│   ├── models/             # Pydantic data models
│   ├── repositories/       # Data access layer
│   ├── services/           # Business logic
│   ├── monitoring/         # Observability
│   ├── api/                # REST API (FastAPI)
│   ├── config/             # Configuration management
│   └── utils/              # Shared utilities
├── tests/                  # Test suite
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration tests
│   └── contract/           # Contract tests
├── docker/                 # Docker configuration
│   ├── cassandra/          # Cassandra setup
│   ├── postgres/           # PostgreSQL setup
│   ├── kafka/              # Kafka configuration
│   ├── vault/              # Vault configuration
│   ├── monitoring/         # Grafana dashboards
│   └── connectors/         # Kafka Connect connectors
├── config/                 # Environment-specific config
├── scripts/                # Utility scripts
└── helm/                   # Kubernetes deployment

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and customize:

```bash
# Cassandra
CASSANDRA_HOST=localhost
CASSANDRA_PORT=9042

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=warehouse

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Vault (production)
VAULT_ADDR=http://localhost:8200
```

### Connector Configuration

Connector configurations are in `docker/connectors/`:
- `cassandra-source.json`: Debezium Cassandra source
- `postgres-sink.json`: JDBC PostgreSQL sink

## Monitoring

### Metrics

Key metrics exposed at `/metrics`:
- `cdc_events_processed_total`: Total events processed
- `cdc_processing_latency_seconds`: Processing latency (P50, P95, P99)
- `cdc_backlog_depth`: Kafka consumer lag
- `cdc_errors_total`: Error count by type

### Dashboards

Pre-configured Grafana dashboards:
- **CDC Pipeline**: Overall pipeline health and performance
- **Kafka**: Kafka broker and consumer metrics
- **Databases**: Cassandra and PostgreSQL connection pools

### Tracing

Distributed tracing via Jaeger shows end-to-end request flows:
- Cassandra capture → Kafka produce → PostgreSQL write

## Troubleshooting

### Common Issues

**Services not starting**
```bash
# Check Docker resources (needs 8GB RAM)
docker stats

# Check logs
make logs
```

**Replication lag**
```bash
# Check consumer lag
docker-compose exec kafka kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group connect-cdc-sink
```

**Schema mismatch errors**
```bash
# Check DLQ for failed events
curl http://localhost:8080/dlq/records
```

See [quickstart.md](specs/001-cass-cdc-pg/quickstart.md) for detailed troubleshooting.

## Production Deployment

### Kubernetes

```bash
# Deploy with Helm
helm install cdc-pipeline ./helm -f values-prod.yaml

# Check status
kubectl get pods -n cdc
```

### Configuration

Production configuration requires:
- HashiCorp Vault for secrets
- TLS certificates for all connections
- Prometheus AlertManager for alerts

See [deployment checklist](docs/deployment-checklist.md).

## Performance

### Benchmarks

```bash
make benchmark
```

Target performance:
- **Throughput**: ≥10,000 events/sec per instance
- **Latency**: P95 ≤2 seconds end-to-end
- **Availability**: 99.9% uptime

### Tuning

Key tuning parameters in `docker/connectors/`:
- `max.batch.size`: Batch size for source connector
- `batch.size`: Batch size for sink connector
- `connection.pool.size`: Database connection pool

## Contributing

1. Create feature branch
2. Write tests first (TDD)
3. Implement feature
4. Ensure all tests pass: `make test`
5. Run linters: `make lint`
6. Submit pull request

## License

Copyright 2025 CDC Team. All rights reserved.

## Support

- Documentation: See `specs/001-cass-cdc-pg/` directory
- Issues: Report bugs via GitHub Issues
- Architecture: See [plan.md](specs/001-cass-cdc-pg/plan.md)
