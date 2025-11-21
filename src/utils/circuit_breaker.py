"""
Circuit breaker implementation for PostgreSQL connections (FR-020).
Opens after 5 consecutive failures, half-open after 60 seconds.
"""
import time
from enum import Enum
from typing import Callable, Any

from src.config.logging_config import get_logger
from src.config.settings import settings

logger = get_logger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failures exceeded threshold
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open"""
    pass


class CircuitBreaker:
    """Circuit breaker for fault tolerance"""

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        name: str = "default"
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout_seconds: Seconds to wait before moving to half-open
            name: Name for logging
        """
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.name = name
        self.failure_count = 0
        self.last_failure_time: float = 0
        self.state = CircuitBreakerState.CLOSED

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit is open
        """
        if self.state == CircuitBreakerState.OPEN:
            if time.time() - self.last_failure_time >= self.timeout_seconds:
                logger.info(
                    "circuit_breaker_half_open",
                    name=self.name,
                    failure_count=self.failure_count
                )
                self.state = CircuitBreakerState.HALF_OPEN
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is open"
                )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self) -> None:
        """Handle successful execution"""
        if self.state == CircuitBreakerState.HALF_OPEN:
            logger.info(
                "circuit_breaker_closed",
                name=self.name,
                previous_failures=self.failure_count
            )
            self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0

    def _on_failure(self) -> None:
        """Handle failed execution"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitBreakerState.OPEN:
                logger.warning(
                    "circuit_breaker_opened",
                    name=self.name,
                    failure_count=self.failure_count
                )
                self.state = CircuitBreakerState.OPEN
