from typing import List, Dict, Any, Optional
from cassandra.cluster import Cluster, Session, NoHostAvailable
from cassandra.query import dict_factory
from cassandra.auth import PlainTextAuthProvider
import structlog

from src.repositories.base import AbstractRepository
from src.config.settings import Settings
from src.monitoring.metrics import (
    cassandra_connection_errors_total,
    cassandra_query_duration_seconds,
    cassandra_active_connections,
)

logger = structlog.get_logger(__name__)


class CassandraRepository(AbstractRepository):
    """
    Repository for Cassandra database operations.

    Provides methods to connect, read schema, query tables, and perform health checks
    on Cassandra source database.
    """

    def __init__(self, settings: Settings):
        """
        Initialize Cassandra repository.

        Args:
            settings: Application settings containing Cassandra configuration
        """
        self.settings = settings
        self.cluster: Optional[Cluster] = None
        self.session: Optional[Session] = None
        self._logger = logger.bind(component="cassandra_repository")

    def connect(self) -> None:
        """
        Establish connection to Cassandra cluster.

        Raises:
            NoHostAvailable: If unable to connect to any Cassandra host
        """
        try:
            self._logger.info(
                "connecting_to_cassandra",
                hosts=self.settings.cassandra.hosts,
                port=self.settings.cassandra.port,
            )

            auth_provider = None
            if self.settings.cassandra.username and self.settings.cassandra.password:
                auth_provider = PlainTextAuthProvider(
                    username=self.settings.cassandra.username,
                    password=self.settings.cassandra.password,
                )

            self.cluster = Cluster(
                contact_points=self.settings.cassandra.hosts,
                port=self.settings.cassandra.port,
                auth_provider=auth_provider,
                protocol_version=4,
            )

            self.session = self.cluster.connect()
            self.session.row_factory = dict_factory

            cassandra_active_connections.inc()

            self._logger.info(
                "cassandra_connection_established",
                hosts=self.settings.cassandra.hosts,
            )

        except NoHostAvailable as e:
            cassandra_connection_errors_total.inc()
            self._logger.error(
                "cassandra_connection_failed",
                error=str(e),
                hosts=self.settings.cassandra.hosts,
            )
            raise

    def health_check(self) -> bool:
        """
        Check if Cassandra connection is healthy.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self.session:
            self._logger.warning("health_check_failed", reason="no_session")
            return False

        try:
            self.session.execute("SELECT now() FROM system.local")
            return True
        except Exception as e:
            self._logger.error("health_check_failed", error=str(e))
            return False

    def close(self) -> None:
        """Close Cassandra connection and cleanup resources."""
        if self.cluster:
            self.cluster.shutdown()
            cassandra_active_connections.dec()
            self._logger.info("cassandra_connection_closed")

    def read_schema(self, keyspace: str, table: str) -> Dict[str, Any]:
        """
        Read schema metadata for a Cassandra table.

        Args:
            keyspace: Cassandra keyspace name
            table: Table name

        Returns:
            Dictionary containing schema information with keys:
            - columns: List of column definitions
            - primary_key: List of primary key column names
            - clustering_key: List of clustering key column names
        """
        with cassandra_query_duration_seconds.labels(operation="read_schema").time():
            self._logger.info(
                "reading_schema",
                keyspace=keyspace,
                table=table,
            )

            query = """
                SELECT column_name, type, kind
                FROM system_schema.columns
                WHERE keyspace_name = %s AND table_name = %s
            """

            rows = self.session.execute(query, (keyspace, table))

            columns = []
            primary_key = []
            clustering_key = []

            for row in rows:
                column_info = {
                    "name": row["column_name"],
                    "type": row["type"],
                    "kind": row["kind"],
                }
                columns.append(column_info)

                if row["kind"] == "partition_key":
                    primary_key.append(row["column_name"])
                elif row["kind"] == "clustering":
                    clustering_key.append(row["column_name"])

            self._logger.info(
                "schema_read",
                keyspace=keyspace,
                table=table,
                column_count=len(columns),
                primary_key_count=len(primary_key),
            )

            return {
                "columns": columns,
                "primary_key": primary_key,
                "clustering_key": clustering_key,
            }

    def query_table(
        self,
        keyspace: str,
        table: str,
        limit: int = 100,
        where_clause: Optional[str] = None,
        parameters: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query a Cassandra table.

        Args:
            keyspace: Cassandra keyspace name
            table: Table name
            limit: Maximum number of rows to return
            where_clause: Optional WHERE clause (without 'WHERE' keyword)
            parameters: Optional list of parameters for prepared statement

        Returns:
            List of dictionaries representing rows
        """
        with cassandra_query_duration_seconds.labels(operation="query_table").time():
            self.session.set_keyspace(keyspace)

            query = f"SELECT * FROM {table}"

            if where_clause:
                query += f" WHERE {where_clause}"

            query += f" LIMIT {limit}"

            self._logger.debug(
                "executing_query",
                keyspace=keyspace,
                table=table,
                query=query,
            )

            if parameters:
                rows = self.session.execute(query, parameters)
            else:
                rows = self.session.execute(query)

            results = list(rows)

            self._logger.info(
                "query_executed",
                keyspace=keyspace,
                table=table,
                row_count=len(results),
            )

            return results

    def get_table_count(self, keyspace: str, table: str) -> int:
        """
        Get approximate row count for a table.

        Note: This uses COUNT(*) which can be slow for large tables.
        Consider using estimates for production use.

        Args:
            keyspace: Cassandra keyspace name
            table: Table name

        Returns:
            Number of rows in the table
        """
        with cassandra_query_duration_seconds.labels(operation="count").time():
            self.session.set_keyspace(keyspace)

            query = f"SELECT COUNT(*) FROM {table}"

            self._logger.debug("counting_rows", keyspace=keyspace, table=table)

            result = self.session.execute(query)
            count = result.one()["count"]

            self._logger.info(
                "row_count_retrieved",
                keyspace=keyspace,
                table=table,
                count=count,
            )

            return count

    def get_cdc_enabled_tables(self, keyspace: str) -> List[str]:
        """
        Get list of tables with CDC enabled in a keyspace.

        Args:
            keyspace: Cassandra keyspace name

        Returns:
            List of table names with CDC enabled
        """
        with cassandra_query_duration_seconds.labels(operation="get_cdc_tables").time():
            query = """
                SELECT table_name
                FROM system_schema.tables
                WHERE keyspace_name = %s
            """

            rows = self.session.execute(query, (keyspace,))

            cdc_tables = []

            for row in rows:
                table_name = row["table_name"]

                table_query = """
                    SELECT extensions
                    FROM system_schema.tables
                    WHERE keyspace_name = %s AND table_name = %s
                """

                table_info = self.session.execute(table_query, (keyspace, table_name))
                table_data = table_info.one()

                if table_data and "extensions" in table_data:
                    extensions = table_data["extensions"]
                    if extensions and "cdc" in extensions:
                        if extensions["cdc"].get("enabled", False):
                            cdc_tables.append(table_name)

            self._logger.info(
                "cdc_tables_retrieved",
                keyspace=keyspace,
                cdc_table_count=len(cdc_tables),
                tables=cdc_tables,
            )

            return cdc_tables
