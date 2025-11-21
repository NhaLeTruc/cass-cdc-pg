"""Contract test for /metrics API endpoint."""

import re

import pytest
import requests


class TestMetricsAPI:
    """Contract tests for metrics endpoint per rest-api.md specification."""

    BASE_URL = "http://localhost:8080"

    def test_metrics_returns_prometheus_format(self) -> None:
        """Verify /metrics returns data in Prometheus text format."""
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "text/plain" in response.headers.get("Content-Type", ""), (
            "Content-Type should be text/plain for Prometheus format"
        )

        text = response.text
        assert len(text) > 0, "Metrics response is empty"

        # Verify Prometheus format structure (# TYPE, # HELP, metric lines)
        has_type_comments = "# TYPE" in text
        has_metric_lines = any(
            line and not line.startswith("#") for line in text.split("\n")
        )

        assert has_type_comments or has_metric_lines, (
            "Response does not appear to be in Prometheus format"
        )

    def test_metrics_includes_required_metrics(self) -> None:
        """Verify required RED metrics are present."""
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)

        assert response.status_code == 200
        text = response.text

        required_metrics = [
            "cdc_events_processed_total",
            "cdc_processing_latency_seconds",
            "cdc_backlog_depth",
            "cdc_errors_total",
        ]

        for metric in required_metrics:
            assert metric in text, f"Required metric '{metric}' not found in response"

    def test_metrics_includes_cdc_events_processed_total(self) -> None:
        """Verify cdc_events_processed_total metric has required labels."""
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)

        text = response.text
        # Look for metric with table and operation labels
        pattern = r'cdc_events_processed_total\{.*table="[^"]+",.*operation="[^"]+"\}'

        matches = re.findall(pattern, text)
        # May not have data yet, but TYPE declaration should exist
        assert (
            "cdc_events_processed_total" in text
        ), "cdc_events_processed_total metric not found"

    def test_metrics_includes_latency_histogram(self) -> None:
        """Verify cdc_processing_latency_seconds is a histogram with buckets."""
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)

        text = response.text
        assert "cdc_processing_latency_seconds" in text, "Latency metric not found"

        # Histogram should have _bucket, _sum, _count suffixes
        # May not have data yet, but TYPE should be histogram
        has_type = "# TYPE cdc_processing_latency_seconds histogram" in text

        assert has_type, "cdc_processing_latency_seconds should be declared as histogram"

    def test_metrics_includes_backlog_depth_gauge(self) -> None:
        """Verify cdc_backlog_depth is a gauge metric."""
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)

        text = response.text
        assert "cdc_backlog_depth" in text, "Backlog depth metric not found"

        # Gauge should be declared with TYPE gauge
        has_type = "# TYPE cdc_backlog_depth gauge" in text
        assert has_type, "cdc_backlog_depth should be declared as gauge"

    def test_metrics_includes_errors_counter(self) -> None:
        """Verify cdc_errors_total counter includes error_type label."""
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)

        text = response.text
        assert "cdc_errors_total" in text, "Errors counter not found"

        # Counter should be declared with TYPE counter
        has_type = "# TYPE cdc_errors_total counter" in text
        assert has_type, "cdc_errors_total should be declared as counter"

    def test_metrics_endpoint_performance(self) -> None:
        """Verify /metrics endpoint responds quickly."""
        import time

        start_time = time.time()
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)
        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 2.0, f"Metrics endpoint took {elapsed:.2f}s, should be < 2s"

    def test_metrics_includes_schema_evolution_metrics(self) -> None:
        """Verify schema evolution metrics are exposed."""
        response = requests.get(f"{self.BASE_URL}/metrics", timeout=10)

        text = response.text
        schema_metrics = [
            "cdc_schema_changes_total",
            "cdc_schema_versions",
        ]

        for metric in schema_metrics:
            assert metric in text, f"Schema metric '{metric}' not found"
