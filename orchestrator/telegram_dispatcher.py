"""Passive outbound Telegram notification for dossiers awaiting human review."""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Mapping

import httpx


@dataclasses.dataclass(frozen=True)
class TelegramDispatchResult:
    status: str
    delivered: bool
    dry_run: bool
    reason: str
    message: str


class TelegramDispatcher:
    """Send bounded incident summaries to Telegram without accepting inbound commands."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        *,
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.bot_token = bot_token if bot_token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")
        self.timeout_seconds = timeout_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    @staticmethod
    def _text(value: Any, fallback: str = "Tidak tersedia", limit: int = 500) -> str:
        text = " ".join(str(value or fallback).split())
        return text[:limit]

    def format_message(self, dossier: Mapping[str, Any]) -> str:
        """Build an allowlisted summary; unknown and ground-truth fields are never traversed."""
        incident_id = self._text(dossier.get("incident_id"), "inc-unknown", 128)
        severity = self._text(dossier.get("severity"), "unknown", 32).upper()
        impact = dossier.get("impact_summary") if isinstance(dossier.get("impact_summary"), Mapping) else {}
        affected = impact.get("affected_services") or dossier.get("investigation_scope") or [dossier.get("service_id", "unknown")]
        if isinstance(affected, (list, tuple)):
            affected_text = ", ".join(self._text(item, "unknown", 80) for item in affected[:8])
        else:
            affected_text = self._text(affected, "unknown", 200)
        symptom = self._text(impact.get("observed_symptoms") or dossier.get("message"), limit=500)

        hypotheses = dossier.get("hypotheses")
        if not isinstance(hypotheses, list):
            root_cause = dossier.get("root_cause_analysis")
            root_cause = root_cause if isinstance(root_cause, Mapping) else {}
            hypotheses = root_cause.get("ranked_hypotheses", [])
        top = hypotheses[0] if hypotheses and isinstance(hypotheses[0], Mapping) else {}
        diagnosis = self._text(
            top.get("statement")
            or top.get("hypothesis_statement")
            or top.get("title")
            or top.get("description")
            or "Belum ada diagnosis yang didukung",
            limit=500,
        )
        confidence = top.get("confidence_score")
        confidence_text = f" ({float(confidence):.0%})" if isinstance(confidence, (int, float)) else ""

        citations = dossier.get("sop_citations")
        if not isinstance(citations, list):
            actions = dossier.get("recommended_actions")
            actions = actions if isinstance(actions, Mapping) else {}
            citations = actions.get("sop_citations", [])
        citation = citations[0] if citations and isinstance(citations[0], Mapping) else {}
        doc_id = self._text(citation.get("doc_id") or citation.get("document_id"), "Tidak ada sitasi aktif", 128)
        section = self._text(citation.get("section_path") or citation.get("section"), "bagian tidak tersedia", 160)

        return "\n".join(
            (
                f"SRE INCIDENT ALERT [{severity}]",
                f"Incident ID: {incident_id}",
                f"Affected: {affected_text}",
                f"Symptom: {symptom}",
                f"AI diagnosis: {diagnosis}{confidence_text}",
                f"Runbook SOP: {doc_id} | {section}",
                "Review di Unified SRE Command Center:",
                "python3 scripts/sre_dashboard.py",
                "Notification only. Tidak ada perintah Telegram yang diterima server.",
            )
        )

    def dispatch_pending_review(self, dossier: Mapping[str, Any]) -> TelegramDispatchResult:
        """Send only PENDING_REVIEW dossiers; missing credentials become a safe dry-run."""
        review = dossier.get("review_summary")
        review = review if isinstance(review, Mapping) else {}
        if review.get("status", "PENDING_REVIEW") != "PENDING_REVIEW":
            return TelegramDispatchResult(
                status="SKIPPED",
                delivered=False,
                dry_run=not self.configured,
                reason="DOSSIER_NOT_PENDING_REVIEW",
                message="",
            )

        message = self.format_message(dossier)
        if not self.configured:
            return TelegramDispatchResult(
                status="DRY_RUN",
                delivered=False,
                dry_run=True,
                reason="TELEGRAM_CREDENTIALS_NOT_CONFIGURED",
                message=message,
            )

        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message, "disable_web_page_preview": True}
        try:
            if self._client is not None:
                response = self._client.post(endpoint, json=payload, timeout=self.timeout_seconds)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(endpoint, json=payload)
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            return TelegramDispatchResult(
                status="FALLBACK",
                delivered=False,
                dry_run=False,
                reason=f"NETWORK_UNAVAILABLE:{type(exc).__name__}",
                message=message,
            )

        return TelegramDispatchResult(
            status="DELIVERED",
            delivered=True,
            dry_run=False,
            reason="OK",
            message=message,
        )
