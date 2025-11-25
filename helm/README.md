# Cassandra to PostgreSQL CDC Pipeline Helm Chart

This Helm chart deploys the Cassandra to PostgreSQL Change Data Capture (CDC) pipeline on Kubernetes.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.8+
- Kafka cluster (external or deployed separately)
- Cassandra cluster (external or deployed separately)
- PostgreSQL database (external or deployed separately)
- HashiCorp Vault (optional, for secrets management)
- Prometheus Operator (optional, for monitoring)

## Installation

### Basic Installation

```bash
helm install cdc-pipeline ./helm
```

### Installation with Custom Values

```bash
helm install cdc-pipeline ./helm -f custom-values.yaml
```

### Installation with Specific Kafka Brokers

```bash
helm install cdc-pipeline ./helm \
  --set kafkaConnect.env.CONNECT_BOOTSTRAP_SERVERS="kafka-0.kafka:9092,kafka-1.kafka:9092"
```

## Configuration

The following table lists the configurable parameters of the chart and their default values.

### Kafka Connect Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `kafkaConnect.replicaCount` | Number of Kafka Connect worker replicas | `3` |
| `kafkaConnect.image.repository` | Kafka Connect image repository | `confluentinc/cp-kafka-connect` |
| `kafkaConnect.image.tag` | Kafka Connect image tag | `7.5.2` |
| `kafkaConnect.resources.limits.cpu` | CPU limit | `1000m` |
| `kafkaConnect.resources.limits.memory` | Memory limit | `2Gi` |
| `kafkaConnect.resources.requests.cpu` | CPU request | `500m` |
| `kafkaConnect.resources.requests.memory` | Memory request | `1Gi` |

### Connector Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `connectors.cassandraSource.enabled` | Enable Cassandra source connector | `true` |
| `connectors.cassandraSource.name` | Connector name | `cassandra-source-connector` |
| `connectors.postgresqlSink.enabled` | Enable PostgreSQL sink connector | `true` |
| `connectors.postgresqlSink.name` | Connector name | `postgresql-sink-connector` |

### Vault Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `vault.enabled` | Enable Vault integration | `true` |
| `vault.address` | Vault server address | `https://vault.vault.svc.cluster.local:8200` |
| `vault.authMethod` | Authentication method (kubernetes, approle, token) | `kubernetes` |
| `vault.kubernetesAuth.role` | Kubernetes auth role | `cdc-pipeline` |

### Monitoring Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `monitoring.prometheus.enabled` | Enable Prometheus metrics | `true` |
| `monitoring.prometheus.serviceMonitor.enabled` | Enable ServiceMonitor for Prometheus Operator | `true` |

### Autoscaling Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `kafkaConnect.autoscaling.enabled` | Enable HPA | `false` |
| `kafkaConnect.autoscaling.minReplicas` | Minimum replicas | `3` |
| `kafkaConnect.autoscaling.maxReplicas` | Maximum replicas | `10` |
| `kafkaConnect.autoscaling.targetCPUUtilizationPercentage` | Target CPU utilization | `70` |

## Usage

### Deploy Connectors

After the chart is installed, deploy the connectors:

```bash
# Get the Kafka Connect service endpoint
kubectl port-forward svc/cdc-pipeline-kafka-connect 8083:8083

# Deploy Cassandra source connector
curl -X POST http://localhost:8083/connectors \
  -H "Content-Type: application/json" \
  -d @helm/templates/configmap.yaml

# Check connector status
curl http://localhost:8083/connectors/cassandra-source-connector/status
```

### Verify Deployment

```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=cass-cdc-pg

# View logs
kubectl logs -f -l app.kubernetes.io/component=kafka-connect

# Check connector status
curl http://localhost:8083/connectors
```

### Scale Deployment

```bash
# Scale to 5 replicas
kubectl scale deployment/cdc-pipeline-kafka-connect --replicas=5

# Or enable HPA
helm upgrade cdc-pipeline ./helm --set kafkaConnect.autoscaling.enabled=true
```

### Access Metrics

```bash
# Port forward to Kafka Connect
kubectl port-forward svc/cdc-pipeline-kafka-connect 8083:8083

# Get Prometheus metrics
curl http://localhost:8083/metrics
```

## Upgrading

```bash
helm upgrade cdc-pipeline ./helm -f custom-values.yaml
```

## Uninstalling

```bash
helm uninstall cdc-pipeline
```

## Vault Integration

### Setup Vault for Kubernetes Auth

```bash
# Enable Kubernetes auth in Vault
vault auth enable kubernetes

# Configure Kubernetes auth
vault write auth/kubernetes/config \
  kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443"

# Create policy for CDC pipeline
vault policy write cdc-pipeline - <<EOF
path "secret/data/cdc/*" {
  capabilities = ["read"]
}
path "database/creds/postgresql-writer" {
  capabilities = ["read"]
}
EOF

# Create Kubernetes auth role
vault write auth/kubernetes/role/cdc-pipeline \
  bound_service_account_names=kafka-connect \
  bound_service_account_namespaces=default \
  policies=cdc-pipeline \
  ttl=24h
```

### Store Secrets in Vault

```bash
# Cassandra credentials
vault kv put secret/cdc/cassandra username=cassandra password=cassandra

# Configure PostgreSQL dynamic secrets
vault write database/config/postgresql \
  plugin_name=postgresql-database-plugin \
  allowed_roles="postgresql-writer" \
  connection_url="postgresql://{{username}}:{{password}}@postgres:5432/warehouse?sslmode=require" \
  username="vault_admin" \
  password="vault_password"

vault write database/roles/postgresql-writer \
  db_name=postgresql \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; \
    GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
  default_ttl="24h" \
  max_ttl="72h"
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod events
kubectl describe pod <pod-name>

# Check logs
kubectl logs <pod-name>
```

### Connectors Failing

```bash
# Check connector status
curl http://localhost:8083/connectors/<connector-name>/status

# View connector config
curl http://localhost:8083/connectors/<connector-name>/config

# Restart connector
curl -X POST http://localhost:8083/connectors/<connector-name>/restart
```

### Vault Authentication Issues

```bash
# Check Vault agent logs
kubectl logs <pod-name> -c vault-agent

# Verify service account
kubectl get sa kafka-connect -o yaml

# Check Vault policy
vault policy read cdc-pipeline
```

## Production Considerations

1. **Resource Limits**: Adjust `resources.limits` based on your workload
2. **Replication Factor**: Set Kafka topic replication factor to 3 in production
3. **Monitoring**: Enable Prometheus ServiceMonitor for production monitoring
4. **High Availability**: Run at least 3 Kafka Connect workers
5. **Pod Disruption Budget**: Enabled by default to maintain availability during updates
6. **Network Policies**: Enable `networkPolicy.enabled=true` for security
7. **TLS**: Configure TLS for Kafka, Cassandra, and PostgreSQL connections
8. **Vault**: Use Vault for all credentials in production
9. **Autoscaling**: Enable HPA based on CPU/memory metrics

## License

Apache License 2.0
