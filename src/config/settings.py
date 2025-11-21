"""
Configuration module using pydantic-settings for type-safe environment variable management.
"""
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CassandraSettings(BaseSettings):
    """Cassandra connection settings"""
    host: str = Field(default="localhost", env="CASSANDRA_HOST")
    port: int = Field(default=9042, env="CASSANDRA_PORT")
    keyspace: str = Field(default="warehouse", env="CASSANDRA_KEYSPACE")
    username: str = Field(default="cassandra", env="CASSANDRA_USERNAME")
    password: str = Field(default="cassandra", env="CASSANDRA_PASSWORD")
    datacenter: str = Field(default="dc1", env="CASSANDRA_DC")
    tls_enabled: bool = Field(default=False, env="CASSANDRA_TLS_ENABLED")
    tls_ca_cert: Optional[str] = Field(default=None, env="CASSANDRA_TLS_CA_CERT")
    tls_client_cert: Optional[str] = Field(default=None, env="CASSANDRA_TLS_CLIENT_CERT")
    tls_client_key: Optional[str] = Field(default=None, env="CASSANDRA_TLS_CLIENT_KEY")


class PostgreSQLSettings(BaseSettings):
    """PostgreSQL connection settings"""
    host: str = Field(default="localhost", env="POSTGRES_HOST")
    port: int = Field(default=5432, env="POSTGRES_PORT")
    database: str = Field(default="warehouse", env="POSTGRES_DB")
    user: str = Field(default="cdc_user", env="POSTGRES_USER")
    password: str = Field(default="cdc_password", env="POSTGRES_PASSWORD")
    schema: str = Field(default="public", env="POSTGRES_SCHEMA")
    tls_enabled: bool = Field(default=False, env="POSTGRES_TLS_ENABLED")
    tls_ca_cert: Optional[str] = Field(default=None, env="POSTGRES_TLS_CA_CERT")
    tls_client_cert: Optional[str] = Field(default=None, env="POSTGRES_TLS_CLIENT_CERT")
    tls_client_key: Optional[str] = Field(default=None, env="POSTGRES_TLS_CLIENT_KEY")
    min_pool_size: int = Field(default=2, env="POSTGRES_MIN_POOL_SIZE")
    max_pool_size: int = Field(default=10, env="POSTGRES_MAX_POOL_SIZE")
    connect_timeout: int = Field(default=10, env="POSTGRES_CONNECT_TIMEOUT")


class KafkaSettings(BaseSettings):
    """Kafka configuration settings"""
    bootstrap_servers: str = Field(default="localhost:9093", env="KAFKA_BOOTSTRAP_SERVERS")
    schema_registry_url: str = Field(default="http://localhost:8081", env="KAFKA_SCHEMA_REGISTRY_URL")
    schema_registry_host: str = Field(default="localhost", env="SCHEMA_REGISTRY_HOST")
    schema_registry_port: int = Field(default=8081, env="SCHEMA_REGISTRY_PORT")
    connect_url: str = Field(default="http://localhost:8083", env="KAFKA_CONNECT_URL")
    tls_enabled: bool = Field(default=False, env="KAFKA_TLS_ENABLED")
    tls_ca_cert: Optional[str] = Field(default=None, env="KAFKA_TLS_CA_CERT")
    tls_client_cert: Optional[str] = Field(default=None, env="KAFKA_TLS_CLIENT_CERT")
    tls_client_key: Optional[str] = Field(default=None, env="KAFKA_TLS_CLIENT_KEY")


class VaultSettings(BaseSettings):
    """HashiCorp Vault settings"""
    url: str = Field(default="http://localhost:8200", env="VAULT_ADDR")
    token: str = Field(default="dev-root-token", env="VAULT_TOKEN")
    namespace: str = Field(default="cdc", env="VAULT_NAMESPACE")
    enabled: bool = Field(default=False, env="VAULT_ENABLED")
    approle_role_id: Optional[str] = Field(default=None, env="VAULT_ROLE_ID")
    approle_secret_id: Optional[str] = Field(default=None, env="VAULT_SECRET_ID")


class PerformanceSettings(BaseSettings):
    """Performance tuning settings"""
    max_batch_size: int = Field(default=1000, env="MAX_BATCH_SIZE")
    max_queue_size: int = Field(default=8192, env="MAX_QUEUE_SIZE")
    poll_interval_ms: int = Field(default=1000, env="POLL_INTERVAL_MS")
    connection_pool_min: int = Field(default=5, env="CONNECTION_POOL_MIN")
    connection_pool_max: int = Field(default=50, env="CONNECTION_POOL_MAX")
    consumer_threads: int = Field(default=4, env="CONSUMER_THREADS")


class ErrorHandlingSettings(BaseSettings):
    """Error handling configuration"""
    max_retries: int = Field(default=10, env="MAX_RETRIES")
    retry_backoff_ms: int = Field(default=3000, env="RETRY_BACKOFF_MS")
    retry_backoff_multiplier: float = Field(default=2.0, env="RETRY_BACKOFF_MULTIPLIER")
    max_retry_backoff_ms: int = Field(default=60000, env="MAX_RETRY_BACKOFF_MS")
    circuit_breaker_failure_threshold: int = Field(default=5, env="CIRCUIT_BREAKER_FAILURE_THRESHOLD")
    circuit_breaker_timeout_ms: int = Field(default=60000, env="CIRCUIT_BREAKER_TIMEOUT_MS")
    dlq_enabled: bool = Field(default=True, env="DLQ_ENABLED")


class ObservabilitySettings(BaseSettings):
    """Observability configuration"""
    metrics_enabled: bool = Field(default=True, env="METRICS_ENABLED")
    metrics_port: int = Field(default=9090, env="METRICS_PORT")
    trace_sampling_rate: float = Field(default=0.1, env="TRACE_SAMPLING_RATE")
    health_check_interval_ms: int = Field(default=30000, env="HEALTH_CHECK_INTERVAL_MS")
    jaeger_agent_host: str = Field(default="localhost", env="JAEGER_AGENT_HOST")
    jaeger_agent_port: int = Field(default=6831, env="JAEGER_AGENT_PORT")


class ReconciliationSettings(BaseSettings):
    """Reconciliation configuration"""
    enabled: bool = Field(default=True, env="RECONCILIATION_ENABLED")
    interval_minutes: int = Field(default=60, env="RECONCILIATION_INTERVAL_MINUTES")
    drift_warning_threshold: float = Field(default=1.0, env="RECONCILIATION_DRIFT_WARNING_THRESHOLD")
    drift_critical_threshold: float = Field(default=5.0, env="RECONCILIATION_DRIFT_CRITICAL_THRESHOLD")
    sample_size: int = Field(default=1000, env="RECONCILIATION_SAMPLE_SIZE")
    tables: List[str] = Field(default_factory=list, env="RECONCILIATION_TABLES")


class Settings(BaseSettings):
    """Main application settings"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )

    # Application settings
    environment: str = Field(default="development", env="ENVIRONMENT")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8080, env="API_PORT")

    # Component settings
    cassandra: CassandraSettings = Field(default_factory=CassandraSettings)
    postgresql: PostgreSQLSettings = Field(default_factory=PostgreSQLSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    vault: VaultSettings = Field(default_factory=VaultSettings)
    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)
    error_handling: ErrorHandlingSettings = Field(default_factory=ErrorHandlingSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    reconciliation: ReconciliationSettings = Field(default_factory=ReconciliationSettings)

    def load_credentials_from_vault(self) -> None:
        """
        Load credentials from Vault in production mode.

        If VAULT_ENABLED is True and environment is production,
        fetches credentials from Vault and updates settings.
        """
        if not self.vault.enabled or self.environment == "development":
            return

        try:
            from src.repositories.vault_repository import VaultRepository

            vault_repo = VaultRepository(self)
            vault_repo.connect()

            cassandra_creds = vault_repo.get_credentials("cdc/cassandra", use_cache=True)
            self.cassandra.username = cassandra_creds.get("username", self.cassandra.username)
            self.cassandra.password = cassandra_creds.get("password", self.cassandra.password)

            postgres_creds = vault_repo.get_database_credentials("postgresql-writer", use_cache=True)
            self.postgresql.user = postgres_creds.get("username", self.postgresql.user)
            self.postgresql.password = postgres_creds.get("password", self.postgresql.password)

        except Exception as e:
            import structlog
            logger = structlog.get_logger(__name__)
            logger.error("failed_to_load_vault_credentials", error=str(e))
            raise


# Global settings instance
settings = Settings()
