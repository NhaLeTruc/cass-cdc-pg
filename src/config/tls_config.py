"""TLS 1.3 configuration for all database and service connections."""

import ssl
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


def create_tls_context(
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
    ca_file: Optional[str] = None,
    verify_mode: ssl.VerifyMode = ssl.CERT_REQUIRED,
) -> ssl.SSLContext:
    """
    Create SSL context with TLS 1.3 configuration.

    Args:
        cert_file: Path to client certificate file
        key_file: Path to client private key file
        ca_file: Path to CA certificate file
        verify_mode: SSL certificate verification mode

    Returns:
        Configured SSLContext with TLS 1.3
    """
    logger.info("creating_tls_context", tls_version="TLSv1.3")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3

    context.verify_mode = verify_mode

    if ca_file:
        context.load_verify_locations(cafile=ca_file)
        logger.info("tls_ca_loaded", ca_file=ca_file)

    if cert_file and key_file:
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        logger.info("tls_client_cert_loaded", cert_file=cert_file)

    context.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS")

    logger.info("tls_context_created", min_version="TLSv1.3", max_version="TLSv1.3")

    return context


def get_cassandra_ssl_options(
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
    ca_file: Optional[str] = None,
) -> dict:
    """
    Get SSL options for Cassandra driver.

    Args:
        cert_file: Path to client certificate
        key_file: Path to client private key
        ca_file: Path to CA certificate

    Returns:
        Dictionary with Cassandra SSL options
    """
    logger.info("creating_cassandra_ssl_options")

    ssl_context = create_tls_context(
        cert_file=cert_file,
        key_file=key_file,
        ca_file=ca_file,
    )

    return {
        "ssl_context": ssl_context,
        "check_hostname": True,
    }


def get_postgresql_ssl_params(
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
    ca_file: Optional[str] = None,
) -> dict:
    """
    Get SSL parameters for PostgreSQL connection.

    Args:
        cert_file: Path to client certificate
        key_file: Path to client private key
        ca_file: Path to CA certificate

    Returns:
        Dictionary with PostgreSQL SSL parameters
    """
    logger.info("creating_postgresql_ssl_params")

    params = {
        "sslmode": "require",
        "sslprotocol": "TLSv1.3",
    }

    if ca_file:
        params["sslrootcert"] = ca_file

    if cert_file:
        params["sslcert"] = cert_file

    if key_file:
        params["sslkey"] = key_file

    return params


def get_kafka_ssl_config(
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
    ca_file: Optional[str] = None,
) -> dict:
    """
    Get SSL configuration for Kafka client.

    Args:
        cert_file: Path to client certificate
        key_file: Path to client private key
        ca_file: Path to CA certificate

    Returns:
        Dictionary with Kafka SSL configuration
    """
    logger.info("creating_kafka_ssl_config")

    config = {
        "security.protocol": "SSL",
        "ssl.enabled.protocols": "TLSv1.3",
        "ssl.protocol": "TLSv1.3",
    }

    if ca_file:
        config["ssl.ca.location"] = ca_file

    if cert_file:
        config["ssl.certificate.location"] = cert_file

    if key_file:
        config["ssl.key.location"] = key_file

    return config
