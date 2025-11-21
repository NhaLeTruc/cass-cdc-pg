#!/bin/bash

set -e

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-cdc_user}"
POSTGRES_DB="${POSTGRES_DB:-warehouse}"
MAX_RETRIES="${MAX_RETRIES:-30}"
RETRY_INTERVAL="${RETRY_INTERVAL:-2}"

echo "Checking PostgreSQL health at ${POSTGRES_HOST}:${POSTGRES_PORT}..."

for i in $(seq 1 "$MAX_RETRIES"); do
    if docker exec cdc-postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" > /dev/null 2>&1; then
        if docker exec cdc-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1" > /dev/null 2>&1; then
            echo "✓ PostgreSQL is healthy"
            exit 0
        fi
    fi

    echo "Attempt $i/$MAX_RETRIES: PostgreSQL not ready yet, waiting ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done

echo "✗ PostgreSQL health check failed after $MAX_RETRIES attempts"
exit 1
