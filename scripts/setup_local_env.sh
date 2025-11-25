#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "CDC Pipeline Local Environment Setup"
echo "=========================================="
echo ""

cd "$PROJECT_ROOT"

check_prerequisites() {
    echo "Checking prerequisites..."

    local missing_tools=()

    if ! command -v docker &> /dev/null; then
        missing_tools+=("docker")
    fi

    if ! command -v docker compose &> /dev/null; then
        missing_tools+=("docker-compose")
    fi

    if ! command -v python3 &> /dev/null; then
        missing_tools+=("python3")
    fi

    if [ ${#missing_tools[@]} -gt 0 ]; then
        echo "✗ Missing required tools: ${missing_tools[*]}"
        echo ""
        echo "Please install the following:"
        for tool in "${missing_tools[@]}"; do
            case $tool in
                docker)
                    echo "  - Docker: https://docs.docker.com/get-docker/"
                    ;;
                docker-compose)
                    echo "  - Docker Compose: https://docs.docker.com/compose/install/"
                    ;;
                python3)
                    echo "  - Python 3.11+: https://www.python.org/downloads/"
                    ;;
            esac
        done
        exit 1
    fi

    if ! docker info &> /dev/null; then
        echo "✗ Docker daemon is not running. Please start Docker."
        exit 1
    fi

    local docker_version
    docker_version=$(docker version --format '{{.Server.Version}}' 2>/dev/null)
    echo "  ✓ Docker ${docker_version}"

    local compose_version
    compose_version=$(docker compose version --short 2>/dev/null)
    echo "  ✓ Docker Compose ${compose_version}"

    local python_version
    python_version=$(python3 --version | awk '{print $2}')
    echo "  ✓ Python ${python_version}"

    echo ""
}

setup_env_file() {
    echo "Setting up environment configuration..."

    if [ ! -f .env ]; then
        if [ -f .env.example ]; then
            cp .env.example .env
            echo "  ✓ Created .env from .env.example"
        else
            echo "  ⚠ Warning: .env.example not found, skipping .env creation"
        fi
    else
        echo "  ✓ .env already exists"
    fi

    echo ""
}

cleanup_existing_environment() {
    echo "Cleaning up any existing environment..."

    if docker compose ps -q 2>/dev/null | grep -q .; then
        echo "  Stopping existing services..."
        docker compose down --volumes --remove-orphans
        echo "  ✓ Stopped and removed existing containers"
    else
        echo "  ✓ No existing services to clean up"
    fi

    echo ""
}

start_services() {
    echo "Starting Docker Compose services..."
    echo "This may take several minutes on first run (downloading images)..."
    echo ""

    docker compose up -d

    echo ""
    echo "  ✓ Services started"
    echo ""
}

wait_for_services() {
    echo "Waiting for services to become healthy..."
    echo ""

    local services=("cassandra" "postgres" "kafka" "vault")
    local service_ready=()

    for service in "${services[@]}"; do
        echo "  Checking ${service}..."
        if bash "${SCRIPT_DIR}/health-check-${service}.sh"; then
            service_ready+=("${service}")
        else
            echo "  ✗ ${service} health check failed"
            return 1
        fi
    done

    echo ""
    echo "  ✓ All core services are healthy"
    echo ""
}

deploy_connectors() {
    echo "Deploying Kafka Connect connectors..."

    local connect_url="http://localhost:8083"
    local max_retries=30
    local retry_interval=2

    echo "  Waiting for Kafka Connect to be ready..."
    for i in $(seq 1 $max_retries); do
        if curl -s "${connect_url}" > /dev/null 2>&1; then
            echo "  ✓ Kafka Connect is ready"
            break
        fi

        if [ "$i" -eq "$max_retries" ]; then
            echo "  ✗ Kafka Connect failed to start after ${max_retries} attempts"
            return 1
        fi

        echo "    Attempt $i/$max_retries: waiting ${retry_interval}s..."
        sleep "$retry_interval"
    done

    if [ -d "docker/connectors" ]; then
        if [ -f "docker/connectors/deploy-connectors.sh" ]; then
            echo "  Running connector deployment script..."
            bash docker/connectors/deploy-connectors.sh
            echo "  ✓ Connectors deployed"
        else
            echo "  ⚠ Warning: deploy-connectors.sh not found, skipping connector deployment"
        fi
    else
        echo "  ⚠ Warning: docker/connectors directory not found, skipping connector deployment"
    fi

    echo ""
}

generate_test_data() {
    echo "Generating test data..."

    local generate_data="${1:-yes}"

    if [ "$generate_data" = "no" ]; then
        echo "  ⊘ Skipping test data generation (--no-data flag)"
        echo ""
        return 0
    fi

    if [ -f "${SCRIPT_DIR}/generate_test_data.py" ]; then
        if command -v poetry &> /dev/null; then
            echo "  Using poetry to run data generator..."
            poetry run python "${SCRIPT_DIR}/generate_test_data.py" --users 10000 --orders 10000 --sessions 1000
        elif python3 -c "import faker, cassandra" &> /dev/null; then
            echo "  Using system python to run data generator..."
            python3 "${SCRIPT_DIR}/generate_test_data.py" --users 10000 --orders 10000 --sessions 1000
        else
            echo "  ⚠ Warning: faker or cassandra-driver not installed"
            echo "    Install with: pip install faker cassandra-driver"
            echo "    Or run manually: python3 ${SCRIPT_DIR}/generate_test_data.py"
        fi
    else
        echo "  ⚠ Warning: generate_test_data.py not found, skipping test data generation"
    fi

    echo ""
}

verify_replication() {
    echo "Verifying CDC replication..."

    echo "  Checking PostgreSQL for replicated data..."

    local max_wait=60
    local elapsed=0
    local check_interval=5

    while [ $elapsed -lt $max_wait ]; do
        local pg_count
        pg_count=$(docker exec cdc-postgres psql -U cdc_user -d warehouse -t -c "SELECT COUNT(*) FROM cdc_users" 2>/dev/null | xargs || echo "0")

        if [ "$pg_count" -gt 0 ]; then
            echo "  ✓ Replication working: $pg_count users replicated to PostgreSQL"
            echo ""
            return 0
        fi

        echo "    Waiting for replication... (${elapsed}s/${max_wait}s)"
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done

    echo "  ⚠ Warning: No replicated data detected after ${max_wait}s"
    echo "    This may be normal if connectors are still initializing"
    echo "    Check connector status: curl http://localhost:8083/connectors"
    echo ""
}

print_service_info() {
    echo "=========================================="
    echo "Local CDC Environment Ready!"
    echo "=========================================="
    echo ""
    echo "Services:"
    echo "  • Cassandra:       localhost:9042"
    echo "  • PostgreSQL:      localhost:5432"
    echo "  • Kafka:           localhost:9092 (internal), localhost:9093 (external)"
    echo "  • Schema Registry: http://localhost:8081"
    echo "  • Kafka Connect:   http://localhost:8083"
    echo "  • Vault:           http://localhost:8200 (token: dev-root-token)"
    echo "  • Prometheus:      http://localhost:9090"
    echo "  • Grafana:         http://localhost:3000 (admin/admin)"
    echo "  • Jaeger:          http://localhost:16686"
    echo ""
    echo "Next steps:"
    echo "  • View logs:       docker compose logs -f"
    echo "  • Check connectors: curl http://localhost:8083/connectors"
    echo "  • Run tests:       pytest tests/integration/"
    echo "  • Stop services:   docker compose down"
    echo ""
    echo "Documentation:"
    echo "  • See quickstart.md for detailed usage"
    echo "  • Check docs/ directory for architecture and troubleshooting"
    echo ""
}

main() {
    local skip_data="no"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --no-data)
                skip_data="yes"
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --no-data    Skip test data generation"
                echo "  --help       Show this help message"
                echo ""
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    check_prerequisites
    setup_env_file
    cleanup_existing_environment
    start_services
    wait_for_services
    deploy_connectors
    generate_test_data "$skip_data"
    verify_replication
    print_service_info
}

main "$@"
