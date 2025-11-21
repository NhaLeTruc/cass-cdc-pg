from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import hvac
from hvac.exceptions import VaultError, InvalidPath
import structlog

from src.repositories.base import AbstractRepository
from src.config.settings import Settings
from src.monitoring.metrics import vault_connection_errors_total

logger = structlog.get_logger(__name__)


class VaultRepository(AbstractRepository):
    """
    Repository for HashiCorp Vault operations.

    Provides methods to retrieve credentials, renew leases, and perform health checks
    on Vault secret management system.
    """

    def __init__(self, settings: Settings):
        """
        Initialize Vault repository.

        Args:
            settings: Application settings containing Vault configuration
        """
        self.settings = settings
        self.client: Optional[hvac.Client] = None
        self._credentials_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._logger = logger.bind(component="vault_repository")

    def connect(self) -> None:
        """
        Establish connection to Vault server.

        Raises:
            VaultError: If unable to connect to Vault or authenticate
        """
        try:
            self._logger.info(
                "connecting_to_vault",
                url=self.settings.vault.url,
            )

            self.client = hvac.Client(
                url=self.settings.vault.url,
                token=self.settings.vault.token,
            )

            if not self.client.is_authenticated():
                raise VaultError("Vault authentication failed")

            self._logger.info("vault_connection_established")

        except Exception as e:
            vault_connection_errors_total.inc()
            self._logger.error("vault_connection_failed", error=str(e))
            raise

    def health_check(self) -> bool:
        """
        Check if Vault connection is healthy.

        Returns:
            True if Vault is healthy and authenticated, False otherwise
        """
        if not self.client:
            self._logger.warning("health_check_failed", reason="no_client")
            return False

        try:
            health_status = self.client.sys.read_health_status()
            is_authenticated = self.client.is_authenticated()

            is_healthy = (
                not health_status.get("sealed", True)
                and health_status.get("initialized", False)
                and is_authenticated
            )

            if not is_healthy:
                self._logger.warning(
                    "vault_unhealthy",
                    sealed=health_status.get("sealed"),
                    initialized=health_status.get("initialized"),
                    authenticated=is_authenticated,
                )

            return is_healthy

        except Exception as e:
            self._logger.error("health_check_failed", error=str(e))
            return False

    def close(self) -> None:
        """Close Vault connection and cleanup resources."""
        self._credentials_cache.clear()
        self._cache_expiry.clear()
        self._logger.info("vault_connection_closed")

    def get_credentials(
        self,
        path: str,
        use_cache: bool = True,
        cache_ttl_hours: int = 23,
    ) -> Dict[str, Any]:
        """
        Retrieve credentials from Vault.

        Args:
            path: Vault secret path (e.g., 'secret/data/cdc/cassandra')
            use_cache: Whether to use cached credentials if available
            cache_ttl_hours: Cache TTL in hours (default 23 hours for 24h leases)

        Returns:
            Dictionary containing credentials

        Raises:
            InvalidPath: If the secret path does not exist
            VaultError: If unable to read from Vault
        """
        if use_cache:
            cached_creds = self._get_from_cache(path)
            if cached_creds:
                self._logger.debug("credentials_from_cache", path=path)
                return cached_creds

        try:
            self._logger.info("reading_credentials_from_vault", path=path)

            response = self.client.secrets.kv.v2.read_secret_version(path=path)

            if not response or "data" not in response:
                raise InvalidPath(f"No data found at path: {path}")

            credentials = response["data"]["data"]

            if use_cache:
                self._put_in_cache(path, credentials, cache_ttl_hours)

            self._logger.info("credentials_retrieved", path=path)

            return credentials

        except InvalidPath as e:
            self._logger.error("invalid_vault_path", path=path, error=str(e))
            raise
        except Exception as e:
            vault_connection_errors_total.inc()
            self._logger.error("vault_read_failed", path=path, error=str(e))
            raise VaultError(f"Failed to read from Vault: {e}")

    def renew_lease(self, lease_id: str, increment_seconds: int = 86400) -> Dict[str, Any]:
        """
        Renew a Vault lease.

        Args:
            lease_id: Lease ID to renew
            increment_seconds: Lease increment in seconds (default 24 hours)

        Returns:
            Dictionary containing lease renewal response

        Raises:
            VaultError: If unable to renew lease
        """
        try:
            self._logger.info(
                "renewing_vault_lease",
                lease_id=lease_id,
                increment_seconds=increment_seconds,
            )

            response = self.client.sys.renew_lease(
                lease_id=lease_id,
                increment=increment_seconds,
            )

            self._logger.info("lease_renewed", lease_id=lease_id)

            return response

        except Exception as e:
            vault_connection_errors_total.inc()
            self._logger.error("lease_renewal_failed", lease_id=lease_id, error=str(e))
            raise VaultError(f"Failed to renew lease: {e}")

    def refresh_credentials(self, path: str, cache_ttl_hours: int = 23) -> Dict[str, Any]:
        """
        Force refresh credentials from Vault and update cache.

        Args:
            path: Vault secret path
            cache_ttl_hours: Cache TTL in hours

        Returns:
            Dictionary containing refreshed credentials
        """
        self._logger.info("refreshing_credentials", path=path)

        if path in self._credentials_cache:
            del self._credentials_cache[path]
            del self._cache_expiry[path]

        return self.get_credentials(path, use_cache=True, cache_ttl_hours=cache_ttl_hours)

    def get_database_credentials(
        self,
        role_name: str,
        use_cache: bool = True,
        cache_ttl_hours: int = 23,
    ) -> Dict[str, Any]:
        """
        Get dynamic database credentials from Vault database secrets engine.

        Args:
            role_name: Database role name (e.g., 'postgresql-writer')
            use_cache: Whether to use cached credentials
            cache_ttl_hours: Cache TTL in hours

        Returns:
            Dictionary with 'username' and 'password' keys
        """
        path = f"database/creds/{role_name}"

        if use_cache:
            cached_creds = self._get_from_cache(path)
            if cached_creds:
                self._logger.debug("database_credentials_from_cache", role=role_name)
                return cached_creds

        try:
            self._logger.info("generating_database_credentials", role=role_name)

            response = self.client.secrets.database.generate_credentials(name=role_name)

            if not response or "data" not in response:
                raise VaultError(f"No credentials generated for role: {role_name}")

            credentials = {
                "username": response["data"]["username"],
                "password": response["data"]["password"],
                "lease_id": response.get("lease_id"),
                "lease_duration": response.get("lease_duration"),
            }

            if use_cache:
                self._put_in_cache(path, credentials, cache_ttl_hours)

            self._logger.info(
                "database_credentials_generated",
                role=role_name,
                username=credentials["username"],
                lease_duration=credentials.get("lease_duration"),
            )

            return credentials

        except Exception as e:
            vault_connection_errors_total.inc()
            self._logger.error(
                "database_credentials_generation_failed",
                role=role_name,
                error=str(e),
            )
            raise VaultError(f"Failed to generate database credentials: {e}")

    def _get_from_cache(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Get credentials from cache if not expired.

        Args:
            path: Vault secret path

        Returns:
            Cached credentials or None if expired/not found
        """
        if path in self._credentials_cache:
            expiry = self._cache_expiry.get(path)
            if expiry and datetime.utcnow() < expiry:
                return self._credentials_cache[path]
            else:
                del self._credentials_cache[path]
                del self._cache_expiry[path]

        return None

    def _put_in_cache(
        self,
        path: str,
        credentials: Dict[str, Any],
        ttl_hours: int,
    ) -> None:
        """
        Put credentials in cache with expiry.

        Args:
            path: Vault secret path
            credentials: Credentials to cache
            ttl_hours: Cache TTL in hours
        """
        self._credentials_cache[path] = credentials
        self._cache_expiry[path] = datetime.utcnow() + timedelta(hours=ttl_hours)

        self._logger.debug(
            "credentials_cached",
            path=path,
            expiry=self._cache_expiry[path].isoformat(),
        )
