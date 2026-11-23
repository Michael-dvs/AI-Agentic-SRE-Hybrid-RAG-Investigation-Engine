"""Live Alert Watcher & Agentic Investigation Bridge for SRE Simulation Lab.

Polls Prometheus `/api/v1/alerts`, deduplicates firing alerts with a bounded
cooldown, runs the 9-state `DeterministicInvestigator` using read-only live
telemetry adapters (Prometheus, Loki, Tempo), and persists dossiers into
`WorkflowStateStore` (`orchestrator_state.db`) so they appear in `sre_dashboard.py`.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Callable

import httpx

from gateway.adapters import LogsAdapter, MetricsAdapter, TracesAdapter
from gateway.audit import SecurityAuditLogger
from gateway.dispatcher import ToolDispatcher
from gateway.policy import PolicyGateway
from orchestrator.console_config import PROVIDER_PRESETS, EnvConfigManager
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.llm_investigator import LLMInvestigator, LLMRunLedger
from orchestrator.llm_provider import (
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OpenRouterProvider,
)
from orchestrator.resilience import ResilienceController
from orchestrator.state_machine import (
    InvestigationStateMachine,
    WorkflowStateStore,
    utc_now_z,
)
from orchestrator.telegram_dispatcher import TelegramDispatcher
from services.alert_intake.correlation import DependencyCorrelator


def _build_configured_llm_investigator(
    state_db: str = "orchestrator_state.db",
    env_manager: EnvConfigManager | None = None,
) -> LLMInvestigator | None:
    """Build LLMInvestigator from .env/environment when an API key is configured."""
    mgr = env_manager or EnvConfigManager()
    vals = mgr.read_all()
    provider_key = (vals.get("LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or "openrouter").strip().lower()
    preset = PROVIDER_PRESETS.get(provider_key, PROVIDER_PRESETS["custom"])
    key_env = preset["key_env"]
    api_key = (
        vals.get(key_env)
        or vals.get("OPENROUTER_API_KEY")
        or vals.get("LLM_API_KEY")
        or os.getenv(key_env)
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("LLM_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return None
    base_url = (
        vals.get("LLM_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or preset["base_url"]
        or OPENROUTER_BASE_URL
    ).strip()
    model = (
        vals.get("LLM_MODEL")
        or os.getenv("LLM_MODEL")
        or preset["default_model"]
        or OPENROUTER_MODEL
    ).strip()
    try:
        provider = OpenRouterProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_name=provider_key,
        )
        ledger = LLMRunLedger(state_db)
        audit = SecurityAuditLogger()
        return LLMInvestigator(provider=provider, ledger=ledger, audit=audit)
    except Exception:
        return None


def _map_priority(severity: str | None) -> str:
    sev = str(severity or "high").strip().lower()
    if sev in ("critical", "crit", "p1"):
        return "CRITICAL"
    if sev in ("high", "error", "p2"):
        return "HIGH"
    if sev in ("medium", "warn", "warning", "p3"):
        return "MEDIUM"
    return "LOW"


class LiveAlertWatcher:
    """Bridge live Prometheus alerts into `orchestrator_state.db` via `DeterministicInvestigator`."""

    def __init__(
        self,
        *,
        state_db: str | None = None,
        prometheus_url: str = "http://127.0.0.1:19090",
        loki_url: str = "http://127.0.0.1:13100",
        tempo_url: str = "http://127.0.0.1:13200",
        cooldown_sec: float = 60.0,
        alerts_client: Any = None,
        telemetry_client: Any = None,
        llm_investigator: LLMInvestigator | None = None,
        use_env_llm: bool = True,
        on_incident: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.state_db = state_db or os.getenv("SRE_STATE_DB", "orchestrator_state.db")
        self.prometheus_url = prometheus_url.rstrip("/")
        self.loki_url = loki_url.rstrip("/")
        self.tempo_url = tempo_url.rstrip("/")
        self.cooldown_sec = max(5.0, cooldown_sec)
        self._alerts_client = alerts_client
        self.on_incident = on_incident
        self._last_seen: dict[tuple[str, str], float] = {}

        self.store = WorkflowStateStore(self.state_db)
        self.state_machine = InvestigationStateMachine(store=self.store)

        metrics_adapter = MetricsAdapter(
            base_url=self.prometheus_url,
            client=telemetry_client,
        )
        logs_adapter = LogsAdapter(
            base_url=self.loki_url,
            client=telemetry_client,
        )
        traces_adapter = TracesAdapter(
            base_url=self.tempo_url,
            client=telemetry_client,
        )
        dispatcher = ToolDispatcher(
            metrics_adapter=metrics_adapter,
            logs_adapter=logs_adapter,
            traces_adapter=traces_adapter,
        )
        self.gateway = PolicyGateway(dispatcher=dispatcher)
        self.telegram = TelegramDispatcher()

        def _notify_telegram(dossier: dict[str, Any]) -> None:
            if self.telegram.configured:
                try:
                    self.telegram.notify_pending_review(dossier)
                except Exception:
                    pass

        resolved_llm = llm_investigator
        if resolved_llm is None and use_env_llm:
            resolved_llm = _build_configured_llm_investigator(state_db=self.state_db)

        self.investigator = DeterministicInvestigator(
            state_machine=self.state_machine,
            gateway=self.gateway,
            correlator=DependencyCorrelator(),
            resilience=ResilienceController(default_deadline_seconds=60.0, max_tool_calls=25),
            llm_investigator=resolved_llm,
            pending_review_notifier=_notify_telegram,
        )

    def _fetch_alerts(self) -> list[dict[str, Any]]:
        url = f"{self.prometheus_url}/api/v1/alerts"
        try:
            if self._alerts_client is not None:
                resp = self._alerts_client.get(url, timeout=3.0)
            else:
                with httpx.Client(timeout=3.0) as client:
                    resp = client.get(url)
            if resp.status_code == 200:
                payload = resp.json()
                alerts = payload.get("alerts", [])
                return alerts if isinstance(alerts, list) else []
        except Exception:
            pass
        return []

    def poll_once(self) -> list[dict[str, Any]]:
        """Poll Prometheus alerts once and investigate any new non-cooldown alerts."""
        alerts = self._fetch_alerts()
        if not alerts:
            return []

        now = time.monotonic()
        investigated: list[dict[str, Any]] = []

        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            service_id = str(alert.get("service_id") or alert.get("service.name") or "api-gateway")
            alert_type = str(alert.get("alert_type") or alert.get("error_code") or "SimAlert")
            dedup_key = (service_id, alert_type)

            last_ts = self._last_seen.get(dedup_key)
            if last_ts is not None and (now - last_ts) < self.cooldown_sec:
                continue

            self._last_seen[dedup_key] = now
            raw_alert_id = str(alert.get("alert_id") or "")
            digest = hashlib.sha256(
                f"{service_id}:{alert_type}:{raw_alert_id}:{int(time.time())}".encode("utf-8")
            ).hexdigest()[:10]
            incident_id = f"inc-live-{service_id}-{digest}"

            raw_event_time = str(alert.get("event_time") or alert.get("starts_at") or "").strip()
            if not raw_event_time:
                raw_event_time = utc_now_z()
            elif raw_event_time.endswith("+00:00"):
                raw_event_time = raw_event_time[:-6] + "Z"

            incident_input: dict[str, Any] = {
                "incident_id": incident_id,
                "service_id": service_id,
                "environment": str(alert.get("environment") or "lab"),
                "event_time": raw_event_time,
                "error_code": str(alert.get("error_code") or "ERR_OBSERVED_ALERT"),
                "message": str(
                    alert.get("summary")
                    or alert.get("message")
                    or f"Prometheus alert {alert_type} fired on {service_id}"
                ),
                "priority": _map_priority(alert.get("severity")),
            }
            if alert.get("trace_id"):
                incident_input["trace_id"] = str(alert["trace_id"])

            result = self.investigator.investigate_incident(incident_input)
            summary = {
                "incident_id": incident_id,
                "service_id": service_id,
                "alert_type": alert_type,
                "status": result.get("status"),
                "state": result.get("state") or result.get("status"),
            }
            investigated.append(summary)
            if self.on_incident is not None:
                self.on_incident(summary)

        return investigated
