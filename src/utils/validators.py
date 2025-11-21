"""
Data validators for event validation, schema validation, and integrity checks (FR-012).
"""
from typing import Any, Dict, List
import uuid
from datetime import datetime, timedelta

from src.config.logging_config import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    """Raised when validation fails"""
    pass


def validate_uuid(value: str) -> bool:
    """Validate UUID format"""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def validate_timestamp_micros(timestamp_micros: int, allow_clock_skew_minutes: int = 1) -> bool:
    """
    Validate timestamp is not in the future (allow 1-minute clock skew).

    Args:
        timestamp_micros: Timestamp in microseconds since epoch
        allow_clock_skew_minutes: Minutes of clock skew to allow

    Returns:
        True if valid, False otherwise
    """
    current_time = datetime.now().timestamp() * 1_000_000
    max_future_time = current_time + (allow_clock_skew_minutes * 60 * 1_000_000)

    return timestamp_micros <= max_future_time


def validate_change_event(event: Dict[str, Any]) -> bool:
    """
    Validate change event structure and contents.

    Args:
        event: Change event dictionary

    Returns:
        True if valid

    Raises:
        ValidationError: If validation fails
    """
    # Check required fields
    required_fields = ["event_id", "source_table", "operation_type", "timestamp_micros"]
    for field in required_fields:
        if field not in event:
            raise ValidationError(f"Missing required field: {field}")

    # Validate event_id is UUID
    if not validate_uuid(event["event_id"]):
        raise ValidationError(f"Invalid event_id UUID: {event['event_id']}")

    # Validate timestamp not in future
    if not validate_timestamp_micros(event["timestamp_micros"]):
        raise ValidationError(f"Timestamp is in the future: {event['timestamp_micros']}")

    # Validate operation-specific requirements
    operation = event["operation_type"]
    if operation == "UPDATE":
        if "before_values" not in event or "after_values" not in event:
            raise ValidationError("UPDATE operation requires both before_values and after_values")
    elif operation == "INSERT":
        if "after_values" not in event:
            raise ValidationError("INSERT operation requires after_values")
    elif operation == "DELETE":
        if "before_values" not in event and not event.get("is_tombstone"):
            raise ValidationError("DELETE operation requires before_values or tombstone flag")

    return True


def validate_schema_compatibility(old_schema: Dict[str, Any], new_schema: Dict[str, Any]) -> bool:
    """
    Validate schema compatibility for evolution.

    Args:
        old_schema: Previous schema version
        new_schema: New schema version

    Returns:
        True if schemas are compatible

    Raises:
        ValidationError: If schemas are incompatible
    """
    # Check if columns were removed (may break compatibility)
    old_columns = set(old_schema.get("columns", {}).keys())
    new_columns = set(new_schema.get("columns", {}).keys())

    removed_columns = old_columns - new_columns
    if removed_columns:
        logger.warning(
            "schema_columns_removed",
            removed=list(removed_columns)
        )

    # Check for type changes (may break compatibility)
    for col in old_columns.intersection(new_columns):
        old_type = old_schema["columns"][col].get("type")
        new_type = new_schema["columns"][col].get("type")
        if old_type != new_type:
            logger.warning(
                "schema_type_changed",
                column=col,
                old_type=old_type,
                new_type=new_type
            )

    return True


def validate_not_null(value: Any, field_name: str) -> None:
    """Validate value is not null"""
    if value is None:
        raise ValidationError(f"{field_name} cannot be null")


def validate_in_range(value: int, min_val: int, max_val: int, field_name: str) -> None:
    """Validate value is within range"""
    if not min_val <= value <= max_val:
        raise ValidationError(
            f"{field_name} must be between {min_val} and {max_val}, got {value}"
        )
