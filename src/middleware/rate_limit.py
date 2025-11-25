"""Rate limiting middleware using slowapi."""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
import structlog

logger = structlog.get_logger(__name__)

# Create limiter instance
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000/hour", "100/minute"],  # Default rate limits
    storage_uri="memory://",  # Use in-memory storage (consider Redis for production)
    strategy="fixed-window",  # or "moving-window" for more accuracy
)


# Alias for backward compatibility
RateLimitMiddleware = SlowAPIMiddleware


def get_limiter() -> Limiter:
    """Get the limiter instance for use in route decorators."""
    return limiter


def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Custom rate limit exceeded handler."""
    logger.warning(
        "rate_limit_exceeded",
        path=request.url.path,
        client=get_remote_address(request),
        limit=str(exc.detail)
    )
    return _rate_limit_exceeded_handler(request, exc)
