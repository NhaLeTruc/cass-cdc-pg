#!/bin/bash
# Vault initialization script for CDC Pipeline
# Populates secrets and configures dynamic database credentials

set -e

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-dev-token}"

echo "Initializing Vault secrets for CDC Pipeline..."
echo "Vault Address: $VAULT_ADDR"

# Wait for Vault to be ready
echo "Waiting for Vault to be ready..."
until curl -s -f "$VAULT_ADDR/v1/sys/health" > /dev/null 2>&1; do
    echo "Vault not ready yet, waiting..."
    sleep 2
done
echo "Vault is ready!"

# Enable KV secrets engine v2 (if not already enabled)
echo "Enabling KV secrets engine v2..."
vault secrets enable -version=2 -path=secret kv 2>/dev/null || echo "KV secrets engine already enabled"

# Create Cassandra credentials
echo "Creating Cassandra credentials..."
vault kv put secret/cdc/cassandra \
    username="cassandra" \
    password="cassandra" \
    contact_points="cassandra:9042" \
    keyspace="cdc_test"

# Create Kafka credentials
echo "Creating Kafka credentials..."
vault kv put secret/cdc/kafka \
    bootstrap_servers="kafka:9092" \
    security_protocol="PLAINTEXT"

# Create Schema Registry credentials
echo "Creating Schema Registry credentials..."
vault kv put secret/cdc/schema-registry \
    url="http://schema-registry:8081"

# Enable database secrets engine (if not already enabled)
echo "Enabling database secrets engine..."
vault secrets enable database 2>/dev/null || echo "Database secrets engine already enabled"

# Configure PostgreSQL connection
echo "Configuring PostgreSQL dynamic credentials..."
vault write database/config/postgresql \
    plugin_name=postgresql-database-plugin \
    allowed_roles="postgresql-writer" \
    connection_url="postgresql://{{username}}:{{password}}@postgres:5432/cdc_target?sslmode=disable" \
    username="postgres" \
    password="postgres"

# Create PostgreSQL writer role with 24h TTL
echo "Creating postgresql-writer role..."
vault write database/roles/postgresql-writer \
    db_name=postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; \
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\"; \
        GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO \"{{name}}\"; \
        GRANT CREATE ON SCHEMA public TO \"{{name}}\";" \
    default_ttl="24h" \
    max_ttl="24h"

# Create CDC policy
echo "Creating CDC policy..."
vault policy write cdc-policy /vault/policies/cdc-policy.hcl

# Enable AppRole auth method (if not already enabled)
echo "Enabling AppRole auth method..."
vault auth enable approle 2>/dev/null || echo "AppRole auth already enabled"

# Create AppRole for CDC pipeline
echo "Creating CDC pipeline AppRole..."
vault write auth/approle/role/cdc-pipeline \
    token_policies="cdc-policy" \
    token_ttl=24h \
    token_max_ttl=24h

# Get role ID and secret ID
echo "Getting AppRole credentials..."
ROLE_ID=$(vault read -field=role_id auth/approle/role/cdc-pipeline/role-id)
SECRET_ID=$(vault write -field=secret_id -f auth/approle/role/cdc-pipeline/secret-id)

echo ""
echo "Vault initialization complete!"
echo ""
echo "AppRole Credentials:"
echo "  ROLE_ID: $ROLE_ID"
echo "  SECRET_ID: $SECRET_ID"
echo ""
echo "To authenticate with AppRole:"
echo "  vault write auth/approle/login role_id=\"$ROLE_ID\" secret_id=\"$SECRET_ID\""
echo ""
echo "To test PostgreSQL dynamic credentials:"
echo "  vault read database/creds/postgresql-writer"
echo ""
echo "To test Cassandra static credentials:"
echo "  vault kv get secret/cdc/cassandra"
echo ""
