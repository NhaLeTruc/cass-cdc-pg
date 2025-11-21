from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor
import structlog
from tenacity import (
    retry,
    stop_after_delay,
    wait_exponential,
    retry_if_exception_type,
)

from src.repositories.base import AbstractRepository
from src.config.settings import Settings
from src.monitoring.metrics import (
    postgresql_connection_errors_total,
    postgresql_query_duration_seconds,
    postgresql_active_connections,
)
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logger = structlog.get_logger(__name__)


class PostgreSQLRepository(AbstractRepository):
    """
    Repository for PostgreSQL database operations.

    Provides methods to connect, create tables, upsert, delete, query,
    and perform health checks on PostgreSQL target database.
    Uses connection pooling for efficient resource management.
    """

    def __init__(self, settings: Settings):
        """
        Initialize PostgreSQL repository.

        Args:
            settings: Application settings containing PostgreSQL configuration
        """
        self.settings = settings
        self.connection_pool: Optional[pool.ThreadedConnectionPool] = None
        self._logger = logger.bind(component="postgresql_repository")
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            timeout_seconds=60,
            name="postgresql_connection",
        )

    def connect(self) -> None:
        """
        Establish connection pool to PostgreSQL database.

        Creates a thread pool with min/max connections for efficient resource usage.

        Raises:
            psycopg2.OperationalError: If unable to connect to PostgreSQL
        """
        try:
            self._logger.info(
                "creating_postgresql_connection_pool",
                host=self.settings.postgresql.host,
                port=self.settings.postgresql.port,
                database=self.settings.postgresql.database,
            )

            self.connection_pool = pool.ThreadedConnectionPool(
                minconn=self.settings.postgresql.min_pool_size,
                maxconn=self.settings.postgresql.max_pool_size,
                host=self.settings.postgresql.host,
                port=self.settings.postgresql.port,
                database=self.settings.postgresql.database,
                user=self.settings.postgresql.user,
                password=self.settings.postgresql.password,
                connect_timeout=self.settings.postgresql.connect_timeout,
            )

            postgresql_active_connections.set(self.settings.postgresql.min_pool_size)

            self._logger.info(
                "postgresql_connection_pool_created",
                min_connections=self.settings.postgresql.min_pool_size,
                max_connections=self.settings.postgresql.max_pool_size,
            )

        except psycopg2.OperationalError as e:
            postgresql_connection_errors_total.inc()
            self._logger.error(
                "postgresql_connection_failed",
                error=str(e),
                host=self.settings.postgresql.host,
            )
            raise

    def health_check(self) -> bool:
        """
        Check if PostgreSQL connection is healthy.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self.connection_pool:
            self._logger.warning("health_check_failed", reason="no_connection_pool")
            return False

        conn = None
        try:
            conn = self.connection_pool.getconn()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            return result[0] == 1
        except Exception as e:
            self._logger.error("health_check_failed", error=str(e))
            return False
        finally:
            if conn:
                self.connection_pool.putconn(conn)

    def close(self) -> None:
        """Close PostgreSQL connection pool and cleanup resources."""
        if self.connection_pool:
            self.connection_pool.closeall()
            postgresql_active_connections.set(0)
            self._logger.info("postgresql_connection_pool_closed")

    def create_table(
        self,
        table_name: str,
        columns: List[Dict[str, str]],
        primary_key: List[str],
    ) -> None:
        """
        Create a PostgreSQL table with CDC metadata columns.

        Args:
            table_name: Name of the table to create
            columns: List of column definitions with 'name' and 'type'
            primary_key: List of column names forming the primary key
        """
        with postgresql_query_duration_seconds.labels(operation="create_table").time():
            conn = self.connection_pool.getconn()
            try:
                cursor = conn.cursor()

                column_defs = [f"{col['name']} {col['type']}" for col in columns]

                column_defs.extend([
                    "_cdc_deleted BOOLEAN DEFAULT FALSE",
                    "_cdc_timestamp_micros BIGINT",
                    "_ttl_expiry_timestamp TIMESTAMPTZ",
                ])

                pk_clause = f"PRIMARY KEY ({', '.join(primary_key)})"
                column_defs.append(pk_clause)

                create_query = f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        {', '.join(column_defs)}
                    )
                """

                self._logger.info(
                    "creating_table",
                    table=table_name,
                    column_count=len(columns),
                )

                cursor.execute(create_query)
                conn.commit()

                self._logger.info("table_created", table=table_name)

                cursor.close()
            finally:
                self.connection_pool.putconn(conn)

    @retry(
        retry=retry_if_exception_type((psycopg2.OperationalError, psycopg2.InterfaceError)),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_delay(300),
        reraise=True,
    )
    def upsert(
        self,
        table_name: str,
        primary_key: List[str],
        data: Dict[str, Any],
    ) -> None:
        """
        Insert or update a record using PostgreSQL ON CONFLICT.

        Retries with exponential backoff on transient errors:
        - wait_exponential: 1s, 2s, 4s, 8s, 16s, 32s, 60s
        - stop_after_delay: 300s (5 minutes)

        Args:
            table_name: Name of the target table
            primary_key: List of primary key column names
            data: Dictionary of column names to values

        Raises:
            psycopg2.OperationalError: After retries exhausted
            CircuitBreakerOpenError: If circuit breaker is open
        """
        def _execute_upsert():
            with postgresql_query_duration_seconds.labels(operation="upsert").time():
                conn = self.connection_pool.getconn()
                try:
                    cursor = conn.cursor()

                    columns = list(data.keys())
                    values = list(data.values())
                    placeholders = ["%s"] * len(columns)

                    update_columns = [col for col in columns if col not in primary_key]
                    update_set = [f"{col} = EXCLUDED.{col}" for col in update_columns]

                    query = f"""
                        INSERT INTO {table_name} ({', '.join(columns)})
                        VALUES ({', '.join(placeholders)})
                        ON CONFLICT ({', '.join(primary_key)})
                        DO UPDATE SET {', '.join(update_set)}
                    """

                    self._logger.debug(
                        "executing_upsert",
                        table=table_name,
                        primary_key=primary_key,
                    )

                    cursor.execute(query, values)
                    conn.commit()

                    cursor.close()
                finally:
                    self.connection_pool.putconn(conn)

        try:
            self.circuit_breaker.call(_execute_upsert)
        except CircuitBreakerOpenError:
            self._logger.warning(
                "upsert_blocked_by_circuit_breaker",
                table=table_name,
            )
            raise

    def delete(self, table_name: str, where_clause: str, parameters: List[Any]) -> None:
        """
        Delete records from a table (hard delete).

        Args:
            table_name: Name of the target table
            where_clause: WHERE clause (without 'WHERE' keyword)
            parameters: List of parameters for the WHERE clause
        """
        with postgresql_query_duration_seconds.labels(operation="delete").time():
            conn = self.connection_pool.getconn()
            try:
                cursor = conn.cursor()

                query = f"DELETE FROM {table_name} WHERE {where_clause}"

                self._logger.debug(
                    "executing_delete",
                    table=table_name,
                    where=where_clause,
                )

                cursor.execute(query, parameters)
                rows_deleted = cursor.rowcount
                conn.commit()

                self._logger.info(
                    "delete_executed",
                    table=table_name,
                    rows_deleted=rows_deleted,
                )

                cursor.close()
            finally:
                self.connection_pool.putconn(conn)

    def soft_delete(self, table_name: str, primary_key_values: Dict[str, Any]) -> None:
        """
        Mark a record as deleted (soft delete) by setting _cdc_deleted = TRUE.

        Args:
            table_name: Name of the target table
            primary_key_values: Dictionary of primary key column names to values
        """
        with postgresql_query_duration_seconds.labels(operation="soft_delete").time():
            conn = self.connection_pool.getconn()
            try:
                cursor = conn.cursor()

                where_parts = [f"{key} = %s" for key in primary_key_values.keys()]
                where_clause = " AND ".join(where_parts)
                values = list(primary_key_values.values())

                query = f"""
                    UPDATE {table_name}
                    SET _cdc_deleted = TRUE
                    WHERE {where_clause}
                """

                self._logger.debug(
                    "executing_soft_delete",
                    table=table_name,
                    primary_key=primary_key_values,
                )

                cursor.execute(query, values)
                conn.commit()

                cursor.close()
            finally:
                self.connection_pool.putconn(conn)

    def query(
        self,
        table_name: str,
        where_clause: Optional[str] = None,
        parameters: Optional[List[Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query a PostgreSQL table.

        Args:
            table_name: Name of the table to query
            where_clause: Optional WHERE clause (without 'WHERE' keyword)
            parameters: Optional list of parameters for prepared statement
            limit: Maximum number of rows to return

        Returns:
            List of dictionaries representing rows
        """
        with postgresql_query_duration_seconds.labels(operation="query").time():
            conn = self.connection_pool.getconn()
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)

                query = f"SELECT * FROM {table_name}"

                if where_clause:
                    query += f" WHERE {where_clause}"

                query += f" LIMIT {limit}"

                self._logger.debug(
                    "executing_query",
                    table=table_name,
                    query=query,
                )

                if parameters:
                    cursor.execute(query, parameters)
                else:
                    cursor.execute(query)

                results = cursor.fetchall()

                self._logger.info(
                    "query_executed",
                    table=table_name,
                    row_count=len(results),
                )

                cursor.close()

                return [dict(row) for row in results]
            finally:
                self.connection_pool.putconn(conn)

    def get_table_count(self, table_name: str) -> int:
        """
        Get row count for a table.

        Args:
            table_name: Name of the table

        Returns:
            Number of rows in the table
        """
        with postgresql_query_duration_seconds.labels(operation="count").time():
            conn = self.connection_pool.getconn()
            try:
                cursor = conn.cursor()

                query = f"SELECT COUNT(*) FROM {table_name}"

                self._logger.debug("counting_rows", table=table_name)

                cursor.execute(query)
                count = cursor.fetchone()[0]

                self._logger.info("row_count_retrieved", table=table_name, count=count)

                cursor.close()

                return count
            finally:
                self.connection_pool.putconn(conn)

    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database.

        Args:
            table_name: Name of the table to check

        Returns:
            True if table exists, False otherwise
        """
        conn = self.connection_pool.getconn()
        try:
            cursor = conn.cursor()

            query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = %s
                )
            """

            cursor.execute(query, (table_name,))
            exists = cursor.fetchone()[0]

            cursor.close()

            return exists
        finally:
            self.connection_pool.putconn(conn)
