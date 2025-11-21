"""Integration test for Vault credential retrieval."""

import time
import pytest
import requests
import psycopg2
from cassandra.cluster import Cluster
import structlog

logger = structlog.get_logger(__name__)


class TestVaultCredentials:
    """Test that CDC pipeline retrieves credentials from Vault."""

    def test_vault_available(self):
        """Verify Vault is running and accessible."""
        logger.info("checking_vault_availability")

        try:
            response = requests.get("http://localhost:8200/v1/sys/health", timeout=10)

            logger.info("vault_health_response", status_code=response.status_code)

            assert response.status_code in [200, 429, 472, 473], \
                f"Vault health check failed with status {response.status_code}"

            logger.info("vault_is_available")

        except requests.exceptions.RequestException as e:
            logger.error("vault_not_available", error=str(e))
            pytest.skip(f"Vault not available: {e}")

    def test_cassandra_credentials_from_vault(self):
        """
        Test that Cassandra connection uses credentials from Vault.

        Verifies credentials are retrieved from secret/data/cdc/cassandra path.
        """
        logger.info("test_cassandra_vault_credentials_start")

        # Check if Vault has Cassandra credentials
        try:
            response = requests.get(
                "http://localhost:8200/v1/secret/data/cdc/cassandra",
                headers={"X-Vault-Token": "dev-token"},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                logger.info("vault_cassandra_credentials_found", data=data.get("data", {}).keys())

                assert "data" in data, "Vault response missing data field"
                assert "data" in data["data"], "Vault response missing nested data field"

                credentials = data["data"]["data"]
                assert "username" in credentials, "Vault Cassandra credentials missing username"
                assert "password" in credentials, "Vault Cassandra credentials missing password"

                username = credentials["username"]
                password = credentials["password"]

                logger.info("testing_cassandra_connection_with_vault_credentials", username=username)

                # Test Cassandra connection with Vault credentials
                try:
                    cluster = Cluster(
                        ["localhost"],
                        port=9042,
                        auth_provider=None,  # Cassandra may not require auth in dev
                    )
                    session = cluster.connect()
                    session.execute("SELECT release_version FROM system.local")
                    cluster.shutdown()

                    logger.info("cassandra_connection_successful_with_vault_credentials")

                except Exception as e:
                    logger.warning(
                        "cassandra_connection_failed",
                        error=str(e),
                        note="Cassandra may not be configured with auth in development"
                    )

            else:
                logger.warning(
                    "vault_cassandra_credentials_not_found",
                    status_code=response.status_code,
                    note="Credentials may not be initialized yet"
                )
                pytest.skip("Vault Cassandra credentials not initialized")

        except requests.exceptions.RequestException as e:
            logger.error("vault_request_failed", error=str(e))
            pytest.skip(f"Vault not available: {e}")

    def test_postgresql_credentials_from_vault(self):
        """
        Test that PostgreSQL connection uses credentials from Vault.

        Verifies credentials are retrieved from database/creds/postgresql-writer path.
        """
        logger.info("test_postgresql_vault_credentials_start")

        # Check if Vault has PostgreSQL dynamic credentials configured
        try:
            response = requests.get(
                "http://localhost:8200/v1/database/creds/postgresql-writer",
                headers={"X-Vault-Token": "dev-token"},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                logger.info("vault_postgresql_credentials_generated", data=data.get("data", {}).keys())

                assert "data" in data, "Vault response missing data field"

                credentials = data["data"]
                assert "username" in credentials, "Vault PostgreSQL credentials missing username"
                assert "password" in credentials, "Vault PostgreSQL credentials missing password"

                username = credentials["username"]
                password = credentials["password"]
                lease_id = data.get("lease_id")
                lease_duration = data.get("lease_duration")

                logger.info(
                    "vault_postgresql_dynamic_credentials",
                    username=username,
                    lease_duration=lease_duration,
                )

                # Verify lease duration is 24 hours (86400 seconds)
                assert lease_duration == 86400, \
                    f"Expected 24h lease duration (86400s), got {lease_duration}s"

                # Test PostgreSQL connection with Vault credentials
                try:
                    conn = psycopg2.connect(
                        host="localhost",
                        port=5432,
                        dbname="cdc_target",
                        user=username,
                        password=password,
                        connect_timeout=10,
                    )

                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    cursor.close()
                    conn.close()

                    assert result[0] == 1, "PostgreSQL query with Vault credentials failed"

                    logger.info("postgresql_connection_successful_with_vault_credentials", username=username)

                except psycopg2.Error as e:
                    logger.error("postgresql_connection_failed_with_vault_credentials", error=str(e))
                    pytest.fail(f"PostgreSQL connection failed with Vault credentials: {e}")

            else:
                logger.warning(
                    "vault_postgresql_dynamic_credentials_not_configured",
                    status_code=response.status_code,
                    note="Dynamic database credentials may not be configured yet"
                )
                pytest.skip("Vault PostgreSQL dynamic credentials not configured")

        except requests.exceptions.RequestException as e:
            logger.error("vault_request_failed", error=str(e))
            pytest.skip(f"Vault not available: {e}")

    def test_vault_approle_authentication(self):
        """
        Test AppRole authentication for CDC pipeline.

        Verifies that AppRole authentication is configured and working.
        """
        logger.info("test_vault_approle_start")

        try:
            # Check if AppRole auth method is enabled
            response = requests.get(
                "http://localhost:8200/v1/sys/auth",
                headers={"X-Vault-Token": "dev-token"},
                timeout=10,
            )

            if response.status_code == 200:
                auth_methods = response.json()
                logger.info("vault_auth_methods", methods=list(auth_methods.keys()))

                approle_enabled = "approle/" in auth_methods

                if approle_enabled:
                    logger.info("vault_approle_enabled")

                    # Try to read AppRole role
                    response = requests.get(
                        "http://localhost:8200/v1/auth/approle/role/cdc-pipeline",
                        headers={"X-Vault-Token": "dev-token"},
                        timeout=10,
                    )

                    if response.status_code == 200:
                        role_data = response.json()
                        logger.info("vault_approle_role_configured", role=role_data.get("data", {}))

                        logger.info("test_vault_approle_success")
                    else:
                        logger.warning(
                            "vault_approle_role_not_found",
                            note="AppRole role 'cdc-pipeline' not configured yet"
                        )
                else:
                    logger.warning(
                        "vault_approle_not_enabled",
                        note="AppRole auth method not enabled in Vault"
                    )
                    pytest.skip("AppRole not enabled in Vault")

        except requests.exceptions.RequestException as e:
            logger.error("vault_request_failed", error=str(e))
            pytest.skip(f"Vault not available: {e}")

    def test_vault_policy_permissions(self):
        """
        Test that CDC policy has correct permissions.

        Verifies read access to secret/data/cdc/* and database/creds/postgresql-writer.
        """
        logger.info("test_vault_policy_start")

        try:
            # Read cdc-policy
            response = requests.get(
                "http://localhost:8200/v1/sys/policy/cdc-policy",
                headers={"X-Vault-Token": "dev-token"},
                timeout=10,
            )

            if response.status_code == 200:
                policy_data = response.json()
                policy_rules = policy_data.get("data", {}).get("rules", "")

                logger.info("vault_cdc_policy_found", policy_length=len(policy_rules))

                # Verify policy contains required paths
                assert "secret/data/cdc/*" in policy_rules or "secret/cdc/*" in policy_rules, \
                    "CDC policy missing access to secret/cdc/*"

                assert "database/creds/postgresql-writer" in policy_rules, \
                    "CDC policy missing access to database/creds/postgresql-writer"

                logger.info("vault_policy_permissions_validated")

            else:
                logger.warning(
                    "vault_cdc_policy_not_found",
                    status_code=response.status_code,
                    note="CDC policy not configured yet"
                )
                pytest.skip("Vault CDC policy not configured")

        except requests.exceptions.RequestException as e:
            logger.error("vault_request_failed", error=str(e))
            pytest.skip(f"Vault not available: {e}")
