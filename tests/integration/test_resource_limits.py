import pytest
import subprocess
import json
from typing import Dict, Any


class TestResourceLimits:
    """
    Integration test for Docker Compose resource constraints.

    Verifies that total Docker memory usage remains under 4GB to ensure
    the CDC pipeline can run on a developer laptop.
    """

    MAX_TOTAL_MEMORY_GB = 4.0
    MAX_TOTAL_MEMORY_BYTES = int(MAX_TOTAL_MEMORY_GB * 1024 * 1024 * 1024)

    EXPECTED_MEMORY_LIMITS = {
        "cassandra": 1024,
        "postgres": 512,
        "kafka": 1024,
        "schema-registry": 256,
        "kafka-connect": 256,
        "vault": 256,
        "prometheus": 256,
        "grafana": 256,
        "jaeger": 256,
        "zookeeper": 256,
    }

    def test_total_docker_memory_under_4gb(self) -> None:
        """Test that total Docker memory usage is under 4GB."""
        memory_stats = self._get_container_memory_stats()

        total_memory_bytes = sum(
            stats["memory_usage"] for stats in memory_stats.values()
        )

        total_memory_gb = total_memory_bytes / (1024 * 1024 * 1024)

        assert total_memory_bytes < self.MAX_TOTAL_MEMORY_BYTES, (
            f"Total memory usage {total_memory_gb:.2f}GB exceeds limit of "
            f"{self.MAX_TOTAL_MEMORY_GB}GB"
        )

        print(f"Total memory usage: {total_memory_gb:.2f}GB / {self.MAX_TOTAL_MEMORY_GB}GB")

    def test_individual_service_memory_limits(self) -> None:
        """Test that each service respects its memory limit."""
        memory_stats = self._get_container_memory_stats()

        for service, expected_limit_mb in self.EXPECTED_MEMORY_LIMITS.items():
            if service not in memory_stats:
                pytest.skip(f"Service {service} not running")

            stats = memory_stats[service]
            actual_usage_mb = stats["memory_usage"] / (1024 * 1024)
            limit_mb = stats.get("memory_limit", 0) / (1024 * 1024)

            if limit_mb > 0:
                assert limit_mb <= expected_limit_mb * 1.1, (
                    f"Service {service} limit {limit_mb:.0f}MB exceeds "
                    f"expected {expected_limit_mb}MB"
                )

            print(f"{service}: {actual_usage_mb:.0f}MB / {expected_limit_mb}MB limit")

    def test_memory_limits_configured_in_docker_compose(self) -> None:
        """Test that memory limits are properly configured in docker-compose.yml."""
        compose_config = self._get_docker_compose_config()

        for service_name, expected_limit_mb in self.EXPECTED_MEMORY_LIMITS.items():
            if service_name not in compose_config.get("services", {}):
                continue

            service_config = compose_config["services"][service_name]

            deploy_config = service_config.get("deploy", {})
            resources = deploy_config.get("resources", {})
            limits = resources.get("limits", {})

            memory_limit_str = limits.get("memory")

            if memory_limit_str:
                memory_limit_bytes = self._parse_memory_string(memory_limit_str)
                memory_limit_mb = memory_limit_bytes / (1024 * 1024)

                assert memory_limit_mb <= expected_limit_mb * 1.1, (
                    f"Service {service_name} docker compose limit "
                    f"{memory_limit_mb:.0f}MB exceeds expected {expected_limit_mb}MB"
                )

    def test_cpu_limits_reasonable(self) -> None:
        """Test that CPU limits are reasonable for laptop development."""
        cpu_stats = self._get_container_cpu_stats()

        for service, stats in cpu_stats.items():
            cpu_percent = stats.get("cpu_percent", 0)

            assert cpu_percent < 100, (
                f"Service {service} using {cpu_percent:.1f}% CPU, should be <100%"
            )

    def test_no_memory_swapping(self) -> None:
        """Test that services are not heavily swapping memory."""
        memory_stats = self._get_container_memory_stats()

        for service, stats in memory_stats.items():
            usage = stats["memory_usage"]
            limit = stats.get("memory_limit", usage * 2)

            usage_percent = (usage / limit * 100) if limit > 0 else 0

            assert usage_percent < 90, (
                f"Service {service} using {usage_percent:.1f}% of memory limit, "
                f"may be swapping"
            )

    def test_disk_usage_reasonable(self) -> None:
        """Test that Docker disk usage is reasonable for local development."""
        disk_usage = self._get_docker_disk_usage()

        total_size_gb = disk_usage["total_size"] / (1024 * 1024 * 1024)

        assert total_size_gb < 20, (
            f"Docker disk usage {total_size_gb:.2f}GB exceeds 20GB, "
            f"may be too large for laptop"
        )

    def _get_container_memory_stats(self) -> Dict[str, Dict[str, int]]:
        """Get memory statistics for all running containers."""
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return {}

        stats = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            try:
                container_stats = json.loads(line)
                name = container_stats.get("Name", "")

                service_name = self._extract_service_name(name)

                if service_name:
                    mem_usage_str = container_stats.get("MemUsage", "0B / 0B")
                    usage_str, limit_str = mem_usage_str.split(" / ")

                    stats[service_name] = {
                        "memory_usage": self._parse_memory_string(usage_str.strip()),
                        "memory_limit": self._parse_memory_string(limit_str.strip()),
                    }
            except (json.JSONDecodeError, ValueError):
                continue

        return stats

    def _get_container_cpu_stats(self) -> Dict[str, Dict[str, float]]:
        """Get CPU statistics for all running containers."""
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return {}

        stats = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            try:
                container_stats = json.loads(line)
                name = container_stats.get("Name", "")
                service_name = self._extract_service_name(name)

                if service_name:
                    cpu_str = container_stats.get("CPUPerc", "0%")
                    cpu_percent = float(cpu_str.rstrip("%"))

                    stats[service_name] = {"cpu_percent": cpu_percent}
            except (json.JSONDecodeError, ValueError):
                continue

        return stats

    def _get_docker_compose_config(self) -> Dict[str, Any]:
        """Get parsed docker-compose.yml configuration."""
        result = subprocess.run(
            ["docker-compose", "config"],
            capture_output=True,
            text=True,
            cwd="/home/bob/WORK/cass-cdc-pg",
        )

        if result.returncode != 0:
            return {}

        try:
            import yaml
            return yaml.safe_load(result.stdout)
        except:
            return {}

    def _get_docker_disk_usage(self) -> Dict[str, int]:
        """Get Docker disk usage statistics."""
        result = subprocess.run(
            ["docker", "system", "df", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
        )

        total_size = 0

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    usage = json.loads(line)
                    size_str = usage.get("Size", "0B")
                    total_size += self._parse_memory_string(size_str)
                except:
                    pass

        return {"total_size": total_size}

    def _parse_memory_string(self, mem_str: str) -> int:
        """Parse memory string (e.g., '512MiB', '1.5GiB') to bytes."""
        mem_str = mem_str.strip().upper()

        if not mem_str or mem_str == "0" or mem_str == "N/A":
            return 0

        mem_str = mem_str.replace("IB", "").replace("B", "")

        multipliers = {
            "K": 1024,
            "M": 1024 * 1024,
            "G": 1024 * 1024 * 1024,
            "T": 1024 * 1024 * 1024 * 1024,
        }

        for suffix, multiplier in multipliers.items():
            if mem_str.endswith(suffix):
                try:
                    value = float(mem_str[:-1])
                    return int(value * multiplier)
                except ValueError:
                    return 0

        try:
            return int(float(mem_str))
        except ValueError:
            return 0

    def _extract_service_name(self, container_name: str) -> str:
        """Extract service name from container name."""
        for service in self.EXPECTED_MEMORY_LIMITS.keys():
            if service in container_name.lower():
                return service

        return container_name.split("_")[0] if "_" in container_name else container_name
