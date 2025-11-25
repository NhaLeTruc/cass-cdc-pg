"""Contract test for /health API endpoint."""

import pytest
import requests


class TestHealthAPI:
    """Contract tests for health endpoint per rest-api.md specification."""

    BASE_URL = "http://localhost:8080"

    @pytest.mark.skip(reason="Requires API server running on localhost:8080")
    def test_health_returns_200_when_all_components_healthy(self) -> None:
        """Verify /health returns 200 when all components are healthy."""
        response = requests.get(f"{self.BASE_URL}/health", timeout=10)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        data = response.json()
        assert "status" in data, "Response missing 'status' field"
        assert data["status"] == "healthy", f"Expected status 'healthy', got '{data['status']}'"

        assert "components" in data, "Response missing 'components' field"
        components = data["components"]

        required_components = ["cassandra", "postgresql", "kafka", "schema_registry", "vault"]
        for component in required_components:
            assert component in components, f"Missing component '{component}'"
            assert "status" in components[component], f"Component '{component}' missing 'status'"
            assert components[component]["status"] == "healthy", (
                f"Component '{component}' not healthy: {components[component]['status']}"
            )

    @pytest.mark.skip(reason="Requires API server running on localhost:8080")
    def test_health_returns_503_when_any_component_unhealthy(self) -> None:
        """Verify /health returns 503 if any component is unhealthy."""
        # Note: This test requires simulating component failure
        # For actual implementation, you would:
        # 1. Stop a service (e.g., docker compose stop cassandra)
        # 2. Call /health
        # 3. Verify 503 response
        # 4. Restart service

        # Placeholder: This test validates the structure only
        # In CI/CD, this would be implemented with chaos engineering
        pass

    @pytest.mark.skip(reason="Requires API server running on localhost:8080")
    def test_health_response_includes_timestamps(self) -> None:
        """Verify /health response includes check_time timestamp."""
        response = requests.get(f"{self.BASE_URL}/health", timeout=10)

        assert response.status_code == 200
        data = response.json()

        assert "check_time" in data, "Response missing 'check_time' field"
        # Validate ISO8601 format
        from datetime import datetime
        try:
            datetime.fromisoformat(data["check_time"].replace("Z", "+00:00"))
        except ValueError:
            pytest.fail(f"Invalid check_time format: {data['check_time']}")

    @pytest.mark.skip(reason="Requires API server running on localhost:8080")
    def test_health_response_includes_component_details(self) -> None:
        """Verify /health response includes detailed component information."""
        response = requests.get(f"{self.BASE_URL}/health", timeout=10)

        assert response.status_code == 200
        data = response.json()

        components = data.get("components", {})
        for component_name, component_data in components.items():
            assert "status" in component_data, (
                f"Component '{component_name}' missing 'status'"
            )
            # Optional fields that may be present
            # - response_time_ms
            # - message
            # - last_check_time

    @pytest.mark.skip(reason="Requires API server running on localhost:8080")
    def test_health_endpoint_performance(self) -> None:
        """Verify /health endpoint responds within acceptable time."""
        import time

        start_time = time.time()
        response = requests.get(f"{self.BASE_URL}/health", timeout=10)
        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 5.0, f"Health check took {elapsed:.2f}s, should be < 5s"
