"""
Kafka Connect Single Message Transform (SMT) for out-of-order event handling.

This SMT implements Last-Write-Wins (LWW) conflict resolution strategy:
1. Compare incoming event's timestamp_micros with existing record's _cdc_timestamp_micros
2. If incoming > existing: Accept event (newer write)
3. If incoming < existing: Reject event (stale write)
4. If equal: Use event_id lexicographic comparison as tiebreaker

Note: This is a Python implementation for reference and custom processing.
For Kafka Connect, a Java SMT would be deployed. This module provides the
logic that can be called from custom Python consumers or used as reference
for Java SMT implementation.
"""

from typing import Dict, Any, Optional
import structlog

from src.monitoring.metrics import (
    cdc_events_rejected_total,
    cdc_conflict_resolution_total,
)

logger = structlog.get_logger(__name__)


class TimestampConflictResolver:
    """
    Resolves conflicts for out-of-order events using Last-Write-Wins strategy.

    This implements the conflict resolution algorithm defined in data-model.md:
    - Primary ordering: timestamp_micros (microsecond precision)
    - Tiebreaker: event_id (lexicographic comparison)
    """

    def __init__(self) -> None:
        """Initialize the conflict resolver."""
        self._logger = logger.bind(component="timestamp_conflict_resolver")

    def should_accept_event(
        self,
        incoming_event: Dict[str, Any],
        existing_record: Optional[Dict[str, Any]],
    ) -> bool:
        """
        Determine if incoming event should be accepted based on LWW strategy.

        Args:
            incoming_event: New event with timestamp_micros and event_id
            existing_record: Existing database record with _cdc_timestamp_micros
                           (None if record doesn't exist yet)

        Returns:
            True if event should be accepted, False if rejected as stale
        """
        if existing_record is None:
            self._logger.debug(
                "accepting_event_new_record",
                event_id=incoming_event.get("event_id"),
            )
            cdc_conflict_resolution_total.labels(
                resolution="accept_new_record"
            ).inc()
            return True

        incoming_timestamp = incoming_event.get("timestamp_micros")
        existing_timestamp = existing_record.get("_cdc_timestamp_micros")

        if incoming_timestamp is None:
            self._logger.error(
                "incoming_event_missing_timestamp",
                event_id=incoming_event.get("event_id"),
            )
            cdc_events_rejected_total.labels(
                table=incoming_event.get("source_table", "unknown"),
                reason="missing_timestamp",
            ).inc()
            return False

        if existing_timestamp is None:
            self._logger.debug(
                "accepting_event_no_existing_timestamp",
                event_id=incoming_event.get("event_id"),
            )
            cdc_conflict_resolution_total.labels(
                resolution="accept_missing_existing_timestamp"
            ).inc()
            return True

        if incoming_timestamp > existing_timestamp:
            self._logger.debug(
                "accepting_newer_event",
                event_id=incoming_event.get("event_id"),
                incoming_ts=incoming_timestamp,
                existing_ts=existing_timestamp,
            )
            cdc_conflict_resolution_total.labels(
                resolution="accept_newer_timestamp"
            ).inc()
            return True

        elif incoming_timestamp < existing_timestamp:
            self._logger.info(
                "rejecting_older_event",
                event_id=incoming_event.get("event_id"),
                incoming_ts=incoming_timestamp,
                existing_ts=existing_timestamp,
                time_diff_micros=existing_timestamp - incoming_timestamp,
            )
            cdc_events_rejected_total.labels(
                table=incoming_event.get("source_table", "unknown"),
                reason="stale_timestamp",
            ).inc()
            cdc_conflict_resolution_total.labels(
                resolution="reject_older_timestamp"
            ).inc()
            return False

        else:
            return self._resolve_timestamp_tie(incoming_event, existing_record)

    def _resolve_timestamp_tie(
        self,
        incoming_event: Dict[str, Any],
        existing_record: Dict[str, Any],
    ) -> bool:
        """
        Resolve conflict when timestamps are equal using event_id tiebreaker.

        Uses lexicographic comparison: higher event_id wins.

        Args:
            incoming_event: New event with event_id
            existing_record: Existing record (need to reconstruct event_id)

        Returns:
            True if incoming event wins tiebreaker, False otherwise
        """
        incoming_event_id = incoming_event.get("event_id")
        existing_event_id = existing_record.get("_last_event_id")

        if incoming_event_id is None:
            self._logger.error(
                "incoming_event_missing_event_id",
                timestamp=incoming_event.get("timestamp_micros"),
            )
            cdc_events_rejected_total.labels(
                table=incoming_event.get("source_table", "unknown"),
                reason="missing_event_id",
            ).inc()
            return False

        if existing_event_id is None:
            self._logger.warning(
                "existing_record_missing_event_id_accepting_by_default",
                incoming_event_id=incoming_event_id,
            )
            cdc_conflict_resolution_total.labels(
                resolution="accept_tie_missing_existing_event_id"
            ).inc()
            return True

        if incoming_event_id > existing_event_id:
            self._logger.debug(
                "accepting_event_higher_event_id",
                incoming_event_id=incoming_event_id,
                existing_event_id=existing_event_id,
            )
            cdc_conflict_resolution_total.labels(
                resolution="accept_tie_higher_event_id"
            ).inc()
            return True
        else:
            self._logger.info(
                "rejecting_event_lower_event_id",
                incoming_event_id=incoming_event_id,
                existing_event_id=existing_event_id,
            )
            cdc_events_rejected_total.labels(
                table=incoming_event.get("source_table", "unknown"),
                reason="lower_event_id_tiebreaker",
            ).inc()
            cdc_conflict_resolution_total.labels(
                resolution="reject_tie_lower_event_id"
            ).inc()
            return False

    def enrich_event_with_conflict_metadata(
        self,
        event: Dict[str, Any],
        was_accepted: bool,
        existing_record: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Add conflict resolution metadata to event for observability.

        Args:
            event: Original event
            was_accepted: Whether event was accepted
            existing_record: Existing record if any

        Returns:
            Event enriched with conflict resolution metadata
        """
        enriched = event.copy()

        enriched["_conflict_resolution"] = {
            "was_accepted": was_accepted,
            "had_conflict": existing_record is not None,
            "resolution_strategy": "last_write_wins",
        }

        if existing_record:
            enriched["_conflict_resolution"]["existing_timestamp_micros"] = (
                existing_record.get("_cdc_timestamp_micros")
            )
            enriched["_conflict_resolution"]["timestamp_difference_micros"] = (
                event.get("timestamp_micros", 0)
                - existing_record.get("_cdc_timestamp_micros", 0)
            )

        return enriched


def create_conflict_resolver_query(table_name: str) -> str:
    """
    Generate SQL query to check for existing record before insert/update.

    This query is used by JDBC Sink Connector or custom consumers to fetch
    the existing record for conflict resolution.

    Args:
        table_name: PostgreSQL table name

    Returns:
        SQL query string
    """
    return f"""
        SELECT
            _cdc_timestamp_micros,
            id as _last_event_id
        FROM {table_name}
        WHERE id = ?
    """


def create_conditional_upsert_query(table_name: str, columns: list) -> str:
    """
    Generate SQL for conditional upsert that only updates if timestamp is newer.

    This implements LWW at the database level using PostgreSQL's ON CONFLICT.

    Args:
        table_name: PostgreSQL table name
        columns: List of column names

    Returns:
        SQL query with conditional update
    """
    column_list = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))

    update_columns = [col for col in columns if col != "id"]
    update_set = ", ".join([
        f"{col} = CASE "
        f"WHEN EXCLUDED._cdc_timestamp_micros > {table_name}._cdc_timestamp_micros "
        f"OR ({table_name}._cdc_timestamp_micros IS NULL) "
        f"THEN EXCLUDED.{col} "
        f"ELSE {table_name}.{col} END"
        for col in update_columns
    ])

    query = f"""
        INSERT INTO {table_name} ({column_list})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET
            {update_set}
        WHERE
            EXCLUDED._cdc_timestamp_micros > {table_name}._cdc_timestamp_micros
            OR (EXCLUDED._cdc_timestamp_micros = {table_name}._cdc_timestamp_micros
                AND EXCLUDED._last_event_id > {table_name}._last_event_id)
            OR {table_name}._cdc_timestamp_micros IS NULL
    """

    return query
