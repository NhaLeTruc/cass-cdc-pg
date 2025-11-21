"""Prometheus metrics endpoint."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint.

    Exposes all registered Prometheus metrics in text format for scraping.
    """
    logger.debug("metrics_requested")

    # Generate Prometheus metrics in text format
    metrics_output = generate_latest()

    return Response(content=metrics_output, media_type=CONTENT_TYPE_LATEST)
