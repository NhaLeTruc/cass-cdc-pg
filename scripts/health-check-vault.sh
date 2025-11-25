#!/bin/bash

set -e

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-dev-root-token}"
MAX_RETRIES="${MAX_RETRIES:-30}"
RETRY_INTERVAL="${RETRY_INTERVAL:-2}"

echo "Checking Vault health at ${VAULT_ADDR}..."

for i in $(seq 1 "$MAX_RETRIES"); do
    if docker exec -e VAULT_ADDR=http://0.0.0.0:8200 cdc-vault vault status > /dev/null 2>&1; then
        SEAL_STATUS=$(docker exec -e VAULT_ADDR=http://0.0.0.0:8200 cdc-vault vault status -format=json 2>/dev/null | grep -o '"sealed":[^,]*' | cut -d':' -f2 | tr -d ' ')
        if [ "$SEAL_STATUS" = "false" ]; then
            echo "✓ Vault is healthy and unsealed"
            exit 0
        else
            echo "Attempt $i/$MAX_RETRIES: Vault is sealed, waiting ${RETRY_INTERVAL}s..."
        fi
    else
        echo "Attempt $i/$MAX_RETRIES: Vault not ready yet, waiting ${RETRY_INTERVAL}s..."
    fi

    sleep "$RETRY_INTERVAL"
done

echo "✗ Vault health check failed after $MAX_RETRIES attempts"
exit 1
