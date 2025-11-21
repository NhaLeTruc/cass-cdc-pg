#!/bin/bash
set -e

KAFKA_CONNECT_URL="${KAFKA_CONNECT_URL:-http://kafka-connect:8083}"
CONNECTORS_DIR="${CONNECTORS_DIR:-/connectors}"

MAX_RETRIES=30
RETRY_DELAY=5

echo "========================================"
echo "Kafka Connect Connector Deployment"
echo "========================================"
echo "Connect URL: $KAFKA_CONNECT_URL"
echo "Connectors Directory: $CONNECTORS_DIR"
echo ""

wait_for_kafka_connect() {
    echo "Waiting for Kafka Connect to be ready..."

    for i in $(seq 1 $MAX_RETRIES); do
        if curl -s "$KAFKA_CONNECT_URL" > /dev/null 2>&1; then
            echo "Kafka Connect is ready!"
            return 0
        fi

        echo "Attempt $i/$MAX_RETRIES: Kafka Connect not ready. Retrying in ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
    done

    echo "ERROR: Kafka Connect did not become ready after $MAX_RETRIES attempts"
    exit 1
}

deploy_connector() {
    local connector_file=$1
    local connector_name=$(basename "$connector_file" .json)

    echo "----------------------------------------"
    echo "Deploying connector: $connector_name"
    echo "----------------------------------------"

    if [ ! -f "$connector_file" ]; then
        echo "ERROR: Connector file not found: $connector_file"
        return 1
    fi

    echo "Checking if connector already exists..."
    if curl -s "$KAFKA_CONNECT_URL/connectors/$connector_name" > /dev/null 2>&1; then
        echo "Connector exists. Deleting old version..."
        curl -X DELETE "$KAFKA_CONNECT_URL/connectors/$connector_name"
        sleep 2
    fi

    echo "Creating connector..."
    response=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        --data @"$connector_file" \
        "$KAFKA_CONNECT_URL/connectors")

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -eq 201 ] || [ "$http_code" -eq 200 ]; then
        echo "✓ Connector deployed successfully"
        echo "$body" | jq '.' 2>/dev/null || echo "$body"
    else
        echo "✗ Failed to deploy connector (HTTP $http_code)"
        echo "$body" | jq '.' 2>/dev/null || echo "$body"
        return 1
    fi

    echo ""
}

check_connector_status() {
    local connector_name=$1

    echo "Checking status of $connector_name..."

    response=$(curl -s "$KAFKA_CONNECT_URL/connectors/$connector_name/status")

    state=$(echo "$response" | jq -r '.connector.state' 2>/dev/null)

    if [ "$state" == "RUNNING" ]; then
        echo "✓ Connector $connector_name is RUNNING"
    else
        echo "✗ Connector $connector_name state: $state"
        echo "$response" | jq '.' 2>/dev/null || echo "$response"
    fi

    echo ""
}

list_deployed_connectors() {
    echo "========================================"
    echo "Deployed Connectors Summary"
    echo "========================================"

    connectors=$(curl -s "$KAFKA_CONNECT_URL/connectors")

    if [ $? -eq 0 ]; then
        echo "$connectors" | jq -r '.[]' 2>/dev/null || echo "$connectors"
    else
        echo "Failed to retrieve connector list"
    fi

    echo ""
}

wait_for_kafka_connect

if [ ! -d "$CONNECTORS_DIR" ]; then
    echo "ERROR: Connectors directory not found: $CONNECTORS_DIR"
    exit 1
fi

echo "Starting connector deployment..."
echo ""

for connector_file in "$CONNECTORS_DIR"/*.json; do
    if [ -f "$connector_file" ]; then
        deploy_connector "$connector_file" || echo "Warning: Failed to deploy $(basename $connector_file)"
    fi
done

echo "========================================"
echo "Waiting for connectors to initialize..."
echo "========================================"
sleep 5

for connector_file in "$CONNECTORS_DIR"/*.json; do
    if [ -f "$connector_file" ]; then
        connector_name=$(basename "$connector_file" .json)
        check_connector_status "$connector_name"
    fi
done

list_deployed_connectors

echo "========================================"
echo "Connector deployment complete!"
echo "========================================"
