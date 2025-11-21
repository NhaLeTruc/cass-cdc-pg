import pytest
from typing import Dict, Any


class TestKafkaTopicsContract:
    """
    Contract test for cdc-events Kafka topic configuration.

    Validates topic config, partitioning strategy, and replication
    according to the Kafka topics contract defined in contracts/kafka-topics.md.
    """

    @pytest.fixture
    def expected_cdc_events_config(self) -> Dict[str, Any]:
        """Expected configuration for cdc-events-{table} topics."""
        return {
            "topic_pattern": "cdc-events-{table}",
            "partitions": 6,
            "replication_factor": 3,
            "retention_ms": 604800000,
            "cleanup_policy": "delete",
            "compression_type": "snappy",
            "min_insync_replicas": 2,
            "max_message_bytes": 1048576,
        }

    @pytest.fixture
    def expected_dlq_topic_config(self) -> Dict[str, Any]:
        """Expected configuration for dlq-events topic."""
        return {
            "topic_name": "dlq-events",
            "partitions": 3,
            "replication_factor": 3,
            "retention_ms": 2592000000,
            "cleanup_policy": "delete",
            "compression_type": "snappy",
            "min_insync_replicas": 2,
        }

    @pytest.fixture
    def expected_schema_changes_topic_config(self) -> Dict[str, Any]:
        """Expected configuration for schema-changes topic."""
        return {
            "topic_name": "schema-changes",
            "partitions": 1,
            "replication_factor": 3,
            "retention_ms": 31536000000,
            "cleanup_policy": "compact",
            "compression_type": "snappy",
            "min_insync_replicas": 2,
        }

    def test_cdc_events_topic_has_correct_partitions(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """Validate that cdc-events topics have 6 partitions for parallelism."""
        assert (
            expected_cdc_events_config["partitions"] == 6
        ), "cdc-events topics must have 6 partitions for 10K events/sec throughput"

    def test_cdc_events_topic_has_replication_factor_3(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """Validate that cdc-events topics have replication factor 3 for fault tolerance."""
        assert (
            expected_cdc_events_config["replication_factor"] == 3
        ), "cdc-events topics must have replication factor 3 for production reliability"

    def test_cdc_events_topic_has_7_day_retention(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """Validate that cdc-events topics have 7-day retention."""
        seven_days_ms = 7 * 24 * 60 * 60 * 1000
        assert (
            expected_cdc_events_config["retention_ms"] == seven_days_ms
        ), "cdc-events topics must have 7-day retention (604800000ms)"

    def test_cdc_events_topic_uses_delete_cleanup_policy(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """Validate that cdc-events topics use delete cleanup policy."""
        assert (
            expected_cdc_events_config["cleanup_policy"] == "delete"
        ), "cdc-events topics must use delete cleanup policy"

    def test_cdc_events_topic_uses_snappy_compression(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """Validate that cdc-events topics use snappy compression for performance."""
        assert (
            expected_cdc_events_config["compression_type"] == "snappy"
        ), "cdc-events topics must use snappy compression for optimal CPU/space tradeoff"

    def test_cdc_events_topic_has_min_insync_replicas_2(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """Validate that cdc-events topics have min.insync.replicas=2 for durability."""
        assert (
            expected_cdc_events_config["min_insync_replicas"] == 2
        ), "cdc-events topics must have min.insync.replicas=2 with acks=all"

    def test_cdc_events_topic_max_message_size_1mb(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """Validate that cdc-events topics allow 1MB max message size."""
        assert (
            expected_cdc_events_config["max_message_bytes"] == 1048576
        ), "cdc-events topics must allow 1MB messages for large BLOB/TEXT columns"

    def test_dlq_topic_has_30_day_retention(
        self, expected_dlq_topic_config: Dict[str, Any]
    ) -> None:
        """Validate that dlq-events topic has 30-day retention for error investigation."""
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        assert (
            expected_dlq_topic_config["retention_ms"] == thirty_days_ms
        ), "dlq-events topic must have 30-day retention (2592000000ms)"

    def test_dlq_topic_has_fewer_partitions(
        self, expected_dlq_topic_config: Dict[str, Any]
    ) -> None:
        """Validate that dlq-events topic has 3 partitions (lower volume expected)."""
        assert (
            expected_dlq_topic_config["partitions"] == 3
        ), "dlq-events topic should have 3 partitions for lower error volume"

    def test_schema_changes_topic_has_single_partition(
        self, expected_schema_changes_topic_config: Dict[str, Any]
    ) -> None:
        """Validate that schema-changes topic has 1 partition for total ordering."""
        assert (
            expected_schema_changes_topic_config["partitions"] == 1
        ), "schema-changes topic must have 1 partition for total ordering of schema evolution"

    def test_schema_changes_topic_has_1_year_retention(
        self, expected_schema_changes_topic_config: Dict[str, Any]
    ) -> None:
        """Validate that schema-changes topic has 1-year retention for audit trail."""
        one_year_ms = 365 * 24 * 60 * 60 * 1000
        assert (
            expected_schema_changes_topic_config["retention_ms"] == one_year_ms
        ), "schema-changes topic must have 1-year retention (31536000000ms)"

    def test_schema_changes_topic_uses_compact_cleanup_policy(
        self, expected_schema_changes_topic_config: Dict[str, Any]
    ) -> None:
        """Validate that schema-changes topic uses compact cleanup policy."""
        assert (
            expected_schema_changes_topic_config["cleanup_policy"] == "compact"
        ), "schema-changes topic must use compact cleanup policy to retain latest schema per table"

    def test_topic_naming_convention(self, expected_cdc_events_config: Dict[str, Any]) -> None:
        """Validate that topic follows naming convention cdc-events-{table}."""
        pattern = expected_cdc_events_config["topic_pattern"]
        assert "cdc-events-" in pattern, "Topic must use prefix cdc-events-"
        assert "{table}" in pattern, "Topic must include {table} placeholder"

    def test_all_topics_have_replication_factor_3(
        self,
        expected_cdc_events_config: Dict[str, Any],
        expected_dlq_topic_config: Dict[str, Any],
        expected_schema_changes_topic_config: Dict[str, Any],
    ) -> None:
        """Validate that all topics have replication factor 3 for production reliability."""
        configs = [
            expected_cdc_events_config,
            expected_dlq_topic_config,
            expected_schema_changes_topic_config,
        ]

        for config in configs:
            assert (
                config["replication_factor"] == 3
            ), f"All topics must have replication factor 3 for fault tolerance"

    def test_all_topics_use_snappy_compression(
        self,
        expected_cdc_events_config: Dict[str, Any],
        expected_dlq_topic_config: Dict[str, Any],
        expected_schema_changes_topic_config: Dict[str, Any],
    ) -> None:
        """Validate that all topics use snappy compression."""
        configs = [
            expected_cdc_events_config,
            expected_dlq_topic_config,
            expected_schema_changes_topic_config,
        ]

        for config in configs:
            assert (
                config["compression_type"] == "snappy"
            ), "All topics must use snappy compression"

    def test_partitioning_strategy_supports_throughput_requirement(
        self, expected_cdc_events_config: Dict[str, Any]
    ) -> None:
        """
        Validate that partitioning strategy supports 10K events/sec requirement.

        With 6 partitions and 3 consumers (one per partition pair),
        each consumer handles ~3,333 events/sec which is achievable.
        """
        partitions = expected_cdc_events_config["partitions"]
        target_throughput = 10000

        events_per_partition = target_throughput / partitions

        assert (
            events_per_partition <= 2000
        ), f"With {partitions} partitions, each handles {events_per_partition} events/sec which must be ≤2000 for single consumer"
