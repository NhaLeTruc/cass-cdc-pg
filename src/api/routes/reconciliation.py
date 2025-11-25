"""Reconciliation API endpoints (T119-T123).

REST API for triggering and querying reconciliation jobs.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.models.reconciliation_job import (
    ReconciliationJob,
    JobType,
    ValidationStrategy,
    JobStatus
)
from src.models.reconciliation_mismatch import (
    ReconciliationMismatch,
    MismatchType,
    ResolutionStatus
)
from src.repositories.reconciliation_repository import ReconciliationRepository
from src.services.reconciliation_scheduler import ReconciliationScheduler


router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


class TriggerReconciliationRequest(BaseModel):
    """Request model for triggering reconciliation."""

    tables: List[str] = Field(..., min_items=1, description="List of tables to reconcile")
    validation_strategy: ValidationStrategy = Field(
        ValidationStrategy.ROW_COUNT,
        description="Validation strategy to use"
    )


class TriggerReconciliationResponse(BaseModel):
    """Response model for reconciliation trigger."""

    job_ids: List[str] = Field(..., description="List of created job IDs")
    status: str = Field(..., description="Trigger status")


class JobListResponse(BaseModel):
    """Response model for job list."""

    jobs: List[dict] = Field(..., description="List of reconciliation jobs")
    total: int = Field(..., description="Total number of jobs matching filters")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Page offset")


class MismatchListResponse(BaseModel):
    """Response model for mismatch list."""

    mismatches: List[dict] = Field(..., description="List of reconciliation mismatches")
    total: int = Field(..., description="Total number of mismatches")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Page offset")


class ResolveMismatchRequest(BaseModel):
    """Request model for resolving mismatch."""

    resolution_status: ResolutionStatus = Field(..., description="Resolution status")
    resolution_notes: Optional[str] = Field(None, description="Resolution notes")


@router.post("/trigger", response_model=TriggerReconciliationResponse)
async def trigger_reconciliation(
    request: TriggerReconciliationRequest,
    scheduler: ReconciliationScheduler = Depends()
) -> TriggerReconciliationResponse:
    """Trigger manual reconciliation for specific tables.

    Triggers on-demand reconciliation jobs for the specified tables.

    Args:
        request: Reconciliation trigger request
        scheduler: Reconciliation scheduler dependency

    Returns:
        Response with created job IDs
    """
    job_ids = []

    for table in request.tables:
        try:
            # Trigger manual reconciliation
            await scheduler.manual_trigger_reconciliation(
                table_name=table,
                source_keyspace="warehouse",
                target_schema="public"
            )

            # Get latest job for this table
            jobs = scheduler.reconciliation_repo.list_jobs(
                table_name=table,
                job_type=JobType.MANUAL_ONDEMAND,
                limit=1
            )

            if jobs:
                job_ids.append(str(jobs[0].job_id))

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to trigger reconciliation for {table}: {str(e)}"
            )

    return TriggerReconciliationResponse(
        job_ids=job_ids,
        status="RUNNING" if job_ids else "FAILED"
    )


@router.get("/jobs", response_model=JobListResponse)
async def list_reconciliation_jobs(
    table: Optional[str] = Query(None, description="Filter by table name"),
    status: Optional[JobStatus] = Query(None, description="Filter by job status"),
    from_date: Optional[datetime] = Query(None, description="Filter by start date (>=)"),
    to_date: Optional[datetime] = Query(None, description="Filter by end date (<=)"),
    limit: int = Query(100, ge=1, le=1000, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    repo: ReconciliationRepository = Depends()
) -> JobListResponse:
    """List reconciliation jobs with filters.

    Returns paginated list of reconciliation jobs matching the filters.

    Args:
        table: Optional table name filter
        status: Optional job status filter
        from_date: Optional start date filter
        to_date: Optional end date filter
        limit: Page size (1-1000)
        offset: Page offset
        repo: Reconciliation repository dependency

    Returns:
        Paginated list of jobs
    """
    jobs = repo.list_jobs(
        table_name=table,
        status=status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset
    )

    # Convert to dict for JSON serialization
    jobs_data = [job.to_dict() for job in jobs]

    return JobListResponse(
        jobs=jobs_data,
        total=len(jobs_data),
        limit=limit,
        offset=offset
    )


@router.get("/jobs/{job_id}", response_model=dict)
async def get_reconciliation_job(
    job_id: UUID,
    repo: ReconciliationRepository = Depends()
) -> dict:
    """Get detailed reconciliation job results.

    Returns full job details including nested mismatches.

    Args:
        job_id: Job ID to retrieve
        repo: Reconciliation repository dependency

    Returns:
        Job details with mismatches

    Raises:
        HTTPException: If job not found
    """
    job = repo.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Reconciliation job {job_id} not found"
        )

    return job.to_dict()


@router.get("/mismatches", response_model=MismatchListResponse)
async def list_reconciliation_mismatches(
    table: Optional[str] = Query(None, description="Filter by table name"),
    mismatch_type: Optional[MismatchType] = Query(None, description="Filter by mismatch type"),
    resolution_status: Optional[ResolutionStatus] = Query(
        None,
        description="Filter by resolution status"
    ),
    limit: int = Query(1000, ge=1, le=10000, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    repo: ReconciliationRepository = Depends()
) -> MismatchListResponse:
    """List reconciliation mismatches with filters.

    Returns paginated list of data mismatches detected during reconciliation.

    Args:
        table: Optional table name filter
        mismatch_type: Optional mismatch type filter
        resolution_status: Optional resolution status filter
        limit: Page size (1-10000)
        offset: Page offset
        repo: Reconciliation repository dependency

    Returns:
        Paginated list of mismatches
    """
    mismatches = repo.list_mismatches(
        table_name=table,
        mismatch_type=mismatch_type,
        resolution_status=resolution_status,
        limit=limit,
        offset=offset
    )

    # Convert to dict for JSON serialization
    mismatches_data = [mismatch.to_dict() for mismatch in mismatches]

    return MismatchListResponse(
        mismatches=mismatches_data,
        total=len(mismatches_data),
        limit=limit,
        offset=offset
    )


@router.post("/mismatches/{mismatch_id}/resolve", response_model=dict)
async def resolve_reconciliation_mismatch(
    mismatch_id: UUID,
    request: ResolveMismatchRequest,
    repo: ReconciliationRepository = Depends()
) -> dict:
    """Mark reconciliation mismatch as resolved.

    Updates the resolution status and adds resolution notes.

    Args:
        mismatch_id: Mismatch ID to resolve
        request: Resolution request with status and notes
        repo: Reconciliation repository dependency

    Returns:
        Updated mismatch details

    Raises:
        HTTPException: If mismatch not found
    """
    mismatch = repo.resolve_mismatch(
        mismatch_id=mismatch_id,
        resolution_status=request.resolution_status,
        resolution_notes=request.resolution_notes
    )

    if not mismatch:
        raise HTTPException(
            status_code=404,
            detail=f"Reconciliation mismatch {mismatch_id} not found"
        )

    return {
        "status": "success",
        "mismatch": mismatch.to_dict()
    }
