"""DLQ management API endpoints."""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import structlog

from src.services.dlq_service import DLQService
from src.models.dlq_record import ErrorType, ResolutionStatus
from src.config.settings import Settings

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/dlq")


class ReplayRequest(BaseModel):
    """Request model for DLQ replay."""

    dlq_ids: List[int] = Field(..., description="List of DLQ record IDs to replay")
    resolution_notes: Optional[str] = Field(None, description="Notes about the resolution")
    retry_strategy: str = Field("immediate", description="Strategy for replay: immediate, batch, scheduled")


class ReplayResponse(BaseModel):
    """Response model for DLQ replay."""

    replayed_count: int = Field(..., description="Number of events successfully replayed")
    failed_count: int = Field(..., description="Number of events that failed to replay")
    message: str = Field(..., description="Summary message")


class DLQRecordResponse(BaseModel):
    """Response model for DLQ record."""

    dlq_id: str
    source_table: str
    error_type: str
    error_message: str
    retry_count: int
    dlq_timestamp: str
    resolution_status: str
    first_failed_at: Optional[str] = None
    last_retry_at: Optional[str] = None
    resolution_notes: Optional[str] = None
    resolved_at: Optional[str] = None


class DLQRecordsResponse(BaseModel):
    """Paginated response for DLQ records."""

    records: List[DLQRecordResponse]
    total: int
    limit: int
    offset: int


class DLQStatsResponse(BaseModel):
    """Response model for DLQ statistics."""

    total_records: int
    by_error_type: dict
    by_resolution_status: dict
    by_table: dict


@router.post("/replay", response_model=ReplayResponse)
async def replay_dlq_events(request: ReplayRequest):
    """
    Replay failed events from DLQ.

    After fixing the root cause of failures, use this endpoint to reprocess
    events that were sent to the Dead Letter Queue.

    Args:
        request: Replay request with dlq_ids and resolution notes

    Returns:
        Replay response with success/failure counts

    Raises:
        HTTPException: If replay fails
    """
    logger.info(
        "dlq_replay_requested",
        dlq_ids=request.dlq_ids,
        retry_strategy=request.retry_strategy,
    )

    try:
        settings = Settings()
        dlq_service = DLQService(settings)

        result = dlq_service.replay_events(
            dlq_ids=request.dlq_ids,
            resolution_notes=request.resolution_notes,
            retry_strategy=request.retry_strategy,
        )

        logger.info(
            "dlq_replay_completed",
            replayed=result["replayed_count"],
            failed=result["failed_count"],
        )

        return ReplayResponse(**result)

    except Exception as e:
        logger.error(
            "dlq_replay_failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"DLQ replay failed: {str(e)}")


@router.get("/records", response_model=DLQRecordsResponse)
async def get_dlq_records(
    error_type: Optional[str] = Query(None, description="Filter by error type"),
    resolution_status: Optional[str] = Query(None, description="Filter by resolution status"),
    table: Optional[str] = Query(None, description="Filter by source table"),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
):
    """
    Query DLQ records with filters and pagination.

    Returns a list of DLQ records matching the provided filters.

    Args:
        error_type: Filter by error type (SCHEMA_MISMATCH, TYPE_CONVERSION_ERROR, etc.)
        resolution_status: Filter by resolution status (PENDING, RESOLVED, etc.)
        table: Filter by source table name
        start_date: Filter by failed_at >= start_date
        end_date: Filter by failed_at <= end_date
        limit: Maximum number of records to return
        offset: Number of records to skip

    Returns:
        Paginated list of DLQ records

    Raises:
        HTTPException: If query fails
    """
    logger.info(
        "dlq_records_query",
        error_type=error_type,
        resolution_status=resolution_status,
        table=table,
        limit=limit,
        offset=offset,
    )

    try:
        settings = Settings()
        dlq_service = DLQService(settings)

        # Parse filters
        error_type_enum = ErrorType(error_type) if error_type else None
        resolution_status_enum = ResolutionStatus(resolution_status) if resolution_status else None
        start_datetime = datetime.fromisoformat(start_date) if start_date else None
        end_datetime = datetime.fromisoformat(end_date) if end_date else None

        records = dlq_service.query_dlq_records(
            error_type=error_type_enum,
            resolution_status=resolution_status_enum,
            table=table,
            start_date=start_datetime,
            end_date=end_datetime,
            limit=limit,
            offset=offset,
        )

        # Get total count for pagination
        all_records = dlq_service.query_dlq_records(
            error_type=error_type_enum,
            resolution_status=resolution_status_enum,
            table=table,
            start_date=start_datetime,
            end_date=end_datetime,
            limit=10000,
            offset=0,
        )
        total = len(all_records)

        response_records = [
            DLQRecordResponse(
                dlq_id=str(record.dlq_id),
                source_table=record.source_table,
                error_type=record.error_type.value,
                error_message=record.error_message,
                retry_count=record.retry_count,
                dlq_timestamp=record.dlq_timestamp.isoformat(),
                resolution_status=record.resolution_status.value,
                first_failed_at=record.first_failed_at.isoformat() if record.first_failed_at else None,
                last_retry_at=record.last_retry_at.isoformat() if record.last_retry_at else None,
                resolution_notes=record.resolution_notes,
                resolved_at=record.resolved_at.isoformat() if record.resolved_at else None,
            )
            for record in records
        ]

        logger.info("dlq_records_retrieved", count=len(response_records), total=total)

        return DLQRecordsResponse(
            records=response_records,
            total=total,
            limit=limit,
            offset=offset,
        )

    except ValueError as e:
        logger.error("invalid_filter_value", error=str(e))
        raise HTTPException(status_code=400, detail=f"Invalid filter value: {str(e)}")

    except Exception as e:
        logger.error(
            "dlq_records_query_failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"DLQ query failed: {str(e)}")


@router.get("/stats", response_model=DLQStatsResponse)
async def get_dlq_stats():
    """
    Get statistics about DLQ records.

    Returns:
        DLQ statistics including counts by error type, resolution status, and table

    Raises:
        HTTPException: If stats retrieval fails
    """
    logger.info("dlq_stats_requested")

    try:
        settings = Settings()
        dlq_service = DLQService(settings)

        stats = dlq_service.get_dlq_stats()

        logger.info("dlq_stats_retrieved", total=stats["total_records"])

        return DLQStatsResponse(**stats)

    except Exception as e:
        logger.error(
            "dlq_stats_failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"DLQ stats retrieval failed: {str(e)}")
