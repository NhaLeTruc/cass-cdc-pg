"""Health check endpoint."""

from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
import requests
import structlog

from cassandra.cluster import Cluster
import psycopg2

logger = structlog.get_logger(__name__)

router = APIRouter()


async def check_cassandra() -> Dict[str, Any]:
    """Check Cassandra health."""
    try:
        cluster = Cluster(["localhost"], port=9042)
        session = cluster.connect()
        session.execute("SELECT release_version FROM system.local")
        cluster.shutdown()
        return {"status": "healthy"}
    except Exception as e:
        logger.error("cassandra_health_check_failed", error=str(e))
        return {"status": "unhealthy", "message": str(e)}


async def check_postgresql() -> Dict[str, Any]:
    """Check PostgreSQL health."""
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="warehouse",
            user="cdc_user",
            password="cdc_password",
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return {"status": "healthy"}
    except Exception as e:
        logger.error("postgresql_health_check_failed", error=str(e))
        return {"status": "unhealthy", "message": str(e)}


async def check_kafka() -> Dict[str, Any]:
    """Check Kafka health via Kafka Connect."""
    try:
        response = requests.get("http://localhost:8083/", timeout=5)
        if response.status_code == 200:
            return {"status": "healthy"}
        return {"status": "unhealthy", "message": f"Status code: {response.status_code}"}
    except Exception as e:
        logger.error("kafka_health_check_failed", error=str(e))
        return {"status": "unhealthy", "message": str(e)}


async def check_schema_registry() -> Dict[str, Any]:
    """Check Schema Registry health."""
    try:
        response = requests.get("http://localhost:8081/subjects", timeout=5)
        if response.status_code == 200:
            return {"status": "healthy"}
        return {"status": "unhealthy", "message": f"Status code: {response.status_code}"}
    except Exception as e:
        logger.error("schema_registry_health_check_failed", error=str(e))
        return {"status": "unhealthy", "message": str(e)}


async def check_vault() -> Dict[str, Any]:
    """Check Vault health."""
    try:
        response = requests.get("http://localhost:8200/v1/sys/health", timeout=5)
        if response.status_code in [200, 429, 472, 473]:  # Vault health status codes
            return {"status": "healthy"}
        return {"status": "unhealthy", "message": f"Status code: {response.status_code}"}
    except Exception as e:
        logger.error("vault_health_check_failed", error=str(e))
        return {"status": "unhealthy", "message": str(e)}


@router.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns 200 if all components are healthy, 503 if any component is unhealthy.
    """
    logger.info("health_check_requested")

    components = {
        "cassandra": await check_cassandra(),
        "postgresql": await check_postgresql(),
        "kafka": await check_kafka(),
        "schema_registry": await check_schema_registry(),
        "vault": await check_vault(),
    }

    # Determine overall status
    all_healthy = all(c["status"] == "healthy" for c in components.values())
    overall_status = "healthy" if all_healthy else "unhealthy"

    response_data = {
        "status": overall_status,
        "check_time": datetime.utcnow().isoformat() + "Z",
        "components": components,
    }

    status_code = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    logger.info(
        "health_check_completed",
        overall_status=overall_status,
        status_code=status_code,
    )

    return JSONResponse(status_code=status_code, content=response_data)
