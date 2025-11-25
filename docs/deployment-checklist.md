## Production Deployment Checklist

**Feature**: 001-cass-cdc-pg
**Version**: 1.0.0

Use this checklist to ensure production readiness before deploying the CDC pipeline.

### Pre-Deployment

#### Infrastructure Requirements

- [ ] **Kubernetes cluster** version ≥1.25 with 20+ nodes
- [ ] **Node resources**: 16GB RAM, 4 CPU cores minimum per node
- [ ] **Persistent storage**: 2TB total (Cassandra 500GB, PostgreSQL 1TB, Kafka 500GB)
- [ ] **Network bandwidth**: 10 Gbps between nodes
- [ ] **Load balancer**: Configure for API and Grafana ingress

#### TLS Certificates

- [ ] **Generate certificates** for all services:
  - Cassandra client TLS
  - PostgreSQL client TLS
  - Kafka broker-to-broker mTLS
  - Kafka client-to-broker TLS
  - Schema Registry TLS
  - Vault TLS
- [ ] **Store certificates** in Kubernetes secrets (sealed secrets recommended)
- [ ] **Set expiry alerts** for certificate renewal (90 days before expiry)
- [ ] **Test certificate chain** validation

#### HashiCorp Vault Setup

- [ ] **Deploy Vault** in HA mode (3+ replicas)
- [ ] **Initialize Vault** with Shamir's Secret Sharing (5 keys, 3 threshold)
- [ ] **Distribute unseal keys** to 5 key holders (security team, SRE leads)
- [ ] **Configure auto-unseal** with AWS KMS, GCP Cloud KMS, or Azure Key Vault
- [ ] **Enable audit logging** to syslog/file backend
- [ ] **Create AppRole** for CDC services:
  ```bash
  vault auth enable approle
  vault write auth/approle/role/cdc-pipeline \
    secret_id_ttl=24h \
    token_ttl=24h \
    token_max_ttl=48h \
    policies="cdc-policy"
  ```
- [ ] **Store Cassandra credentials** in KV v2:
  ```bash
  vault kv put secret/cdc/cassandra username=cassandra password=<strong-password>
  ```
- [ ] **Configure PostgreSQL dynamic secrets**:
  ```bash
  vault write database/config/postgresql \
    plugin_name=postgresql-database-plugin \
    allowed_roles="postgresql-writer" \
    connection_url="postgresql://{{username}}:{{password}}@postgres:5432/warehouse" \
    username="vault_admin" \
    password="<admin-password>"

  vault write database/roles/postgresql-writer \
    db_name=postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; \
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="24h" \
    max_ttl="48h"
  ```
- [ ] **Test credential rotation**: Verify 24-hour TTL renewal works

#### Network Security

- [ ] **Configure network policies** (deny-all-ingress by default):
  ```yaml
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: cdc-pipeline-netpol
    namespace: cdc
  spec:
    podSelector: {}
    policyTypes:
    - Ingress
    - Egress
    ingress:
    - from:
      - podSelector:
          matchLabels:
            app: cdc
      ports:
      - protocol: TCP
        port: 8080  # CDC API
  ```
- [ ] **Whitelist IP ranges** for external access (Grafana, API)
- [ ] **Enable Pod Security Standards** (restricted mode)
- [ ] **Configure egress filtering** (allow only required destinations)

### Configuration

#### Kafka Configuration

- [ ] **Increase broker heap**: 4-8GB for production workload
- [ ] **Configure replication factor**: 3 for all topics
- [ ] **Set log retention**: 7 days for data topics
- [ ] **Enable compression**: Snappy for bandwidth reduction
- [ ] **Configure partitions**: 8-16 partitions per topic
- [ ] **Enable rack awareness** for replica placement
- [ ] **Configure min.insync.replicas**: 2 for durability

#### Connector Configuration

- [ ] **Debezium Source Connector**:
  - `max.batch.size`: 2048
  - `max.queue.size`: 8192
  - `snapshot.mode`: "initial" for first deployment
  - `tombstones.on.delete`: true
- [ ] **JDBC Sink Connector**:
  - `batch.size`: 1000
  - `max.retries`: 10
  - `retry.backoff.ms`: 3000
  - `connection.pool.size`: 20
  - `errors.tolerance`: "all"
  - `errors.deadletterqueue.topic.name`: "dlq-events"

#### Resource Limits

- [ ] **Cassandra**:
  ```yaml
  resources:
    requests:
      memory: "8Gi"
      cpu: "4"
    limits:
      memory: "16Gi"
      cpu: "8"
  ```
- [ ] **PostgreSQL**:
  ```yaml
  resources:
    requests:
      memory: "4Gi"
      cpu: "2"
    limits:
      memory: "8Gi"
      cpu: "4"
  ```
- [ ] **Kafka brokers** (per broker):
  ```yaml
  resources:
    requests:
      memory: "4Gi"
      cpu: "2"
    limits:
      memory: "8Gi"
      cpu: "4"
  ```
- [ ] **Kafka Connect**:
  ```yaml
  resources:
    requests:
      memory: "2Gi"
      cpu: "1"
    limits:
      memory: "4Gi"
      cpu: "2"
  ```
- [ ] **CDC API**:
  ```yaml
  resources:
    requests:
      memory: "512Mi"
      cpu: "500m"
    limits:
      memory: "1Gi"
      cpu: "1"
  ```

#### Auto-Scaling

- [ ] **Horizontal Pod Autoscaler** for CDC API:
  ```yaml
  apiVersion: autoscaling/v2
  kind: HorizontalPodAutoscaler
  metadata:
    name: cdc-api-hpa
    namespace: cdc
  spec:
    scaleTargetRef:
      apiVersion: apps/v1
      kind: Deployment
      name: cdc-api
    minReplicas: 2
    maxReplicas: 10
    metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  ```
- [ ] **Kafka Connect autoscaling** based on consumer lag
- [ ] **Vertical Pod Autoscaler** for databases (if needed)

### Monitoring & Alerting

#### Prometheus Setup

- [ ] **Configure scrape intervals**: 15s default
- [ ] **Set retention**: 15 days for metrics
- [ ] **Enable remote write** to long-term storage (Thanos, Cortex, or Mimir)
- [ ] **Configure service discovery** for Kubernetes pods
- [ ] **Load prometheus-alerts.yml** with all alert rules

#### AlertManager Configuration

- [ ] **Configure Slack receiver**:
  ```yaml
  receivers:
  - name: 'slack-critical'
    slack_configs:
    - api_url: '<slack-webhook-url>'
      channel: '#cdc-alerts-critical'
      title: '{{ .GroupLabels.alertname }}'
      text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
  ```
- [ ] **Configure PagerDuty** for critical alerts
- [ ] **Set up email notifications** for warning alerts
- [ ] **Test alert routing** (send test alert)
- [ ] **Configure inhibition rules** (critical alerts suppress warnings)

#### Grafana Dashboards

- [ ] **Import pre-configured dashboards**:
  - CDC Pipeline Overview
  - Kafka Monitoring
  - Database Connections
  - Reconciliation Metrics
- [ ] **Configure Prometheus datasource**
- [ ] **Set up dashboard alerts** (optional, use AlertManager primarily)
- [ ] **Create team-specific dashboards**

#### Logging

- [ ] **Deploy log aggregation** (ELK, Splunk, or Loki)
- [ ] **Configure structured logging** (JSON format)
- [ ] **Set log retention**: 30 days minimum
- [ ] **Create log-based alerts** for critical errors
- [ ] **Test log query performance**

### Backup & Disaster Recovery

#### Cassandra Backups

- [ ] **Configure daily snapshots**:
  ```bash
  nodetool snapshot -t cdc-backup-$(date +%Y%m%d) warehouse
  ```
- [ ] **Upload to S3/GCS**:
  ```bash
  aws s3 sync /var/lib/cassandra/snapshots/cdc-backup-20251125 s3://backup-bucket/cassandra/20251125/
  ```
- [ ] **Set retention policy**: 30 days
- [ ] **Test restore procedure** (restore to staging)
- [ ] **Document restore runbook**

#### PostgreSQL Backups

- [ ] **Configure pg_dump daily**:
  ```bash
  pg_dump -U admin -d warehouse -F c -f warehouse-$(date +%Y%m%d).dump
  ```
- [ ] **Enable WAL archiving** for point-in-time recovery:
  ```conf
  wal_level = replica
  archive_mode = on
  archive_command = 'aws s3 cp %p s3://backup-bucket/postgresql/wal/%f'
  ```
- [ ] **Upload to S3/GCS**
- [ ] **Set retention policy**: 30 days for dumps, 7 days for WAL
- [ ] **Test PITR restore**

#### Kafka Backups

- [ ] **Configure MirrorMaker 2** for DR region
- [ ] **Mirror critical topics** (dlq-events, schema-changes)
- [ ] **Set up cross-region replication**
- [ ] **Test failover to DR cluster**

#### Vault Backups

- [ ] **Configure Raft snapshots** (every 6 hours):
  ```bash
  vault operator raft snapshot save /vault/snapshots/vault-$(date +%Y%m%d-%H%M).snap
  ```
- [ ] **Upload to S3/GCS**
- [ ] **Set retention policy**: 90 days
- [ ] **Test restore from snapshot**

### Security Hardening

#### Authentication

- [ ] **Disable default passwords** (Cassandra, PostgreSQL, Kafka)
- [ ] **Rotate all credentials** before go-live
- [ ] **Enable RBAC** in Kubernetes
- [ ] **Configure service accounts** with least privilege
- [ ] **Implement JWT authentication** for CDC API (if exposing publicly)

#### Data Protection

- [ ] **Enable encryption at rest**:
  - Cassandra: Transparent Data Encryption
  - PostgreSQL: pgcrypto for sensitive columns
  - Kafka: Log encryption
- [ ] **Enable encryption in transit** (TLS 1.3 all services)
- [ ] **Configure PII masking** for sensitive columns
- [ ] **Implement GDPR compliance**:
  - Data erasure API tested
  - Audit logging enabled
  - Retention policies configured

#### Vulnerability Scanning

- [ ] **Scan Docker images** with Trivy:
  ```bash
  trivy image debezium/connect:2.5.0
  ```
- [ ] **Run security audit** with Bandit and Safety
- [ ] **Pen test API endpoints** (schedule external audit)
- [ ] **Review dependency vulnerabilities** (Dependabot/Renovate)

### Performance Tuning

#### Database Optimization

- [ ] **Cassandra**:
  - Compaction strategy: LeveledCompactionStrategy for read-heavy
  - Heap size: 8-16GB
  - GC: G1GC with tuned parameters
- [ ] **PostgreSQL**:
  - shared_buffers: 25% of RAM
  - effective_cache_size: 75% of RAM
  - work_mem: 64MB
  - max_connections: 200
  - Enable pg_stat_statements extension

#### Kafka Optimization

- [ ] **Increase num.network.threads**: 8
- [ ] **Increase num.io.threads**: 16
- [ ] **Configure log.segment.bytes**: 1GB
- [ ] **Enable compression.type**: snappy
- [ ] **Set replica.lag.time.max.ms**: 30000

### Testing

#### Smoke Tests

- [ ] **Deploy to staging** environment first
- [ ] **Run smoke tests**:
  ```bash
  make test-smoke
  ```
- [ ] **Verify end-to-end replication**:
  - Insert record in Cassandra
  - Verify appears in PostgreSQL within 5 seconds
- [ ] **Test DLQ flow**: Introduce error, verify DLQ capture
- [ ] **Test reconciliation**: Run manual reconciliation, verify results
- [ ] **Test alerts**: Trigger alert conditions, verify notifications

#### Load Testing

- [ ] **Run benchmark script**:
  ```bash
  poetry run python scripts/benchmark.py --events=100000 --duration=600
  ```
- [ ] **Verify target performance**:
  - Throughput: ≥10,000 events/sec
  - Latency: P95 ≤2 seconds
  - No errors or DLQ events
- [ ] **Monitor resource utilization** during load test
- [ ] **Identify bottlenecks** and tune

#### Failure Testing

- [ ] **Test Cassandra node failure**: Kill 1 node, verify pipeline continues
- [ ] **Test PostgreSQL failover**: Promote replica, verify connector reconnects
- [ ] **Test Kafka broker failure**: Kill 1 broker, verify rebalancing
- [ ] **Test network partition**: Simulate split-brain, verify recovery
- [ ] **Test Vault seal**: Seal Vault, verify graceful degradation

### Go-Live

#### Deployment

- [ ] **Schedule maintenance window** (announce to stakeholders)
- [ ] **Deploy infrastructure** (Helm chart):
  ```bash
  helm install cdc-pipeline ./helm -f values-prod.yaml --namespace cdc
  ```
- [ ] **Verify all pods healthy**:
  ```bash
  kubectl get pods -n cdc
  ```
- [ ] **Deploy connectors**:
  ```bash
  kubectl apply -f k8s/connectors/
  ```
- [ ] **Enable reconciliation scheduler** (set RECONCILIATION_ENABLED=true)

#### Validation

- [ ] **Check all services** running:
  ```bash
  kubectl get deployments -n cdc
  ```
- [ ] **Verify connectivity**:
  - Cassandra → Kafka (Debezium source)
  - Kafka → PostgreSQL (JDBC sink)
  - API → Vault (credentials)
- [ ] **Monitor dashboards** for 1 hour post-deployment
- [ ] **Run manual reconciliation** to verify data consistency
- [ ] **Test API endpoints**:
  ```bash
  curl https://cdc-api.prod.company.com/health
  ```

#### Rollback Plan

- [ ] **Document rollback steps**:
  1. Pause source connector
  2. Pause sink connector
  3. Helm rollback to previous version
  4. Resume connectors
- [ ] **Test rollback procedure** in staging
- [ ] **Set rollback trigger criteria**:
  - Error rate > 5%
  - Lag > 100K events
  - Data corruption detected

### Post-Deployment

#### Documentation

- [ ] **Update runbooks** with production-specific details
- [ ] **Document on-call procedures**
- [ ] **Create incident response playbook**
- [ ] **Train SRE team** on monitoring and troubleshooting

#### Monitoring

- [ ] **Set up 24/7 monitoring** dashboard
- [ ] **Configure PagerDuty rotation**
- [ ] **Schedule weekly review** of metrics and alerts
- [ ] **Review and adjust alert thresholds** based on actual traffic

#### Compliance

- [ ] **Complete security audit** documentation
- [ ] **Document data flows** for compliance (GDPR, SOC2)
- [ ] **Review and sign-off** on deployment checklist
- [ ] **Archive deployment artifacts** (Helm values, configs)

---

## Sign-Off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Engineering Lead | | | |
| SRE Lead | | | |
| Security Team | | | |
| DBA Team | | | |
| Product Owner | | | |

**Deployment Date**: _______________

**Next Review**: _______________ (30 days post-deployment)
