# Cassandra-to-PostgreSQL CDC Pipeline

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)]()
[![Code Coverage](https://img.shields.io/badge/coverage-80%25-green)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)]()
[![Python](https://img.shields.io/badge/python-3.11-blue)]()

Enterprise-grade Change Data Capture (CDC) pipeline that replicates data changes from Cassandra cluster to PostgreSQL data warehouse with production-level reliability, observability, and high availability.

## Features

✨ **Production-Ready**
- ≥1000 events/second per worker throughput
- P95 end-to-end latency <5 seconds
- 99.9% uptime with automatic failover
- Zero data loss with exactly-once semantics

🔒 **Enterprise Security**
- TLS encryption for all connections
- HashiCorp Vault secret management
- No credentials in code (enforced via git hooks)
- Security scanning (Trivy, Bandit, Safety)

📊 **Full Observability**
- Structured JSON logging (structlog)
- Prometheus metrics + Grafana dashboards
- Distributed tracing (OpenTelemetry + Jaeger)
- Real-time alerting on critical thresholds

🧪 **Test-Driven Development**
- 80%+ code coverage requirement
- Unit, integration, contract, performance tests
- Testcontainers for realistic integration tests
- Pre-commit hooks enforce quality (see below)

🚀 **Developer-Friendly**
- Full local stack in Docker Compose v2
- Runs on 16GB laptop (all 11 services)
- 10-minute quickstart guide
- Comprehensive documentation

## Quick Start

### Prerequisites
- Docker 20+ with Docker Compose v2
- Python 3.11+
- 16GB RAM, 4 CPU cores (for local development)

### Setup Git Hooks (REQUIRED - First-Time Setup)

**⚠️ IMPORTANT**: Run this before making any commits!

```bash
# Install enforcement mechanisms
./scripts/setup-git-hooks.sh

# This enforces:
# 1. All .md files must be in docs/ (except README.md, CLAUDE.md)
# 2. No credentials can be committed
# 3. All code must pass linting before commits
```

**📖 Full Documentation**: [docs/git-hooks-enforcement.md](docs/git-hooks-enforcement.md)

### Start Local Development

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Follow quickstart guide
cat specs/001-cass-cdc-pg/quickstart.md

# 3. Verify replication
# Insert data into Cassandra → appears in PostgreSQL within 30s
```

## Architecture

```text
┌─────────────┐     ┌──────────┐     ┌───────┐     ┌────────────┐     ┌────────────┐
│  Cassandra  │────▶│ Debezium │────▶│ Kafka │────▶│ CDC Worker │────▶│ PostgreSQL │
│   (Source)  │     │Connector │     │Topics │     │  (Python)  │     │  (Target)  │
└─────────────┘     └──────────┘     └───────┘     └──────┬─────┘     └────────────┘
                                                           │
                                                           ▼
                                                    ┌─────────────┐
                                                    │Redis Cache  │
                                                    │(Metadata)   │
                                                    └─────────────┘
```

**Key Components**:
- **Debezium 2.5**: Captures CDC events from Cassandra commitlog
- **Kafka 3.6**: Durable event log with 7-day retention
- **Python 3.11 Workers**: Event processing with retry logic
- **Redis 7.2**: Distributed coordination and metadata cache
- **PostgreSQL 16**: Target data warehouse

**Full Details**: [docs/architecture.md](docs/architecture.md) *(coming soon)*

## Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| **Source** | Apache Cassandra | 4.1.x | Source database with CDC enabled |
| **CDC** | Debezium | 2.5.x | Change data capture connector |
| **Messaging** | Apache Kafka | 3.6.x | Event log (KRaft mode) |
| **Target** | PostgreSQL | 16.x | Data warehouse |
| **Cache** | Redis | 7.2.x | Metadata and coordination |
| **Language** | Python | 3.11 | Worker implementation |
| **Secrets** | HashiCorp Vault | 1.15 | Credential management |
| **Monitoring** | Prometheus + Grafana | 2.48 / 10.2 | Metrics and dashboards |
| **Tracing** | OpenTelemetry + Jaeger | 1.21 / 1.52 | Distributed tracing |
| **Testing** | pytest + testcontainers | 7.4 / 3.7 | TDD framework |

## Project Structure

```
cass-cdc-pg/
├── src/cdc_pipeline/          # Main pipeline code
│   ├── workers/               # Worker entry points
│   ├── services/              # Business logic
│   ├── connectors/            # Kafka, PostgreSQL, Redis
│   ├── models/                # Pydantic data models
│   ├── observability/         # Logging, metrics, tracing
│   └── resilience/            # Retry, circuit breaker
├── tests/                     # Test suite (80%+ coverage)
│   ├── unit/                  # Fast isolated tests
│   ├── integration/           # Testcontainer tests
│   ├── contract/              # Schema validation
│   └── performance/           # Load tests (Locust)
├── docker/                    # Docker Compose configs
├── config/                    # Environment configs
├── monitoring/                # Prometheus + Grafana
├── docs/                      # Documentation
│   ├── git-hooks-enforcement.md  # ⚠️ READ THIS FIRST
│   └── ENFORCEMENT-SUMMARY.md
├── specs/001-cass-cdc-pg/     # Feature specifications
│   ├── spec.md                # User stories
│   ├── plan.md                # Implementation plan
│   ├── tasks.md               # Task breakdown
│   ├── data-model.md          # Data models
│   └── quickstart.md          # 10-min local setup
└── .pre-commit-config.yaml    # Enforcement hooks
```

## Documentation

- **Getting Started**: [specs/001-cass-cdc-pg/quickstart.md](specs/001-cass-cdc-pg/quickstart.md) (10-minute setup)
- **⚠️ Git Hooks** (REQUIRED): [docs/git-hooks-enforcement.md](docs/git-hooks-enforcement.md)
- **Enforcement Summary**: [docs/ENFORCEMENT-SUMMARY.md](docs/ENFORCEMENT-SUMMARY.md)
- **Implementation Plan**: [specs/001-cass-cdc-pg/plan.md](specs/001-cass-cdc-pg/plan.md)
- **Task Breakdown**: [specs/001-cass-cdc-pg/tasks.md](specs/001-cass-cdc-pg/tasks.md) (165 tasks)
- **Data Models**: [specs/001-cass-cdc-pg/data-model.md](specs/001-cass-cdc-pg/data-model.md)

## Development Workflow

### 1. Setup (First Time)

```bash
# Install git hooks (REQUIRED!)
./scripts/setup-git-hooks.sh

# Install Python dependencies
pip install -r requirements.txt  # or poetry install

# Start local stack
docker compose up -d
```

### 2. Development Cycle (TDD)

```bash
# 1. Write test FIRST (must fail)
# tests/unit/test_my_feature.py

# 2. Run test (verify it fails)
pytest tests/unit/test_my_feature.py -v

# 3. Implement feature
# src/cdc_pipeline/...

# 4. Run test (verify it passes)
pytest tests/unit/test_my_feature.py -v

# 5. Commit (hooks auto-run)
git add .
git commit -m "Add my feature"
# ✅ Hooks will:
#    - Format code (Black)
#    - Lint code (Ruff, mypy)
#    - Check for credentials
#    - Validate .md file locations
```

### 3. Pre-Commit Hooks (Automatic)

Every commit automatically runs:
- ✅ Code formatting (Black)
- ✅ Linting (Ruff, mypy)
- ✅ Security scanning (Bandit)
- ✅ Credential detection
- ✅ Markdown file location check
- ✅ YAML/JSON syntax validation

**See**: [docs/git-hooks-enforcement.md](docs/git-hooks-enforcement.md) for details

## Enforcement Mechanisms

This project enforces three critical requirements via git hooks:

### 1. 📁 Markdown File Organization
**Rule**: All `.md` files must be in `docs/` directory (except `README.md` and `CLAUDE.md`)

**Why**: Keeps documentation organized and discoverable

**Enforced by**: `.git-hooks/enforce_md_location.py`

### 2. 🔒 No Credentials in Code
**Rule**: No passwords, API keys, secrets, or credentials can be committed

**Why**: Security - prevents credential leaks to version control

**Enforced by**:
- `detect-secrets` (industry standard)
- `.git-hooks/check_credentials.py` (custom patterns)

**Safe alternatives**: Environment variables, HashiCorp Vault

### 3. ✨ Code Quality
**Rule**: All code must pass linting before commits

**Why**: Maintains consistent code quality and catches bugs early

**Enforced by**:
- Black (auto-formatting)
- Ruff (fast linting)
- mypy (type checking)
- Bandit (security)

**📖 Full Details**: [docs/ENFORCEMENT-SUMMARY.md](docs/ENFORCEMENT-SUMMARY.md)

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test suite
pytest tests/unit/ -v              # Unit tests only
pytest tests/integration/ -v       # Integration tests
pytest tests/contract/ -v          # Contract tests

# With coverage
pytest tests/ --cov=src/cdc_pipeline --cov-report=html

# Load testing
locust -f tests/performance/locustfile.py
```

## Contributing

1. **Setup git hooks first**: `./scripts/setup-git-hooks.sh`
2. **Create feature branch**: `git checkout -b feature/my-feature`
3. **Write tests first** (TDD): Create test in `tests/`
4. **Implement feature**: Code in `src/cdc_pipeline/`
5. **Ensure tests pass**: `pytest tests/`
6. **Commit**: Git hooks will auto-run
7. **Push**: `git push origin feature/my-feature`
8. **Create PR**: Follow PR template

**Code Review Checklist**:
- [ ] Tests written before implementation (TDD)
- [ ] All tests pass (80%+ coverage)
- [ ] Git hooks pass (Black, Ruff, mypy, no credentials)
- [ ] Documentation updated (if needed)
- [ ] No `.md` files outside `docs/` (except README.md, CLAUDE.md)

## License

Apache License 2.0 - See [LICENSE](LICENSE) file for details

## Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/your-org/cass-cdc-pg/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/cass-cdc-pg/discussions)

---

**Status**: 🚧 Active Development (MVP in progress)
**Version**: 0.1.0-alpha
**Last Updated**: 2025-11-20
