"""
Health check service for all components (FR-028).
"""
import time
from enum import Enum
from typing import Dict, Any, Optional

import httpx
from kafka import KafkaAdminClient
from kafka.errors import KafkaError

from src.config.logging_config import get_logger
from src.config.settings import Settings
from src.repositories.cassandra_repository import CassandraRepository
from src.repositories.postgresql_repository import PostgreSQLRepository
from src.repositories.vault_repository import VaultRepository

logger = get_logger(__name__)


class HealthStatus(str, Enum):
    """Health check status"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


class HealthCheckService:
    """Service for checking health of all components"""

    def __init__(
        self,
        cassandra_repo: Optional[CassandraRepository] = None,
        postgres_repo: Optional[PostgreSQLRepository] = None,
        vault_repo: Optional[VaultRepository] = None,
        settings: Optional[Settings] = None
    ) -> None:
        """
        Initialize health check service.

        Args:
            cassandra_repo: Cassandra repository instance
            postgres_repo: PostgreSQL repository instance
            vault_repo: Vault repository instance
            settings: Application settings
        """
        self.cassandra_repo = cassandra_repo
        self.postgres_repo = postgres_repo
        self.vault_repo = vault_repo
        self.settings = settings or Settings()

    def check_cassandra(self) -> Dict[str, Any]:
        """Check Cassandra connection health"""
        if not self.cassandra_repo:
            return {
                "service": "cassandra",
                "status": HealthStatus.DEGRADED,
                "details": {"connected": False, "message": "Repository not initialized"}
            }

        start_time = time.time()
        try:
            # Execute simple query to verify connection
            result = self.cassandra_repo.session.execute(
                "SELECT now() FROM system.local"
            )
            row = result.one()
            latency_ms = (time.time() - start_time) * 1000

            return {
                "service": "cassandra",
                "status": HealthStatus.HEALTHY,
                "details": {
                    "connected": True,
                    "latency_ms": round(latency_ms, 2),
                    "timestamp": str(row.now) if row else None
                }
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error("cassandra_health_check_failed", error=str(e), exc_info=True)
            return {
                "service": "cassandra",
                "status": HealthStatus.UNHEALTHY,
                "details": {
                    "connected": False,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e)
                }
            }

    def check_postgresql(self) -> Dict[str, Any]:
        """Check PostgreSQL connection health"""
        if not self.postgres_repo:
            return {
                "service": "postgresql",
                "status": HealthStatus.DEGRADED,
                "details": {"connected": False, "message": "Repository not initialized"}
            }

        start_time = time.time()
        try:
            # Execute simple query to verify connection
            with self.postgres_repo.connection.cursor() as cursor:
                cursor.execute("SELECT 1, NOW()")
                result = cursor.fetchone()
            latency_ms = (time.time() - start_time) * 1000

            return {
                "service": "postgresql",
                "status": HealthStatus.HEALTHY,
                "details": {
                    "connected": True,
                    "latency_ms": round(latency_ms, 2),
                    "timestamp": str(result[1]) if result else None
                }
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error("postgresql_health_check_failed", error=str(e), exc_info=True)
            return {
                "service": "postgresql",
                "status": HealthStatus.UNHEALTHY,
                "details": {
                    "connected": False,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e)
                }
            }

    def check_kafka(self) -> Dict[str, Any]:
        """Check Kafka connection health"""
        start_time = time.time()
        try:
            # Create admin client to verify connection
            admin_client = KafkaAdminClient(
                bootstrap_servers=self.settings.kafka.bootstrap_servers,
                request_timeout_ms=5000
            )

            # List topics to verify connectivity
            topics = admin_client.list_topics()
            admin_client.close()

            latency_ms = (time.time() - start_time) * 1000

            return {
                "service": "kafka",
                "status": HealthStatus.HEALTHY,
                "details": {
                    "connected": True,
                    "latency_ms": round(latency_ms, 2),
                    "topic_count": len(topics)
                }
            }
        except KafkaError as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error("kafka_health_check_failed", error=str(e), exc_info=True)
            return {
                "service": "kafka",
                "status": HealthStatus.UNHEALTHY,
                "details": {
                    "connected": False,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e)
                }
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error("kafka_health_check_failed", error=str(e), exc_info=True)
            return {
                "service": "kafka",
                "status": HealthStatus.UNHEALTHY,
                "details": {
                    "connected": False,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e)
                }
            }

    def check_schema_registry(self) -> Dict[str, Any]:
        """Check Schema Registry health"""
        start_time = time.time()
        try:
            # HTTP GET to Schema Registry subjects endpoint
            schema_registry_url = self.settings.kafka.schema_registry_url
            response = httpx.get(
                f"{schema_registry_url}/subjects",
                timeout=5.0
            )
            response.raise_for_status()

            subjects = response.json()
            latency_ms = (time.time() - start_time) * 1000

            return {
                "service": "schema_registry",
                "status": HealthStatus.HEALTHY,
                "details": {
                    "available": True,
                    "latency_ms": round(latency_ms, 2),
                    "subject_count": len(subjects)
                }
            }
        except httpx.HTTPStatusError as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error("schema_registry_health_check_failed", error=str(e), exc_info=True)
            return {
                "service": "schema_registry",
                "status": HealthStatus.UNHEALTHY,
                "details": {
                    "available": False,
                    "latency_ms": round(latency_ms, 2),
                    "status_code": e.response.status_code,
                    "error": str(e)
                }
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error("schema_registry_health_check_failed", error=str(e), exc_info=True)
            return {
                "service": "schema_registry",
                "status": HealthStatus.UNHEALTHY,
                "details": {
                    "available": False,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e)
                }
            }

    def check_vault(self) -> Dict[str, Any]:
        """Check Vault connection health"""
        if not self.vault_repo:
            return {
                "service": "vault",
                "status": HealthStatus.DEGRADED,
                "details": {"connected": False, "message": "Repository not initialized"}
            }

        start_time = time.time()
        try:
            # Check if Vault is initialized and unsealed
            health_status = self.vault_repo.client.sys.read_health_status(method='GET')
            latency_ms = (time.time() - start_time) * 1000

            is_sealed = health_status.get('sealed', True)
            is_initialized = health_status.get('initialized', False)

            if is_sealed:
                status = HealthStatus.UNHEALTHY
            elif not is_initialized:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.HEALTHY

            return {
                "service": "vault",
                "status": status,
                "details": {
                    "connected": True,
                    "sealed": is_sealed,
                    "initialized": is_initialized,
                    "latency_ms": round(latency_ms, 2),
                    "version": health_status.get('version')
                }
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error("vault_health_check_failed", error=str(e), exc_info=True)
            return {
                "service": "vault",
                "status": HealthStatus.UNHEALTHY,
                "details": {
                    "connected": False,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e)
                }
            }

    def check_all(self) -> Dict[str, Any]:
        """Check health of all components"""
        components = {
            "cassandra": self.check_cassandra(),
            "postgresql": self.check_postgresql(),
            "kafka": self.check_kafka(),
            "schema_registry": self.check_schema_registry(),
            "vault": self.check_vault(),
        }

        # Determine overall status
        statuses = [comp["status"] for comp in components.values()]
        if all(status == HealthStatus.HEALTHY for status in statuses):
            overall_status = HealthStatus.HEALTHY
        elif any(status == HealthStatus.UNHEALTHY for status in statuses):
            overall_status = HealthStatus.UNHEALTHY
        else:
            overall_status = HealthStatus.DEGRADED

        return {
            "status": overall_status,
            "components": components
        }
