"""FastAPI application for CDC Pipeline observability and management."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from src.api.routes import health, metrics, dlq
from src.config.settings import Settings

logger = structlog.get_logger(__name__)


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

    @app.on_event("startup")
    async def startup_event():
        """Run on application startup."""
        logger.info("cdc_api_starting", version="1.0.0")

    @app.on_event("shutdown")
    async def shutdown_event():
        """Run on application shutdown."""
        logger.info("cdc_api_shutting_down")

    return app


app = create_app()
