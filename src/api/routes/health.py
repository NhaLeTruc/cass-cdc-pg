"""Health check endpoint using HealthCheckService."""

from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
import structlog

from src.config.settings import Settings
from src.monitoring.health_check import HealthCheckService, HealthStatus
from src.repositories.cassandra_repository import CassandraRepository
from src.repositories.postgresql_repository import PostgreSQLRepository
from src.repositories.vault_repository import VaultRepository

logger = structlog.get_logger(__name__)

router = APIRouter()

# Global service instances (initialized once)
_health_service: HealthCheckService | None = None
_cassandra_repo: CassandraRepository | None = None
_postgres_repo: PostgreSQLRepository | None = None
_vault_repo: VaultRepository | None = None


def get_health_service() -> HealthCheckService:
    """Get or create health check service with repository instances."""
    global _health_service, _cassandra_repo, _postgres_repo, _vault_repo

    if _health_service is None:
        settings = Settings()

        try:
            # Initialize repositories
            _cassandra_repo = CassandraRepository(settings=settings)
            _cassandra_repo.connect()

            _postgres_repo = PostgreSQLRepository(settings=settings)
            _postgres_repo.connect()

            _vault_repo = VaultRepository(settings=settings)
            _vault_repo.connect()

            # Create health service
            _health_service = HealthCheckService(
                cassandra_repo=_cassandra_repo,
                postgres_repo=_postgres_repo,
                vault_repo=_vault_repo,
                settings=settings
            )

            logger.info("health_service_initialized")
        except Exception as e:
            logger.error("health_service_initialization_failed", error=str(e), exc_info=True)
            # Return service without repos - will return degraded status
            _health_service = HealthCheckService(settings=settings)

    return _health_service


@router.get("/health")
async def health_check(
    health_service: HealthCheckService = Depends(get_health_service)
):
    """
    Health check endpoint.

    Returns 200 if all components are healthy, 503 if any component is unhealthy.

    Response format:
    {
        "status": "healthy" | "unhealthy" | "degraded",
        "check_time": "2025-11-25T08:00:00Z",
        "components": {
            "cassandra": {"service": "cassandra", "status": "healthy", "details": {...}},
            "postgresql": {"service": "postgresql", "status": "healthy", "details": {...}},
            ...
        }
    }
    """
    logger.info("health_check_requested")

    # Perform health check
    health_result = health_service.check_all()

    response_data = {
        "status": health_result["status"],
        "check_time": datetime.utcnow().isoformat() + "Z",
        "components": health_result["components"],
    }

    # Map health status to HTTP status code
    if health_result["status"] == HealthStatus.HEALTHY:
        status_code = status.HTTP_200_OK
    elif health_result["status"] == HealthStatus.DEGRADED:
        status_code = status.HTTP_200_OK  # Still operational but degraded
    else:  # UNHEALTHY
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    logger.info(
        "health_check_completed",
        overall_status=health_result["status"],
        status_code=status_code,
    )

    return JSONResponse(status_code=status_code, content=response_data)


@router.get("/health/{component}")
async def health_check_component(
    component: str,
    health_service: HealthCheckService = Depends(get_health_service)
):
    """
    Check health of a specific component.

    Args:
        component: Component name (cassandra, postgresql, kafka, schema_registry, vault)

    Returns 200 if component is healthy, 503 if unhealthy.
    """
    logger.info("component_health_check_requested", component=component)

    # Map component name to health check method
    check_methods = {
        "cassandra": health_service.check_cassandra,
        "postgresql": health_service.check_postgresql,
        "kafka": health_service.check_kafka,
        "schema_registry": health_service.check_schema_registry,
        "vault": health_service.check_vault,
    }

    if component not in check_methods:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "status": "error",
                "message": f"Unknown component: {component}",
                "available_components": list(check_methods.keys())
            }
        )

    # Perform component-specific health check
    result = check_methods[component]()

    status_code = (
        status.HTTP_200_OK
        if result["status"] == HealthStatus.HEALTHY
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    response_data = {
        **result,
        "check_time": datetime.utcnow().isoformat() + "Z",
    }

    logger.info(
        "component_health_check_completed",
        component=component,
        component_status=result["status"],
        status_code=status_code,
    )

    return JSONResponse(status_code=status_code, content=response_data)
