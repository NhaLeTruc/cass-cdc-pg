from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger(__name__)


class TypeMapper:
    """
    Service for mapping Cassandra data types to PostgreSQL data types.

    Handles type conversion including:
    - Primitive types (text, int, bigint, uuid, timestamp)
    - Collection types (list, set, map)
    - User-defined types (UDT)
    - TTL preservation via PostgreSQL retention policies
    """

    CASSANDRA_TO_POSTGRES_TYPE_MAP = {
        "text": "VARCHAR",
        "varchar": "VARCHAR",
        "ascii": "VARCHAR",
        "int": "INTEGER",
        "bigint": "BIGINT",
        "smallint": "SMALLINT",
        "tinyint": "SMALLINT",
        "varint": "NUMERIC",
        "float": "REAL",
        "double": "DOUBLE PRECISION",
        "decimal": "DECIMAL",
        "boolean": "BOOLEAN",
        "uuid": "UUID",
        "timeuuid": "UUID",
        "timestamp": "TIMESTAMPTZ",
        "date": "DATE",
        "time": "TIME",
        "blob": "BYTEA",
        "inet": "INET",
        "counter": "BIGINT",
    }

    def __init__(self) -> None:
        """Initialize TypeMapper service."""
        self._logger = logger.bind(component="type_mapper")

    def cassandra_to_postgres_type(
        self,
        cassandra_type: str,
        is_nullable: bool = True,
    ) -> str:
        """
        Map Cassandra type to PostgreSQL type.

        Args:
            cassandra_type: Cassandra type (e.g., 'text', 'list<int>', 'map<text,int>')
            is_nullable: Whether the column allows NULL values

        Returns:
            PostgreSQL type string (e.g., 'VARCHAR', 'INTEGER[]', 'JSONB')
        """
        cassandra_type = cassandra_type.strip().lower()

        if cassandra_type.startswith("list<"):
            element_type = self._extract_generic_type(cassandra_type, "list")
            pg_element_type = self.cassandra_to_postgres_type(element_type)
            return f"{pg_element_type}[]"

        elif cassandra_type.startswith("set<"):
            element_type = self._extract_generic_type(cassandra_type, "set")
            pg_element_type = self.cassandra_to_postgres_type(element_type)
            return f"{pg_element_type}[]"

        elif cassandra_type.startswith("map<"):
            return "JSONB"

        elif cassandra_type.startswith("frozen<"):
            inner_type = cassandra_type[7:-1]
            return self.cassandra_to_postgres_type(inner_type)

        else:
            pg_type = self.CASSANDRA_TO_POSTGRES_TYPE_MAP.get(cassandra_type, "TEXT")

            if not is_nullable and pg_type != "TEXT":
                pg_type += " NOT NULL"

            return pg_type

    def convert_value(
        self,
        value: Any,
        cassandra_type: str,
    ) -> Any:
        """
        Convert Cassandra value to PostgreSQL-compatible value.

        Args:
            value: Value from Cassandra
            cassandra_type: Cassandra type

        Returns:
            Converted value suitable for PostgreSQL
        """
        if value is None:
            return None

        cassandra_type = cassandra_type.strip().lower()

        if cassandra_type.startswith("list<") or cassandra_type.startswith("set<"):
            if isinstance(value, (list, set)):
                return list(value)
            return value

        elif cassandra_type.startswith("map<"):
            if isinstance(value, dict):
                return value
            return value

        elif cassandra_type in ["uuid", "timeuuid"]:
            return str(value)

        elif cassandra_type == "timestamp":
            if isinstance(value, datetime):
                return value
            elif isinstance(value, (int, float)):
                return datetime.fromtimestamp(value / 1000)
            return value

        elif cassandra_type == "date":
            if isinstance(value, datetime):
                return value.date()
            return value

        else:
            return value

    def calculate_ttl_expiry(
        self,
        ttl_seconds: Optional[int],
        event_timestamp_micros: int,
    ) -> Optional[datetime]:
        """
        Calculate TTL expiry timestamp for PostgreSQL.

        This implements TTL preservation by storing the expiry timestamp
        in the _ttl_expiry_timestamp column. A PostgreSQL trigger will
        automatically delete rows after this timestamp is reached.

        Args:
            ttl_seconds: Cassandra TTL in seconds (None if no TTL)
            event_timestamp_micros: Event timestamp in microseconds

        Returns:
            Expiry datetime or None if no TTL
        """
        if ttl_seconds is None or ttl_seconds == 0:
            return None

        event_datetime = datetime.fromtimestamp(event_timestamp_micros / 1_000_000)
        expiry_datetime = event_datetime + timedelta(seconds=ttl_seconds)

        self._logger.debug(
            "calculated_ttl_expiry",
            ttl_seconds=ttl_seconds,
            event_datetime=event_datetime.isoformat(),
            expiry_datetime=expiry_datetime.isoformat(),
        )

        return expiry_datetime

    def create_ttl_trigger_sql(self, table_name: str) -> str:
        """
        Generate SQL for creating TTL auto-delete trigger.

        This trigger automatically deletes rows where _ttl_expiry_timestamp
        has passed, implementing Cassandra TTL behavior in PostgreSQL.

        Args:
            table_name: Name of the PostgreSQL table

        Returns:
            SQL statement for creating the trigger
        """
        function_name = f"delete_expired_ttl_records_{table_name}"
        trigger_name = f"{table_name}_ttl_expiry_cleanup"

        sql = f"""
        CREATE OR REPLACE FUNCTION {function_name}()
        RETURNS TRIGGER AS $$
        BEGIN
            DELETE FROM {table_name}
            WHERE _ttl_expiry_timestamp IS NOT NULL
              AND _ttl_expiry_timestamp < NOW();
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};

        CREATE TRIGGER {trigger_name}
        AFTER INSERT OR UPDATE ON {table_name}
        FOR EACH STATEMENT
        EXECUTE FUNCTION {function_name}();
        """

        return sql

    def extract_column_definitions(
        self,
        schema: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Extract column definitions from Cassandra schema.

        Args:
            schema: Cassandra schema dictionary with 'columns' key

        Returns:
            Dictionary mapping column names to PostgreSQL types
        """
        column_defs = {}

        for column in schema.get("columns", []):
            column_name = column["name"]
            cassandra_type = column["type"]
            is_nullable = column.get("kind") != "partition_key"

            postgres_type = self.cassandra_to_postgres_type(cassandra_type, is_nullable)

            column_defs[column_name] = postgres_type

        self._logger.debug(
            "extracted_column_definitions",
            column_count=len(column_defs),
        )

        return column_defs

    def _extract_generic_type(self, full_type: str, container_type: str) -> str:
        """
        Extract element type from generic container type.

        Args:
            full_type: Full type string (e.g., 'list<int>')
            container_type: Container type name (e.g., 'list')

        Returns:
            Element type (e.g., 'int')
        """
        prefix_len = len(container_type) + 1
        return full_type[prefix_len:-1].strip()

    def prepare_row_data_for_postgres(
        self,
        row_data: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Prepare row data from Cassandra for PostgreSQL insertion.

        Converts all values according to their Cassandra types.

        Args:
            row_data: Row data from Cassandra
            schema: Cassandra schema with column type information

        Returns:
            Dictionary with converted values ready for PostgreSQL
        """
        column_types = {
            col["name"]: col["type"]
            for col in schema.get("columns", [])
        }

        converted_data = {}

        for column_name, value in row_data.items():
            cassandra_type = column_types.get(column_name, "text")
            converted_value = self.convert_value(value, cassandra_type)
            converted_data[column_name] = converted_value

        return converted_data
