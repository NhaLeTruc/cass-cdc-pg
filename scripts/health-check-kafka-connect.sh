#!/bin/bash

set -e

KAFKA_CONNECT_HOST="${KAFKA_CONNECT_HOST:-localhost}"
KAFKA_CONNECT_PORT="${KAFKA_CONNECT_PORT:-8083}"
MAX_RETRIES="${MAX_RETRIES:-60}"
RETRY_INTERVAL="${RETRY_INTERVAL:-2}"

echo "Checking Kafka Connect health at ${KAFKA_CONNECT_HOST}:${KAFKA_CONNECT_PORT}..."

for i in $(seq 1 "$MAX_RETRIES"); do
    # Check if Kafka Connect API is responding
    if curl -f -s --max-time 5 "http://${KAFKA_CONNECT_HOST}:${KAFKA_CONNECT_PORT}/" > /dev/null 2>&1; then
        # Verify connector plugins are loaded (indicates full initialization)
        if curl -f -s --max-time 5 "http://${KAFKA_CONNECT_HOST}:${KAFKA_CONNECT_PORT}/connector-plugins" 2>/dev/null | grep -q "class"; then
            echo "✓ Kafka Connect is healthy and plugins are loaded"
            exit 0
        else
            echo "Attempt $i/$MAX_RETRIES: Kafka Connect API responding but plugins not loaded yet, waiting ${RETRY_INTERVAL}s..."
        fi
    else
        echo "Attempt $i/$MAX_RETRIES: Kafka Connect not ready yet, waiting ${RETRY_INTERVAL}s..."
    fi

    sleep "$RETRY_INTERVAL"
done

echo "✗ Kafka Connect health check failed after $MAX_RETRIES attempts"
exit 1