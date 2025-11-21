# CDC Pipeline Vault Policy
path "secret/data/cdc/*" {
  capabilities = ["read"]
}

path "database/creds/postgresql-writer" {
  capabilities = ["read"]
}
