import pytest
import time
import subprocess
from typing import List, Dict


class TestDockerComposeHealth:
    """
    Integration test for Docker Compose health checks.

    Verifies that all 12 services start and become healthy within 90 seconds.
    Tests the complete local development environment setup.
    """

    EXPECTED_SERVICES = [
        "zookeeper",
        "kafka",
        "schema-registry",
        "kafka-connect",
        "cassandra",
        "postgres",
        "vault",
        "prometheus",
        "grafana",
        "jaeger",
    ]

    HEALTH_CHECK_TIMEOUT = 90
    HEALTH_CHECK_INTERVAL = 5

    @pytest.mark.skip(reason="Requires Docker Compose services running")
    def test_all_services_start_and_become_healthy(self) -> None:
        """Test that all Docker Compose services start and become healthy within 90 seconds."""
        start_time = time.time()

        healthy_services = set()
        attempts = 0
        max_attempts = self.HEALTH_CHECK_TIMEOUT // self.HEALTH_CHECK_INTERVAL

        while attempts < max_attempts:
            service_status = self._get_service_status()

            for service in self.EXPECTED_SERVICES:
                if service in service_status:
                    status = service_status[service]
                    if status in ["running", "healthy"]:
                        healthy_services.add(service)

            if len(healthy_services) == len(self.EXPECTED_SERVICES):
                elapsed = time.time() - start_time
                print(f"All services healthy in {elapsed:.2f} seconds")
                break

            attempts += 1
            time.sleep(self.HEALTH_CHECK_INTERVAL)

        elapsed_time = time.time() - start_time

        assert elapsed_time < self.HEALTH_CHECK_TIMEOUT, (
            f"Services took {elapsed_time:.2f}s to become healthy, "
            f"expected <{self.HEALTH_CHECK_TIMEOUT}s"
        )

        missing_services = set(self.EXPECTED_SERVICES) - healthy_services
        assert len(missing_services) == 0, (
            f"Services not healthy: {missing_services}"
        )

    @pytest.mark.skip(reason="Requires Docker Compose services running")
    def test_services_have_correct_ports(self) -> None:
        """Test that all services expose their expected ports."""
        expected_ports = {
            "cassandra": "9042",
            "postgres": "5432",
            "kafka": "9092",
            "schema-registry": "8081",
            "kafka-connect": "8083",
            "vault": "8200",
            "prometheus": "9090",
            "grafana": "3000",
            "jaeger": "16686",
            "zookeeper": "2181",
        }

        port_mapping = self._get_port_mapping()

        for service, expected_port in expected_ports.items():
            assert service in port_mapping, f"Service {service} not found"
            actual_ports = port_mapping[service]
            assert expected_port in actual_ports, (
                f"Service {service} does not expose port {expected_port}, "
                f"found {actual_ports}"
            )

    @pytest.mark.skip(reason="Requires Docker Compose services running")
    def test_services_can_be_restarted(self) -> None:
        """Test that services can be stopped and restarted successfully."""
        test_service = "cassandra"

        self._run_docker_compose_command(["stop", test_service])

        time.sleep(2)

        status = self._get_service_status()
        assert status.get(test_service) != "running", (
            f"Service {test_service} should be stopped"
        )

        self._run_docker_compose_command(["start", test_service])

        healthy = self._wait_for_service_healthy(test_service, timeout=30)
        assert healthy, f"Service {test_service} did not become healthy after restart"

    @pytest.mark.skip(reason="Requires Docker Compose services running")
    def test_service_logs_accessible(self) -> None:
        """Test that logs can be retrieved from all services."""
        for service in self.EXPECTED_SERVICES:
            logs = self._get_service_logs(service, tail=10)
            assert logs is not None, f"Could not retrieve logs for {service}"
            assert len(logs) > 0, f"No logs found for {service}"

    @pytest.mark.skip(reason="Requires Docker Compose services running")
    def test_network_connectivity_between_services(self) -> None:
        """Test that services can communicate with each other."""
        connectivity_tests = [
            ("kafka-connect", "kafka", "9092"),
            ("kafka-connect", "schema-registry", "8081"),
            ("kafka", "zookeeper", "2181"),
        ]

        for source, target, port in connectivity_tests:
            can_connect = self._test_service_connectivity(source, target, port)
            assert can_connect, (
                f"Service {source} cannot connect to {target}:{port}"
            )

    def _get_service_status(self) -> Dict[str, str]:
        """Get status of all Docker Compose services."""
        result = subprocess.run(
            ["docker-compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            cwd="/home/bob/WORK/cass-cdc-pg",
        )

        if result.returncode != 0:
            return {}

        services = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                import json
                service_info = json.loads(line)
                service_name = service_info.get("Service", service_info.get("Name", ""))
                state = service_info.get("State", "")
                services[service_name] = state.lower()
            except:
                pass

        return services

    def _get_port_mapping(self) -> Dict[str, List[str]]:
        """Get port mappings for all services."""
        result = subprocess.run(
            ["docker-compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            cwd="/home/bob/WORK/cass-cdc-pg",
        )

        if result.returncode != 0:
            return {}

        port_mapping = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                import json
                service_info = json.loads(line)
                service_name = service_info.get("Service", "")
                publishers = service_info.get("Publishers", [])

                ports = []
                for pub in publishers:
                    if isinstance(pub, dict):
                        target_port = pub.get("TargetPort")
                        if target_port:
                            ports.append(str(target_port))

                if service_name and ports:
                    port_mapping[service_name] = ports
            except:
                pass

        return port_mapping

    def _wait_for_service_healthy(self, service: str, timeout: int = 30) -> bool:
        """Wait for a specific service to become healthy."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self._get_service_status()
            if service in status and status[service] in ["running", "healthy"]:
                return True
            time.sleep(2)

        return False

    def _get_service_logs(self, service: str, tail: int = 10) -> str:
        """Get logs from a specific service."""
        result = subprocess.run(
            ["docker-compose", "logs", "--tail", str(tail), service],
            capture_output=True,
            text=True,
            cwd="/home/bob/WORK/cass-cdc-pg",
        )

        return result.stdout if result.returncode == 0 else None

    def _test_service_connectivity(
        self, source: str, target: str, port: str
    ) -> bool:
        """Test if source service can connect to target service."""
        result = subprocess.run(
            [
                "docker-compose",
                "exec",
                "-T",
                source,
                "nc",
                "-zv",
                target,
                port,
            ],
            capture_output=True,
            text=True,
            cwd="/home/bob/WORK/cass-cdc-pg",
            timeout=10,
        )

        return result.returncode == 0

    def _run_docker_compose_command(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run a docker compose command."""
        return subprocess.run(
            ["docker-compose"] + args,
            capture_output=True,
            text=True,
            cwd="/home/bob/WORK/cass-cdc-pg",
        )
