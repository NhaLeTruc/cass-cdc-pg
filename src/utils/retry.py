"""
Retry utility using tenacity with exponential backoff (FR-019).
Retry intervals: 1s, 2s, 4s, 8s, up to 60s max.
"""
from tenacity import (
    retry,
    stop_after_delay,
    wait_exponential,
    retry_if_exception_type,
)

from src.config.settings import settings


def with_retry(
    max_delay_seconds: int = 300,  # 5 minutes
    min_wait: int = 1,
    max_wait: int = 60,
    multiplier: float = 2.0,
):
    """
    Decorator for retrying operations with exponential backoff.

    Args:
        max_delay_seconds: Maximum total retry time
        min_wait: Minimum wait time between retries (seconds)
        max_wait: Maximum wait time between retries (seconds)
        multiplier: Backoff multiplier
    """
    return retry(
        wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
        stop=stop_after_delay(max_delay_seconds),
        reraise=True,
    )


def with_retry_on_exception(exception_types: tuple, max_delay_seconds: int = 300):
    """
    Decorator for retrying only on specific exception types.

    Args:
        exception_types: Tuple of exception types to retry on
        max_delay_seconds: Maximum total retry time
    """
    return retry(
        wait=wait_exponential(multiplier=2.0, min=1, max=60),
        stop=stop_after_delay(max_delay_seconds),
        retry=retry_if_exception_type(exception_types),
        reraise=True,
    )
