"""Alert Service (T117).

Service for sending reconciliation alerts to Prometheus/AlertManager.
"""

import httpx
import logging
from typing import Optional
from src.models.reconciliation_job import ReconciliationJob
from src.repositories.reconciliation_repository import ReconciliationRepository

logger = logging.getLogger(__name__)


class AlertService:
    """Alert service for reconciliation drift notifications.

    Sends alerts to Prometheus Pushgateway when drift exceeds thresholds.
    """

    def __init__(
        self,
        prometheus_pushgateway_url: str = "http://localhost:9091",
        warning_threshold: float = 1.0,
        critical_threshold: float = 5.0,
        reconciliation_repo: Optional[ReconciliationRepository] = None
    ):
        """Initialize alert service.

        Args:
            prometheus_pushgateway_url: URL of Prometheus Pushgateway
            warning_threshold: Drift percentage for warning alerts (default: 1%)
            critical_threshold: Drift percentage for critical alerts (default: 5%)
            reconciliation_repo: Optional repository for updating alert_fired flag
        """
        self.pushgateway_url = prometheus_pushgateway_url
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.reconciliation_repo = reconciliation_repo

    async def send_reconciliation_alert(
        self,
        job: ReconciliationJob
    ) -> bool:
        """Send reconciliation alert if drift exceeds threshold.

        Args:
            job: Reconciliation job to evaluate

        Returns:
            True if alert was sent, False otherwise
        """
        if job.drift_percentage is None:
            return False

        drift = float(job.drift_percentage)

        # Determine alert severity
        severity = None
        alertname = None

        if drift >= self.critical_threshold:
            severity = "critical"
            alertname = "ReconciliationDriftCritical"
        elif drift >= self.warning_threshold:
            severity = "warning"
            alertname = "ReconciliationDriftWarning"

        if severity is None:
            # No alert needed
            return False

        # Format alert message
        alert_message = self.format_alert_message(job, severity)

        # Send alert to Prometheus Pushgateway
        success = await self._push_alert_to_prometheus(
            alertname=alertname,
            severity=severity,
            table=job.table_name,
            drift_percentage=drift,
            mismatch_count=job.mismatch_count or 0,
            job_id=str(job.job_id),
            description=alert_message
        )

        # Update alert_fired flag if successful
        if success and self.reconciliation_repo:
            self.reconciliation_repo.update_job(
                job_id=job.job_id,
                alert_fired=True
            )

        return success

    def format_alert_message(
        self,
        job: ReconciliationJob,
        severity: str
    ) -> str:
        """Format alert message for reconciliation drift.

        Args:
            job: Reconciliation job
            severity: Alert severity (warning, critical)

        Returns:
            Formatted alert message
        """
        drift = float(job.drift_percentage) if job.drift_percentage else 0
        mismatch_count = job.mismatch_count or 0

        if severity == "critical":
            summary = (
                f"CRITICAL: High CDC reconciliation drift on {job.table_name}"
            )
            description = (
                f"Table {job.table_name} has {drift:.2f}% drift between "
                f"Cassandra and PostgreSQL (job_id: {job.job_id}). "
                f"{mismatch_count} records are out of sync. "
                f"This indicates a possible pipeline failure."
            )
        else:  # warning
            summary = (
                f"CDC reconciliation drift detected on {job.table_name}"
            )
            description = (
                f"Table {job.table_name} has {drift:.2f}% drift between "
                f"Cassandra and PostgreSQL (job_id: {job.job_id}). "
                f"{mismatch_count} records are out of sync."
            )

        return f"{summary}\n{description}"

    def determine_alert_severity(
        self,
        drift_percentage: float
    ) -> Optional[str]:
        """Determine alert severity based on drift percentage.

        Args:
            drift_percentage: Drift percentage

        Returns:
            'critical', 'warning', or None if no alert needed
        """
        if drift_percentage >= self.critical_threshold:
            return "critical"
        elif drift_percentage >= self.warning_threshold:
            return "warning"
        return None

    async def _push_alert_to_prometheus(
        self,
        alertname: str,
        severity: str,
        table: str,
        drift_percentage: float,
        mismatch_count: int,
        job_id: str,
        description: str
    ) -> bool:
        """Push alert to Prometheus Pushgateway.

        Args:
            alertname: Alert name (e.g., ReconciliationDriftCritical)
            severity: Alert severity (warning, critical)
            table: Table name
            drift_percentage: Drift percentage
            mismatch_count: Number of mismatches
            job_id: Reconciliation job ID
            description: Alert description

        Returns:
            True if alert was pushed successfully
        """
        # Format Prometheus metric with labels
        metric_name = "cdc_reconciliation_alert"
        labels = (
            f'alertname="{alertname}",'
            f'severity="{severity}",'
            f'table="{table}",'
            f'job_id="{job_id}"'
        )

        # Prometheus text format
        payload = (
            f"# TYPE {metric_name} gauge\n"
            f"# HELP {metric_name} CDC reconciliation drift alert\n"
            f"{metric_name}{{{labels}}} {drift_percentage}\n"
        )

        # Push to pushgateway
        url = f"{self.pushgateway_url}/metrics/job/cdc_reconciliation/table/{table}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    content=payload,
                    headers={"Content-Type": "text/plain"},
                    timeout=10.0
                )

                return response.status_code == 200

        except Exception as e:
            # Log error but don't fail reconciliation
            logger.error(f"Failed to push alert to Prometheus: {e}", exc_info=True)
            return False

    async def send_test_alert(self, table: str = "test_table") -> bool:
        """Send a test alert for verification.

        Args:
            table: Table name for test alert

        Returns:
            True if test alert was sent successfully
        """
        return await self._push_alert_to_prometheus(
            alertname="ReconciliationTestAlert",
            severity="info",
            table=table,
            drift_percentage=0.0,
            mismatch_count=0,
            job_id="test-job-id",
            description="Test alert from AlertService"
        )
