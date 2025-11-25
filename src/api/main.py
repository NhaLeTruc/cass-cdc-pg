"""FastAPI application for CDC Pipeline observability and management."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from src.api.routes import health, metrics, dlq, reconciliation, gdpr
from src.config.settings import Settings
from src.services.reconciliation_scheduler import ReconciliationScheduler

logger = structlog.get_logger(__name__)

# Global reconciliation scheduler instance
reconciliation_scheduler: ReconciliationScheduler | None = None


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = Settings()

    app = FastAPI(
        title="CDC Pipeline API",
        description="Observability and management API for Cassandra to PostgreSQL CDC pipeline",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle uncaught exceptions."""
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Internal server error",
                "detail": str(exc) if settings.environment == "development" else None,
            },
        )

    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all HTTP requests."""
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None,
        )
        response = await call_next(request)
        logger.info(
            "http_response",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response

    # Include routers
    app.include_router(health.router, tags=["health"])
    app.include_router(metrics.router, tags=["metrics"])
    app.include_router(dlq.router, tags=["dlq"])
    app.include_router(reconciliation.router, tags=["reconciliation"])
    app.include_router(gdpr.router, tags=["gdpr"])

    @app.on_event("startup")
    async def startup_event():
        """Run on application startup."""
        global reconciliation_scheduler

        logger.info("cdc_api_starting", version="1.0.0")

        # Initialize reconciliation scheduler if enabled (T130)
        if settings.reconciliation.enabled:
            from src.repositories.cassandra_repository import CassandraRepository
            from src.repositories.postgresql_repository import PostgreSQLRepository
            from src.repositories.reconciliation_repository import ReconciliationRepository
            from src.services.alert_service import AlertService

            try:
                # Create repository instances
                cassandra_repo = CassandraRepository(settings=settings)
                cassandra_repo.connect()

                postgres_repo = PostgreSQLRepository(settings=settings)
                postgres_repo.connect()

                reconciliation_repo = ReconciliationRepository(
                    connection=postgres_repo.connection
                )

                # Create alert service
                alert_service = AlertService(
                    prometheus_pushgateway_url=settings.observability.prometheus_pushgateway_url,
                    warning_threshold=settings.reconciliation.drift_warning_threshold,
                    critical_threshold=settings.reconciliation.drift_critical_threshold,
                    reconciliation_repo=reconciliation_repo
                )

                # Create and start scheduler
                reconciliation_scheduler = ReconciliationScheduler(
                    reconciliation_repo=reconciliation_repo,
                    cassandra_repo=cassandra_repo,
                    postgres_repo=postgres_repo,
                    enabled=settings.reconciliation.enabled,
                    interval_minutes=settings.reconciliation.interval_minutes,
                    tables=settings.reconciliation.tables,
                    alert_service=alert_service
                )

                await reconciliation_scheduler.start()

                logger.info(
                    "reconciliation_scheduler_started",
                    interval_minutes=settings.reconciliation.interval_minutes,
                    tables=settings.reconciliation.tables
                )

            except Exception as e:
                logger.error(
                    "failed_to_start_reconciliation_scheduler",
                    error=str(e),
                    exc_info=True
                )

    @app.on_event("shutdown")
    async def shutdown_event():
        """Run on application shutdown."""
        global reconciliation_scheduler

        logger.info("cdc_api_shutting_down")

        # Stop reconciliation scheduler
        if reconciliation_scheduler and reconciliation_scheduler.is_running():
            await reconciliation_scheduler.stop()
            logger.info("reconciliation_scheduler_stopped")

    return app


app = create_app()
