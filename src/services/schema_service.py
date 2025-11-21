from typing import Dict, Any, List, Optional
import json
import requests
import structlog

from src.models.schema_metadata import (
    SchemaMetadata,
    ColumnMetadata,
    SchemaChangeType,
    CompatibilityMode,
)
from src.config.settings import Settings

logger = structlog.get_logger(__name__)


class SchemaService:
    """
    Service for managing schema metadata and evolution.

    Handles schema registration, version tracking, change detection,
    and compatibility validation with Schema Registry.
    """

    def __init__(self, settings: Settings):
        """
        Initialize SchemaService.

        Args:
            settings: Application settings with Schema Registry configuration
        """
        self.settings = settings
        self.schema_registry_url = f"http://{self.settings.kafka.schema_registry_host}:{self.settings.kafka.schema_registry_port}"
        self._logger = logger.bind(component="schema_service")

    def register_schema(
        self,
        subject: str,
        schema: Dict[str, Any],
        compatibility: Optional[CompatibilityMode] = None,
    ) -> int:
        """
        Register Avro schema with Schema Registry.

        Args:
            subject: Schema subject name (e.g., 'cdc-events-users-value')
            schema: Avro schema as dictionary
            compatibility: Optional compatibility mode override

        Returns:
            Schema ID from Schema Registry

        Raises:
            requests.HTTPError: If registration fails
        """
        try:
            self._logger.info(
                "registering_schema",
                subject=subject,
                compatibility=compatibility.value if compatibility else None,
            )

            if compatibility:
                self._set_compatibility(subject, compatibility)

            url = f"{self.schema_registry_url}/subjects/{subject}/versions"

            payload = {"schema": json.dumps(schema)}

            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
            )

            response.raise_for_status()

            schema_id = response.json()["id"]

            self._logger.info(
                "schema_registered",
                subject=subject,
                schema_id=schema_id,
            )

            return schema_id

        except requests.HTTPError as e:
            self._logger.error(
                "schema_registration_failed",
                subject=subject,
                error=str(e),
                response=e.response.text if e.response else None,
            )
            raise

    def get_schema_by_version(
        self,
        subject: str,
        version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve schema from Schema Registry by version.

        Args:
            subject: Schema subject name
            version: Schema version (None for latest)

        Returns:
            Dictionary with 'id', 'version', and 'schema' keys

        Raises:
            requests.HTTPError: If schema not found
        """
        try:
            version_str = str(version) if version else "latest"

            self._logger.debug(
                "retrieving_schema",
                subject=subject,
                version=version_str,
            )

            url = f"{self.schema_registry_url}/subjects/{subject}/versions/{version_str}"

            response = requests.get(url)
            response.raise_for_status()

            data = response.json()

            schema = {
                "id": data["id"],
                "version": data["version"],
                "schema": json.loads(data["schema"]),
            }

            self._logger.info(
                "schema_retrieved",
                subject=subject,
                version=schema["version"],
                schema_id=schema["id"],
            )

            return schema

        except requests.HTTPError as e:
            self._logger.error(
                "schema_retrieval_failed",
                subject=subject,
                version=version,
                error=str(e),
            )
            raise

    def detect_schema_changes(
        self,
        old_schema: SchemaMetadata,
        new_columns: List[ColumnMetadata],
    ) -> List[Dict[str, Any]]:
        """
        Detect schema changes between old and new column definitions.

        Args:
            old_schema: Existing schema metadata
            new_columns: New column definitions

        Returns:
            List of schema changes with 'type', 'column', 'old_type', 'new_type'
        """
        changes = []

        old_columns_map = {col.name: col for col in old_schema.columns}
        new_columns_map = {col.name: col for col in new_columns}

        for column_name, new_col in new_columns_map.items():
            if column_name not in old_columns_map:
                changes.append({
                    "type": SchemaChangeType.ADD_COLUMN,
                    "column": column_name,
                    "new_type": new_col.postgres_type,
                })

        for column_name, old_col in old_columns_map.items():
            if column_name not in new_columns_map:
                changes.append({
                    "type": SchemaChangeType.DROP_COLUMN,
                    "column": column_name,
                    "old_type": old_col.postgres_type,
                })
            else:
                new_col = new_columns_map[column_name]
                if old_col.cassandra_type != new_col.cassandra_type:
                    changes.append({
                        "type": SchemaChangeType.MODIFY_COLUMN,
                        "column": column_name,
                        "old_type": old_col.cassandra_type,
                        "new_type": new_col.cassandra_type,
                    })

        self._logger.info(
            "schema_changes_detected",
            table=old_schema.source_table,
            change_count=len(changes),
            changes=changes,
        )

        return changes

    def validate_compatibility(
        self,
        subject: str,
        new_schema: Dict[str, Any],
    ) -> bool:
        """
        Validate schema compatibility against Schema Registry.

        Args:
            subject: Schema subject name
            new_schema: New Avro schema to validate

        Returns:
            True if compatible, False otherwise
        """
        try:
            self._logger.debug(
                "validating_compatibility",
                subject=subject,
            )

            url = f"{self.schema_registry_url}/compatibility/subjects/{subject}/versions/latest"

            payload = {"schema": json.dumps(new_schema)}

            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
            )

            response.raise_for_status()

            is_compatible = response.json().get("is_compatible", False)

            self._logger.info(
                "compatibility_validated",
                subject=subject,
                is_compatible=is_compatible,
            )

            return is_compatible

        except requests.HTTPError as e:
            self._logger.error(
                "compatibility_validation_failed",
                subject=subject,
                error=str(e),
            )
            return False

    def check_compatibility(
        self,
        old_schema: SchemaMetadata,
        new_schema: SchemaMetadata,
    ) -> bool:
        """
        Check if schema change is compatible according to compatibility mode.

        Args:
            old_schema: Existing schema
            new_schema: New schema

        Returns:
            True if compatible, False otherwise
        """
        compatibility_mode = old_schema.compatibility_mode

        if compatibility_mode == CompatibilityMode.NONE:
            return True

        changes = self.detect_schema_changes(old_schema, new_schema.columns)

        if not changes:
            return True

        if compatibility_mode == CompatibilityMode.BACKWARD:
            return self._check_backward_compatibility(changes, new_schema)

        elif compatibility_mode == CompatibilityMode.FORWARD:
            return self._check_forward_compatibility(changes, old_schema)

        elif compatibility_mode == CompatibilityMode.FULL:
            return (
                self._check_backward_compatibility(changes, new_schema)
                and self._check_forward_compatibility(changes, old_schema)
            )

        return False

    def _check_backward_compatibility(
        self,
        changes: List[Dict[str, Any]],
        new_schema: SchemaMetadata,
    ) -> bool:
        """
        Check backward compatibility.

        Backward compatible means old consumers can read new data.
        - Can add columns with defaults
        - Can delete columns
        - Cannot change column types
        """
        for change in changes:
            if change["type"] == SchemaChangeType.ADD_COLUMN:
                column = new_schema.get_column(change["column"])
                if column and not column.is_nullable and column.default_value is None:
                    self._logger.warning(
                        "backward_incompatible_add_column",
                        column=change["column"],
                        reason="non_nullable_without_default",
                    )
                    return False

            elif change["type"] == SchemaChangeType.MODIFY_COLUMN:
                self._logger.warning(
                    "backward_incompatible_modify_column",
                    column=change["column"],
                    old_type=change["old_type"],
                    new_type=change["new_type"],
                )
                return False

        return True

    def _check_forward_compatibility(
        self,
        changes: List[Dict[str, Any]],
        old_schema: SchemaMetadata,
    ) -> bool:
        """
        Check forward compatibility.

        Forward compatible means new consumers can read old data.
        - Can delete columns
        - Can add columns with defaults
        - Cannot change column types
        """
        for change in changes:
            if change["type"] == SchemaChangeType.ADD_COLUMN:
                pass

            elif change["type"] == SchemaChangeType.MODIFY_COLUMN:
                self._logger.warning(
                    "forward_incompatible_modify_column",
                    column=change["column"],
                    old_type=change["old_type"],
                    new_type=change["new_type"],
                )
                return False

        return True

    def _set_compatibility(
        self,
        subject: str,
        compatibility: CompatibilityMode,
    ) -> None:
        """
        Set compatibility mode for a subject in Schema Registry.

        Args:
            subject: Schema subject name
            compatibility: Compatibility mode to set
        """
        try:
            url = f"{self.schema_registry_url}/config/{subject}"

            payload = {"compatibility": compatibility.value}

            response = requests.put(
                url,
                json=payload,
                headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
            )

            response.raise_for_status()

            self._logger.info(
                "compatibility_mode_set",
                subject=subject,
                compatibility=compatibility.value,
            )

        except requests.HTTPError as e:
            self._logger.error(
                "set_compatibility_failed",
                subject=subject,
                error=str(e),
            )

    def create_avro_schema_for_table(
        self,
        table_name: str,
        columns: List[ColumnMetadata],
    ) -> Dict[str, Any]:
        """
        Create Avro schema from column metadata.

        Args:
            table_name: Name of the table
            columns: List of column metadata

        Returns:
            Avro schema as dictionary
        """
        fields = []

        for column in columns:
            field_type = self._cassandra_to_avro_type(column.cassandra_type)

            if column.is_nullable:
                field_type = ["null", field_type]

            field = {
                "name": column.name,
                "type": field_type,
            }

            if column.default_value is not None:
                field["default"] = column.default_value
            elif column.is_nullable:
                field["default"] = None

            fields.append(field)

        avro_schema = {
            "type": "record",
            "name": f"{table_name.capitalize()}Value",
            "namespace": "com.cdc.events",
            "fields": fields,
        }

        self._logger.debug(
            "avro_schema_created",
            table=table_name,
            field_count=len(fields),
        )

        return avro_schema

    def _cassandra_to_avro_type(self, cassandra_type: str) -> Any:
        """
        Map Cassandra type to Avro type.

        Args:
            cassandra_type: Cassandra type

        Returns:
            Avro type (string or dict)
        """
        cassandra_type = cassandra_type.strip().lower()

        avro_type_map = {
            "text": "string",
            "varchar": "string",
            "ascii": "string",
            "int": "int",
            "bigint": "long",
            "float": "float",
            "double": "double",
            "boolean": "boolean",
            "uuid": "string",
            "timeuuid": "string",
            "timestamp": "long",
            "blob": "bytes",
        }

        if cassandra_type in avro_type_map:
            return avro_type_map[cassandra_type]
        elif cassandra_type.startswith("list<") or cassandra_type.startswith("set<"):
            return {"type": "array", "items": "string"}
        elif cassandra_type.startswith("map<"):
            return {"type": "map", "values": "string"}
        else:
            return "string"
