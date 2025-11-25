#!/bin/bash

set -e

CASSANDRA_HOST="${CASSANDRA_HOST:-localhost}"
CASSANDRA_PORT="${CASSANDRA_PORT:-9042}"
MAX_RETRIES="${MAX_RETRIES:-60}"
RETRY_INTERVAL="${RETRY_INTERVAL:-2}"

echo "Checking Cassandra health at ${CASSANDRA_HOST}:${CASSANDRA_PORT}..."

for i in $(seq 1 "$MAX_RETRIES"); do
    if docker exec cdc-cassandra cqlsh -e "describe cluster" > /dev/null 2>&1; then
        echo "✓ Cassandra is healthy"
        exit 0
    fi

    echo "Attempt $i/$MAX_RETRIES: Cassandra not ready yet, waiting ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done

echo "✗ Cassandra health check failed after $MAX_RETRIES attempts"
exit 1
