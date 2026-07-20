"""Notification dispatcher for webhooks and SMTP email."""

from __future__ import annotations

import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from config import Settings
from services.llm_processor import ActionItem, MeetingAnalysis

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Raised when notification dispatch fails."""


class Notifier:
    """Dispatches meeting analysis to automation webhooks and/or email recipients."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Re-enable the built-in startup settings check
        settings.validate_notification_settings()

    def dispatch(self, analysis: MeetingAnalysis) -> dict[str, object]:
        """
        Send notifications according to configured mode.

        Returns a summary of dispatch results for API responses.
        """
        results: dict[str, object] = {
            "mode": self._settings.notification_mode,
            "webhook": None,
            "emails": [],
        }

        # Uses the .env setting instead of forcing "both"
        if self._settings.notification_mode in {"webhook", "both"}:
            results["webhook"] = self._send_webhook(analysis)

        if self._settings.notification_mode in {"email", "both"}:
            results["emails"] = self._send_action_item_emails(analysis.action_items)

        logger.info("Notification dispatch completed (mode=%s)", self._settings.notification_mode)
        return results

    def _send_webhook(self, analysis: MeetingAnalysis) -> dict[str, object]:
        payload = analysis.model_dump()
        url = "https://pheonixxx1211.app.n8n.cloud/webhook/meeting-actions"
        logger.info("Sending webhook notification to %s", url)
        try:
            with httpx.Client(timeout=self._settings.webhook_timeout_seconds) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("Webhook dispatch failed")
            raise NotificationError(f"Webhook dispatch failed: {exc}") from exc
        return {
            "status_code": response.status_code,
            "response_text": response.text[:500],
        }
        
    def _send_action_item_emails(self, action_items: list[ActionItem]) -> list[dict[str, object]]:
        """Send one email per action item to the resolved recipient."""
        if not action_items:
            logger.info("No action items to email")
            return []

        email_results: list[dict[str, object]] = []

        for item in action_items:
            try:
                self._send_single_email(item)
                email_results.append(
                    {
                        "recipient": item.resolved_email,
                        "task": item.task_description,
                        "status": "sent",
                    }
                )
            except Exception as exc:
                logger.exception("Failed to send email to %s", item.resolved_email)
                email_results.append(
                    {
                        "recipient": item.resolved_email,
                        "task": item.task_description,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        return email_results

    def _send_single_email(self, item: ActionItem) -> None:
        """Send a single SMTP email for one action item."""
        subject = f"[Meeting Action Item][{item.priority}] Task assigned to {item.detected_name}"
        body = (
            f"Hello {item.detected_name},\n\n"
            f"You have been assigned the following action item from a recent meeting:\n\n"
            f"Task: {item.task_description}\n"
            f"Priority: {item.priority}\n"
            f"Timeline: {item.timeline}\n\n"
            f"---\n"
            f"This message was generated automatically by the Meeting Intelligence Pipeline."
        )

        message = MIMEMultipart()
        message["From"] = self._settings.smtp_from_email
        message["To"] = item.resolved_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        logger.info("Sending SMTP email to %s", item.resolved_email)

        try:
            with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port) as server:
                if self._settings.smtp_use_tls:
                    server.starttls()
                if self._settings.smtp_username and self._settings.smtp_password:
                    server.login(self._settings.smtp_username, self._settings.smtp_password)
                server.send_message(message)
        except smtplib.SMTPException as exc:
            logger.exception("SMTP send failed for %s", item.resolved_email)
            raise NotificationError(f"SMTP send failed for {item.resolved_email}: {exc}") from exc

        logger.info("Email sent successfully to %s", item.resolved_email)
