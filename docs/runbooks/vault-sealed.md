# Runbook: HashiCorp Vault Sealed

**Alert**: `VaultSealed` (custom alert)
**Severity**: Critical
**SLO Impact**: Complete pipeline outage (no credentials available)

## Symptoms

- CDC API unable to fetch credentials from Vault
- Kafka connectors failing with authentication errors
- Vault UI shows "Vault is sealed" message
- All database connection attempts fail

## Background

Vault seals automatically:
- On restart/reboot
- After crash
- Manual seal command
- Unsealing requires threshold of unseal keys (Shamir's Secret Sharing)

## Diagnosis

### Step 1: Check Vault Status

```bash
# Check if Vault container is running
docker ps | grep vault

# Check Vault seal status
curl http://localhost:8200/v1/sys/seal-status | jq '.'
```

Expected output if sealed:
```json
{
  "type": "shamir",
  "initialized": true,
  "sealed": true,   // <-- Should be false
  "t": 3,           // Threshold: 3 keys needed
  "n": 5,           // Total: 5 keys generated
  "progress": 0     // Unseal progress
}
```

### Step 2: Check Vault Logs

```bash
docker logs cdc-vault --tail=50
```

Look for:
- `core: vault is sealed`
- `core: security barrier not initialized`
- `storage migration in progress`

## Root Causes & Solutions

### Cause 1: Vault Container Restart (Most Common)

**Solution - Dev Environment (Single Unseal Key)**:

```bash
# In dev mode, Vault auto-unseals on restart
# If using production mode in dev, unseal manually:

# Get unseal key from secure storage (see "Unseal Key Storage" section)
export VAULT_UNSEAL_KEY="<unseal-key-from-1password>"

# Unseal Vault
docker exec -it cdc-vault vault operator unseal $VAULT_UNSEAL_KEY
```

**Solution - Production Environment (Shamir's Secret Sharing)**:

```bash
# Production setup requires 3 of 5 key holders to unseal

# Key holder 1 unseals
docker exec -it cdc-vault vault operator unseal <key-1>
# Output: Sealed: true, Progress: 1/3

# Key holder 2 unseals
docker exec -it cdc-vault vault operator unseal <key-2>
# Output: Sealed: true, Progress: 2/3

# Key holder 3 unseals
docker exec -it cdc-vault vault operator unseal <key-3>
# Output: Sealed: false, Progress: 3/3 - UNSEALED

# Verify unsealed
curl http://localhost:8200/v1/sys/seal-status | jq '.sealed'
# Should return: false
```

### Cause 2: Vault Not Initialized

**Symptom**: `initialized: false` in seal status

**Solution**:

```bash
# Initialize Vault (generates unseal keys and root token)
docker exec -it cdc-vault vault operator init -key-shares=5 -key-threshold=3

# Output will provide:
# - Unseal Key 1: <key-1>
# - Unseal Key 2: <key-2>
# - Unseal Key 3: <key-3>
# - Unseal Key 4: <key-4>
# - Unseal Key 5: <key-5>
# - Initial Root Token: <root-token>

# CRITICAL: Store these keys in 1Password/Key Management System immediately!

# Unseal with 3 keys
docker exec -it cdc-vault vault operator unseal <key-1>
docker exec -it cdc-vault vault operator unseal <key-2>
docker exec -it cdc-vault vault operator unseal <key-3>

# Verify unsealed
docker exec -it cdc-vault vault status
```

### Cause 3: Vault Storage Backend Failure

**Symptom**: Logs show `failed to open raft logs` or `storage migration failed`

**Solution**:

```bash
# Check Vault storage volume
docker volume inspect cdc_vault-data

# If volume corrupted, restore from backup
docker-compose down vault
docker volume rm cdc_vault-data
docker volume create cdc_vault-data

# Restore Raft snapshot
docker run --rm \
  -v cdc_vault-data:/vault/data \
  -v /backup:/backup \
  hashicorp/vault:1.15.4 operator raft snapshot restore /backup/vault-snapshot-latest.snap

# Restart Vault
docker-compose up -d vault

# Unseal Vault
docker exec -it cdc-vault vault operator unseal <key-1>
docker exec -it cdc-vault vault operator unseal <key-2>
docker exec -it cdc-vault vault operator unseal <key-3>
```

## Emergency Procedures

### Temporary Bypass (Dev/Staging Only)

**For non-production environments, bypass Vault temporarily:**

```bash
# Update docker-compose.yml to use direct credentials
# Edit environment variables:
# CASSANDRA_USERNAME=cassandra
# CASSANDRA_PASSWORD=cassandra
# POSTGRES_USER=cdc_user
# POSTGRES_PASSWORD=cdc_password

# Restart services
docker-compose restart cdc-api kafka-connect

# Re-enable Vault after unsealing
# Remove direct credentials from environment
# Restart services again
```

**WARNING**: Never use this in production!

### Auto-Unseal Setup (Production Recommended)

Configure auto-unseal using AWS KMS, GCP Cloud KMS, or Azure Key Vault:

```hcl
# vault/config.hcl
seal "awskms" {
  region     = "us-west-2"
  kms_key_id = "arn:aws:kms:us-west-2:123456789012:key/12345678-1234-1234-1234-123456789012"
}
```

With auto-unseal, Vault automatically unseals on restart using cloud KMS.

## Unseal Key Storage

### Development

- Store unseal keys in 1Password team vault
- Document: "CDC Pipeline - Vault Unseal Keys"

### Production

- Split unseal keys among 5 key holders (security team, SRE leads)
- Store in hardware security modules (HSMs) or separate KMS
- Implement key rotation policy (90 days)
- Audit key access logs

## Post-Unseal Validation

```bash
# 1. Verify Vault health
curl http://localhost:8200/v1/sys/health | jq '.'

# 2. Test credential fetch
docker exec -it cdc-vault vault login <root-token>
docker exec -it cdc-vault vault kv get secret/cdc/cassandra

# 3. Restart CDC services to reconnect
docker-compose restart cdc-api

# 4. Verify connector status
curl http://localhost:8083/connectors/cassandra-source-connector/status
curl http://localhost:8083/connectors/postgres-sink-connector/status

# 5. Check pipeline metrics
curl http://localhost:9090/api/v1/query?query=cdc_events_processed_total | jq '.'
```

## Prevention

### Implement Auto-Unseal

Use cloud KMS for automatic unsealing:
- AWS KMS Auto-Unseal
- GCP Cloud KMS Auto-Unseal
- Azure Key Vault Auto-Unseal

### Set Up Vault HA Cluster

Deploy Vault in HA mode with 3+ nodes:
- Raft storage backend
- Automated leader election
- No single point of failure

### Backup & Disaster Recovery

```bash
# Daily Raft snapshot
docker exec -it cdc-vault vault operator raft snapshot save /vault/snapshots/vault-$(date +%Y%m%d).snap

# Copy to S3
aws s3 cp /vault/snapshots/vault-$(date +%Y%m%d).snap s3://backup-bucket/vault/

# Retention: 30 days
```

### Monitoring

Add Prometheus alert:
```yaml
- alert: VaultSealed
  expr: vault_core_unsealed == 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Vault is sealed"
    description: "Vault instance {{ $labels.instance }} is sealed and unavailable"
```

## Escalation

If unable to unseal Vault within 15 minutes:

1. **Page security team** for unseal key access
2. **Activate DR plan** to failover to backup Vault cluster
3. **Communicate outage** to stakeholders (complete CDC pipeline down)
4. **Implement temporary credential workaround** (dev/staging only)

## Related Runbooks

- [Connector Failure](./connector-failure.md)
- [Database Connection Errors](./database-connection-errors.md)
