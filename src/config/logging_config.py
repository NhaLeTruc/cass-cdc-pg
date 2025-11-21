"""
Structured logging configuration using structlog with JSON output.
"""
import logging
import sys
from typing import Any, Dict

import structlog

from src.config.settings import settings


def filter_sensitive_data(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Filter sensitive data from logs (passwords, tokens, etc.)"""
    sensitive_keys = ["password", "token", "secret", "api_key", "auth", "credential"]

    def redact_dict(d: Dict[str, Any]) -> Dict[str, Any]:
        return {
            k: "***REDACTED***" if any(sensitive in k.lower() for sensitive in sensitive_keys) else v
            for k, v in d.items()
        }

    return redact_dict(event_dict)


def configure_logging() -> None:
    """Configure structlog for JSON logging with correlation IDs"""

    # Processors for structlog
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        filter_sensitive_data,
        structlog.processors.UnicodeDecoder(),
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


def get_logger(name: str) -> Any:
    """Get a structured logger instance"""
    return structlog.get_logger(name)
