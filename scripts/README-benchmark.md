# CDC Pipeline Performance Benchmark

This directory contains performance benchmarking tools for the Cassandra to PostgreSQL CDC pipeline.

## Overview

The `benchmark.py` script uses [Locust](https://locust.io/) to simulate high-volume data changes in Cassandra and measure end-to-end replication latency to PostgreSQL.

## Features

- **Load Generation**: Simulates 10,000+ events/second with realistic workload distribution
- **Latency Measurement**: Measures P50, P95, P99 end-to-end replication latency
- **Operation Mix**: 70% INSERT, 20% UPDATE, 10% DELETE operations
- **Verification**: Samples 1% of events to verify successful replication
- **Prometheus Metrics**: Exposes metrics for monitoring and alerting
- **HTML Reports**: Generates detailed performance reports

## Prerequisites

### Required Services

1. **Cassandra** - Running and accessible with CDC enabled
2. **PostgreSQL** - Running and accessible with CDC tables created
3. **Kafka Connect** - Pipeline deployed and running

### Python Dependencies

Install Locust and required dependencies:

```bash
# Using Poetry (recommended)
poetry add --group dev locust

# Or using pip
pip install locust cassandra-driver psycopg2-binary prometheus-client
```

## Configuration

Configure the benchmark using environment variables:

### Database Connections

```bash
export CASSANDRA_HOST=localhost
export CASSANDRA_PORT=9042
export CASSANDRA_KEYSPACE=warehouse
export CASSANDRA_USERNAME=cassandra
export CASSANDRA_PASSWORD=cassandra

export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=warehouse
export POSTGRES_USER=cdc_user
export POSTGRES_PASSWORD=cdc_password
```

### Benchmark Parameters

```bash
export TARGET_EVENTS_PER_SECOND=10000
export MAX_LATENCY_P95_MS=2000
export MAX_LATENCY_P99_MS=5000
export VERIFICATION_SAMPLE_RATE=0.01  # 1% sample rate
```

## Usage

### Basic Usage

Run with Locust web UI (recommended for development):

```bash
locust -f scripts/benchmark.py --host=http://localhost
```

Then open http://localhost:8089 in your browser and configure:
- **Number of users**: 100
- **Spawn rate**: 10 users/second

### Headless Mode

Run without web UI (recommended for CI/CD):

```bash
locust -f scripts/benchmark.py \
  --host=http://localhost \
  --headless \
  --users 100 \
  --spawn-rate 10 \
  --run-time 5m
```

### With HTML Report

Generate detailed HTML report:

```bash
locust -f scripts/benchmark.py \
  --host=http://localhost \
  --headless \
  --users 100 \
  --spawn-rate 10 \
  --run-time 10m \
  --html benchmark-report.html \
  --csv benchmark-results
```

### Target 10K Events/Second

To achieve 10,000 events/second:

```bash
# Calculate: 10,000 events/sec ÷ wait_time
# With wait_time=1s per user, need 10,000 users
# But that's impractical, so use fewer users with faster wait time

locust -f scripts/benchmark.py \
  --host=http://localhost \
  --headless \
  --users 500 \
  --spawn-rate 50 \
  --run-time 10m
```

### Distributed Load Generation

For very high loads, use distributed mode:

**Master node:**
```bash
locust -f scripts/benchmark.py --host=http://localhost --master
```

**Worker nodes (run on multiple machines):**
```bash
locust -f scripts/benchmark.py --host=http://localhost --worker --master-host=<master-ip>
```

## Workload Distribution

The benchmark simulates realistic CDC workload:

- **70% INSERT** - New record creation
- **20% UPDATE** - Existing record modification
- **10% DELETE** - Record deletion
- **5% VERIFY** - Replication verification (background task)

## Metrics

### Prometheus Metrics Exported

The benchmark exposes metrics on port 9090 (configurable):

- `benchmark_events_written_total{operation}` - Counter of events written to Cassandra
- `benchmark_events_verified_total{status}` - Counter of events verified in PostgreSQL
- `benchmark_replication_latency_seconds` - Histogram of end-to-end latency
- `benchmark_cassandra_errors_total{error_type}` - Counter of Cassandra errors
- `benchmark_postgres_errors_total{error_type}` - Counter of PostgreSQL errors
- `benchmark_verification_queue_depth` - Gauge of pending verifications

### Locust Built-in Metrics

- **Requests per second** - Throughput
- **Response time percentiles** - P50, P95, P99 latency
- **Failure rate** - Error percentage
- **Number of users** - Concurrent load

## Performance Targets

From `plan.md` and `spec.md`:

| Metric | Target | Measured By |
|--------|--------|-------------|
| Throughput | ≥10,000 events/sec | Locust RPS |
| P95 Latency | ≤2 seconds | `benchmark_replication_latency_seconds` |
| P99 Latency | ≤5 seconds | `benchmark_replication_latency_seconds` |
| Error Rate | <0.1% | Locust failure rate |

## Interpreting Results

### Success Criteria

✅ **PASS** if:
- Sustained throughput ≥10,000 events/second
- P95 latency ≤2 seconds
- P99 latency ≤5 seconds
- Failure rate <0.1%
- Verification success rate >99%

❌ **FAIL** if:
- Throughput drops below target
- Latency exceeds thresholds
- High error rate
- Events not replicating to PostgreSQL

### Common Issues

**High Latency**
- Check Kafka consumer lag: `kafka-consumer-groups --describe`
- Verify Kafka Connect workers healthy: `curl http://localhost:8083/connectors`
- Check PostgreSQL write performance: `pg_stat_statements`

**Low Throughput**
- Increase Locust users: `--users 1000`
- Check Cassandra write performance: `nodetool tpstats`
- Verify Kafka partition count matches parallelism

**High Failure Rate**
- Check Cassandra connection pool settings
- Verify network connectivity
- Review error logs in `benchmark.log`

## Example Output

```
================================
CDC Pipeline Performance Benchmark Starting
================================
Target: 10000 events/second
Cassandra: localhost:9042
PostgreSQL: localhost:5432
Max P95 Latency: 2000ms
Max P99 Latency: 5000ms
Verification Sample Rate: 1.0%
================================

[2025-11-25 10:00:00] Starting load test
[2025-11-25 10:00:10] 100 users spawned
[2025-11-25 10:01:00] RPS: 9,847 | P95: 1,234ms | P99: 2,456ms | Failures: 0.02%
[2025-11-25 10:02:00] RPS: 10,234 | P95: 1,345ms | P99: 2,567ms | Failures: 0.01%

================================
CDC Pipeline Performance Benchmark Complete
================================
Total Requests: 6,000,000
Total Failures: 120
Failure Rate: 0.02%
Average Response Time: 456.78ms
Unverified Events: 234
================================
```

## Advanced Usage

### Custom Workload Profile

Edit `benchmark.py` to adjust task weights:

```python
@task(50)  # Change from 70 to 50
def insert_user(self):
    ...

@task(40)  # Change from 20 to 40
def update_user(self):
    ...
```

### Custom Verification Logic

Modify `verify_replication()` to check specific fields:

```python
def verify_user_data(self, user_id: uuid.UUID, expected_data: Dict) -> bool:
    query = "SELECT * FROM cdc_users WHERE user_id = %s"
    cursor.execute(query, (str(user_id),))
    actual = cursor.fetchone()
    return actual['email'] == expected_data['email']
```

### Integration with CI/CD

Add to GitHub Actions:

```yaml
- name: Run Performance Benchmark
  run: |
    locust -f scripts/benchmark.py \
      --headless \
      --users 100 \
      --spawn-rate 10 \
      --run-time 5m \
      --html benchmark-report.html \
      --exit-code-on-error
  env:
    CASSANDRA_HOST: cassandra
    POSTGRES_HOST: postgres
```

## Troubleshooting

### Connection Errors

```bash
# Test Cassandra connectivity
cqlsh -e "SELECT * FROM system.local"

# Test PostgreSQL connectivity
psql -h localhost -U cdc_user -d warehouse -c "SELECT 1"
```

### Import Errors

```bash
# Verify all dependencies installed
poetry install --with dev

# Or with pip
pip install -r requirements.txt
```

### Out of Memory

If Locust crashes with OOM:

```bash
# Reduce user count
locust -f scripts/benchmark.py --users 50

# Or increase available memory
export LOCUST_MAX_REQUEST_SIZE=10485760
```

## References

- [Locust Documentation](https://docs.locust.io/)
- [Performance Testing Best Practices](https://docs.locust.io/en/stable/writing-a-locustfile.html)
- [Cassandra Performance Tuning](https://cassandra.apache.org/doc/latest/operating/performance/)
- [PostgreSQL Performance Tips](https://wiki.postgresql.org/wiki/Performance_Optimization)
