#!/bin/bash

set -e

KAFKA_HOST="${KAFKA_HOST:-localhost}"
KAFKA_PORT="${KAFKA_PORT:-9092}"
MAX_RETRIES="${MAX_RETRIES:-30}"
RETRY_INTERVAL="${RETRY_INTERVAL:-2}"

echo "Checking Kafka health at ${KAFKA_HOST}:${KAFKA_PORT}..."

for i in $(seq 1 "$MAX_RETRIES"); do
    if docker exec cdc-kafka kafka-broker-api-versions --bootstrap-server "${KAFKA_HOST}:${KAFKA_PORT}" > /dev/null 2>&1; then
        if docker exec cdc-kafka kafka-topics --bootstrap-server "${KAFKA_HOST}:${KAFKA_PORT}" --list > /dev/null 2>&1; then
            echo "✓ Kafka is healthy"
            exit 0
        fi
    fi

    echo "Attempt $i/$MAX_RETRIES: Kafka not ready yet, waiting ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done

echo "✗ Kafka health check failed after $MAX_RETRIES attempts"
exit 1
