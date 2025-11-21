# Vault policy for CDC Pipeline
# Allows read access to CDC secrets and database credentials
# Used with AppRole authentication

# Static secrets for Cassandra and other services
path "secret/data/cdc/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/cdc/*" {
  capabilities = ["read", "list"]
}

# Dynamic PostgreSQL credentials with 24h TTL
path "database/creds/postgresql-writer" {
  capabilities = ["read"]
}

# Allow lease renewal for dynamic credentials
path "sys/leases/renew" {
  capabilities = ["update"]
}

# Allow lease revocation (for cleanup on shutdown)
path "sys/leases/revoke" {
  capabilities = ["update"]
}

# Read own token information
path "auth/token/lookup-self" {
  capabilities = ["read"]
}

# Renew own token before expiry
path "auth/token/renew-self" {
  capabilities = ["update"]
}
