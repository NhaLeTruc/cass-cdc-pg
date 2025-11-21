"""Service for managing Dead Letter Queue operations."""

from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import psycopg2
from kafka import KafkaConsumer, KafkaProducer
import structlog

from src.models.dlq_record import DLQRecord, ErrorType, ResolutionStatus
from src.config.settings import Settings

logger = structlog.get_logger(__name__)


class DLQService:
    """
    Service for managing DLQ records and replay operations.

    Handles:
    - Querying DLQ records from PostgreSQL
    - Consuming events from dlq-events Kafka topic
    - Replaying failed events
    - Updating DLQ record status
    """

    def __init__(self, settings: Settings):
        """
        Initialize DLQService.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self._logger = logger.bind(component="dlq_service")

    def query_dlq_records(
        self,
        error_type: Optional[ErrorType] = None,
        resolution_status: Optional[ResolutionStatus] = None,
        table: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DLQRecord]:
        """
        Query DLQ records from PostgreSQL with filters.

        Args:
            error_type: Filter by error type
            resolution_status: Filter by resolution status
            table: Filter by source table
            start_date: Filter by failed_at >= start_date
            end_date: Filter by failed_at <= end_date
            limit: Maximum number of records to return
            offset: Number of records to skip

        Returns:
            List of DLQRecord instances
        """
        self._logger.info(
            "querying_dlq_records",
            error_type=error_type.value if error_type else None,
            resolution_status=resolution_status.value if resolution_status else None,
            table=table,
            limit=limit,
            offset=offset,
        )

        conn = psycopg2.connect(
            host=self.settings.postgres.host,
            port=self.settings.postgres.port,
            dbname=self.settings.postgres.database,
            user=self.settings.postgres.user,
            password=self.settings.postgres.password,
        )

        try:
            cursor = conn.cursor()

            # Build dynamic query
            query = """
                SELECT id, source_table, event_data, error_type, error_message,
                       error_stack_trace, retry_count, first_failed_at, last_retry_at,
                       failed_at, resolution_status, resolution_notes, resolved_at
                FROM _cdc_dlq_records
                WHERE 1=1
            """
            params = []

            if error_type:
                query += " AND error_type = %s"
                params.append(error_type.value)

            if resolution_status:
                query += " AND resolution_status = %s"
                params.append(resolution_status.value)

            if table:
                query += " AND source_table = %s"
                params.append(table)

            if start_date:
                query += " AND failed_at >= %s"
                params.append(start_date)

            if end_date:
                query += " AND failed_at <= %s"
                params.append(end_date)

            query += " ORDER BY failed_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cursor.execute(query, params)

            rows = cursor.fetchall()

            records = []
            for row in rows:
                (
                    dlq_id,
                    source_table,
                    event_data,
                    error_type_str,
                    error_message,
                    error_stack_trace,
                    retry_count,
                    first_failed_at,
                    last_retry_at,
                    failed_at,
                    resolution_status_str,
                    resolution_notes,
                    resolved_at,
                ) = row

                record = DLQRecord(
                    dlq_id=dlq_id,
                    source_table=source_table,
                    original_event=event_data if isinstance(event_data, dict) else json.loads(event_data),
                    error_type=ErrorType(error_type_str),
                    error_message=error_message,
                    error_stack_trace=error_stack_trace,
                    retry_count=retry_count or 0,
                    first_failed_at=first_failed_at,
                    last_retry_at=last_retry_at,
                    dlq_timestamp=failed_at,
                    source_component="kafka-connect",
                    resolution_status=ResolutionStatus(resolution_status_str) if resolution_status_str else ResolutionStatus.PENDING,
                    resolution_notes=resolution_notes,
                    resolved_at=resolved_at,
                )

                records.append(record)

            cursor.close()

            self._logger.info("dlq_records_queried", count=len(records))

            return records

        finally:
            conn.close()

    def replay_events(
        self,
        dlq_ids: List[int],
        resolution_notes: Optional[str] = None,
        retry_strategy: str = "immediate",
    ) -> Dict[str, Any]:
        """
        Replay failed events from DLQ.

        Args:
            dlq_ids: List of DLQ record IDs to replay
            resolution_notes: Notes about the resolution
            retry_strategy: Strategy for replay (immediate, batch, scheduled)

        Returns:
            Dictionary with replay results
        """
        self._logger.info(
            "replaying_dlq_events",
            dlq_ids=dlq_ids,
            retry_strategy=retry_strategy,
        )

        conn = psycopg2.connect(
            host=self.settings.postgres.host,
            port=self.settings.postgres.port,
            dbname=self.settings.postgres.database,
            user=self.settings.postgres.user,
            password=self.settings.postgres.password,
        )

        replayed_count = 0
        failed_count = 0

        try:
            cursor = conn.cursor()

            # Fetch DLQ records
            cursor.execute(
                """
                SELECT id, source_table, event_data, error_type
                FROM _cdc_dlq_records
                WHERE id = ANY(%s)
                """,
                (dlq_ids,),
            )

            records = cursor.fetchall()

            if not records:
                self._logger.warning("no_dlq_records_found", dlq_ids=dlq_ids)
                return {
                    "replayed_count": 0,
                    "failed_count": 0,
                    "message": "No DLQ records found with provided IDs",
                }

            # Create Kafka producer for replay
            producer = KafkaProducer(
                bootstrap_servers=[f"{self.settings.kafka.bootstrap_servers}"],
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )

            for record in records:
                dlq_id, source_table, event_data, error_type = record

                try:
                    # Determine target topic based on source table
                    topic = f"cdc-events-{source_table}"

                    # Parse event data
                    if isinstance(event_data, str):
                        event = json.loads(event_data)
                    else:
                        event = event_data

                    # Send event back to Kafka topic for reprocessing
                    future = producer.send(topic, value=event)
                    future.get(timeout=10)  # Wait for send confirmation

                    # Update DLQ record status to MANUAL_RESOLVED
                    cursor.execute(
                        """
                        UPDATE _cdc_dlq_records
                        SET resolution_status = %s,
                            resolution_notes = %s,
                            resolved_at = NOW()
                        WHERE id = %s
                        """,
                        (ResolutionStatus.MANUAL_RESOLVED.value, resolution_notes, dlq_id),
                    )

                    replayed_count += 1

                    self._logger.info(
                        "dlq_event_replayed",
                        dlq_id=dlq_id,
                        table=source_table,
                        topic=topic,
                    )

                except Exception as e:
                    failed_count += 1
                    self._logger.error(
                        "dlq_replay_failed",
                        dlq_id=dlq_id,
                        error=str(e),
                        exc_info=True,
                    )

            conn.commit()
            cursor.close()
            producer.close()

            self._logger.info(
                "dlq_replay_completed",
                replayed_count=replayed_count,
                failed_count=failed_count,
            )

            return {
                "replayed_count": replayed_count,
                "failed_count": failed_count,
                "message": f"Successfully replayed {replayed_count} events, {failed_count} failed",
            }

        except Exception as e:
            conn.rollback()
            self._logger.error(
                "dlq_replay_error",
                error=str(e),
                exc_info=True,
            )
            raise

        finally:
            conn.close()

    def consume_dlq_topic(
        self,
        max_messages: int = 100,
        timeout_ms: int = 10000,
    ) -> List[DLQRecord]:
        """
        Consume messages from dlq-events Kafka topic.

        Args:
            max_messages: Maximum number of messages to consume
            timeout_ms: Consumer timeout in milliseconds

        Returns:
            List of DLQRecord instances
        """
        self._logger.info("consuming_dlq_topic", max_messages=max_messages)

        consumer = KafkaConsumer(
            "dlq-events",
            bootstrap_servers=[self.settings.kafka.bootstrap_servers],
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")) if m else None,
            consumer_timeout_ms=timeout_ms,
        )

        records = []
        message_count = 0

        try:
            for message in consumer:
                if message_count >= max_messages:
                    break

                event = message.value

                if not event:
                    continue

                try:
                    # Parse DLQ event
                    dlq_record = DLQRecord(
                        dlq_id=event.get("dlq_id") or event.get("id"),
                        source_table=event.get("source_table", "unknown"),
                        original_event=event.get("original_event", {}),
                        error_type=ErrorType(event.get("error_type", "UNKNOWN")),
                        error_message=event.get("error_message", ""),
                        error_stack_trace=event.get("error_stack_trace"),
                        retry_count=event.get("retry_count", 0),
                        first_failed_at=datetime.fromisoformat(event["first_failed_at"]) if event.get("first_failed_at") else None,
                        last_retry_at=datetime.fromisoformat(event["last_retry_at"]) if event.get("last_retry_at") else None,
                        dlq_timestamp=datetime.fromisoformat(event["dlq_timestamp"]) if event.get("dlq_timestamp") else datetime.utcnow(),
                        source_component=event.get("source_component", "kafka-connect"),
                    )

                    records.append(dlq_record)
                    message_count += 1

                except Exception as e:
                    self._logger.error(
                        "failed_to_parse_dlq_event",
                        error=str(e),
                        event=event,
                    )

            self._logger.info("dlq_topic_consumed", record_count=len(records))

            return records

        finally:
            consumer.close()

    def get_dlq_stats(self) -> Dict[str, Any]:
        """
        Get statistics about DLQ records.

        Returns:
            Dictionary with DLQ statistics
        """
        self._logger.info("getting_dlq_stats")

        conn = psycopg2.connect(
            host=self.settings.postgres.host,
            port=self.settings.postgres.port,
            dbname=self.settings.postgres.database,
            user=self.settings.postgres.user,
            password=self.settings.postgres.password,
        )

        try:
            cursor = conn.cursor()

            # Total DLQ records
            cursor.execute("SELECT COUNT(*) FROM _cdc_dlq_records")
            total_records = cursor.fetchone()[0]

            # Count by error type
            cursor.execute(
                """
                SELECT error_type, COUNT(*)
                FROM _cdc_dlq_records
                GROUP BY error_type
                """
            )
            error_type_counts = dict(cursor.fetchall())

            # Count by resolution status
            cursor.execute(
                """
                SELECT resolution_status, COUNT(*)
                FROM _cdc_dlq_records
                GROUP BY resolution_status
                """
            )
            resolution_status_counts = dict(cursor.fetchall())

            # Count by table
            cursor.execute(
                """
                SELECT source_table, COUNT(*)
                FROM _cdc_dlq_records
                GROUP BY source_table
                """
            )
            table_counts = dict(cursor.fetchall())

            cursor.close()

            stats = {
                "total_records": total_records,
                "by_error_type": error_type_counts,
                "by_resolution_status": resolution_status_counts,
                "by_table": table_counts,
            }

            self._logger.info("dlq_stats_retrieved", stats=stats)

            return stats

        finally:
            conn.close()
