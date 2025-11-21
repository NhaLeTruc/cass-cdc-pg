import pytest
from typing import Any, Dict
import json


class TestChangeEventSchema:
    """
    Contract test for Change Event Avro schema validation.

    Validates schema compatibility, field types, and required fields
    according to the CDC event contract defined in contracts/kafka-topics.md.
    """

    @pytest.fixture
    def expected_key_schema(self) -> Dict[str, Any]:
        """Expected Avro schema for cdc-events-{table}-key."""
        return {
            "type": "record",
            "name": "ChangeEventKey",
            "namespace": "com.cdc.events",
            "fields": [
                {"name": "event_id", "type": "string"},
                {
                    "name": "partition_key_hash",
                    "type": ["null", "string"],
                    "default": None,
                },
            ],
        }

    @pytest.fixture
    def expected_value_schema(self) -> Dict[str, Any]:
        """Expected Avro schema for cdc-events-{table}-value."""
        return {
            "type": "record",
            "name": "ChangeEventValue",
            "namespace": "com.cdc.events",
            "fields": [
                {"name": "event_id", "type": "string"},
                {"name": "source_table", "type": "string"},
                {
                    "name": "operation_type",
                    "type": {
                        "type": "enum",
                        "name": "OperationType",
                        "symbols": ["CREATE", "UPDATE", "DELETE", "TRUNCATE"],
                    },
                },
                {"name": "timestamp_micros", "type": "long"},
                {
                    "name": "before",
                    "type": [
                        "null",
                        {"type": "map", "values": ["null", "string", "long", "double"]},
                    ],
                    "default": None,
                },
                {
                    "name": "after",
                    "type": [
                        "null",
                        {"type": "map", "values": ["null", "string", "long", "double"]},
                    ],
                    "default": None,
                },
                {"name": "schema_version", "type": "int"},
                {
                    "name": "ttl_seconds",
                    "type": ["null", "int"],
                    "default": None,
                },
                {"name": "is_tombstone", "type": "boolean", "default": False},
            ],
        }

    def test_key_schema_has_required_fields(self, expected_key_schema: Dict[str, Any]) -> None:
        """Validate that key schema contains required fields."""
        field_names = [field["name"] for field in expected_key_schema["fields"]]

        assert "event_id" in field_names, "event_id is required in key schema"
        assert "partition_key_hash" in field_names, "partition_key_hash is required in key schema"

    def test_key_schema_event_id_is_string(self, expected_key_schema: Dict[str, Any]) -> None:
        """Validate that event_id field is of type string."""
        event_id_field = next(
            f for f in expected_key_schema["fields"] if f["name"] == "event_id"
        )
        assert event_id_field["type"] == "string", "event_id must be string type"

    def test_value_schema_has_required_fields(self, expected_value_schema: Dict[str, Any]) -> None:
        """Validate that value schema contains all required fields."""
        field_names = [field["name"] for field in expected_value_schema["fields"]]

        required_fields = [
            "event_id",
            "source_table",
            "operation_type",
            "timestamp_micros",
            "before",
            "after",
            "schema_version",
            "ttl_seconds",
            "is_tombstone",
        ]

        for field in required_fields:
            assert field in field_names, f"{field} is required in value schema"

    def test_value_schema_operation_type_is_enum(
        self, expected_value_schema: Dict[str, Any]
    ) -> None:
        """Validate that operation_type is an enum with correct symbols."""
        operation_field = next(
            f for f in expected_value_schema["fields"] if f["name"] == "operation_type"
        )

        assert isinstance(operation_field["type"], dict), "operation_type must be enum"
        assert operation_field["type"]["type"] == "enum", "operation_type must be enum"

        expected_symbols = ["CREATE", "UPDATE", "DELETE", "TRUNCATE"]
        assert (
            operation_field["type"]["symbols"] == expected_symbols
        ), f"operation_type enum must have symbols: {expected_symbols}"

    def test_value_schema_timestamp_is_long(self, expected_value_schema: Dict[str, Any]) -> None:
        """Validate that timestamp_micros is long type for microsecond precision."""
        timestamp_field = next(
            f for f in expected_value_schema["fields"] if f["name"] == "timestamp_micros"
        )
        assert timestamp_field["type"] == "long", "timestamp_micros must be long type"

    def test_value_schema_ttl_is_nullable(self, expected_value_schema: Dict[str, Any]) -> None:
        """Validate that ttl_seconds is nullable for tables without TTL."""
        ttl_field = next(
            f for f in expected_value_schema["fields"] if f["name"] == "ttl_seconds"
        )

        assert isinstance(ttl_field["type"], list), "ttl_seconds must be nullable"
        assert "null" in ttl_field["type"], "ttl_seconds must include null type"
        assert "int" in ttl_field["type"], "ttl_seconds must include int type"

    def test_value_schema_before_after_are_nullable_maps(
        self, expected_value_schema: Dict[str, Any]
    ) -> None:
        """Validate that before/after fields are nullable maps for representing row data."""
        for field_name in ["before", "after"]:
            field = next(
                f for f in expected_value_schema["fields"] if f["name"] == field_name
            )

            assert isinstance(field["type"], list), f"{field_name} must be nullable"
            assert "null" in field["type"], f"{field_name} must include null type"

            map_type = next(t for t in field["type"] if isinstance(t, dict))
            assert map_type["type"] == "map", f"{field_name} must be map type"

    def test_value_schema_is_tombstone_is_boolean(
        self, expected_value_schema: Dict[str, Any]
    ) -> None:
        """Validate that is_tombstone is boolean with default false."""
        tombstone_field = next(
            f for f in expected_value_schema["fields"] if f["name"] == "is_tombstone"
        )

        assert tombstone_field["type"] == "boolean", "is_tombstone must be boolean"
        assert tombstone_field["default"] is False, "is_tombstone default must be False"

    def test_schema_namespace_is_correct(self, expected_value_schema: Dict[str, Any]) -> None:
        """Validate that schema uses correct namespace."""
        assert (
            expected_value_schema["namespace"] == "com.cdc.events"
        ), "Schema must use namespace com.cdc.events"

    def test_schema_is_record_type(self, expected_value_schema: Dict[str, Any]) -> None:
        """Validate that schema is of type record."""
        assert expected_value_schema["type"] == "record", "Schema must be record type"

    def test_schema_serialization(self, expected_value_schema: Dict[str, Any]) -> None:
        """Validate that schema can be serialized to JSON for Schema Registry."""
        try:
            schema_json = json.dumps(expected_value_schema)
            assert len(schema_json) > 0, "Schema must serialize to non-empty JSON"
        except Exception as e:
            pytest.fail(f"Schema serialization failed: {e}")

    def test_backward_compatibility_fields_have_defaults(
        self, expected_value_schema: Dict[str, Any]
    ) -> None:
        """
        Validate that nullable fields have defaults for backward compatibility.

        According to BACKWARD compatibility mode in Schema Registry,
        new fields must have defaults.
        """
        nullable_fields = [
            f
            for f in expected_value_schema["fields"]
            if isinstance(f["type"], list) and "null" in f["type"]
        ]

        for field in nullable_fields:
            assert (
                "default" in field
            ), f"Nullable field {field['name']} must have default for backward compatibility"
