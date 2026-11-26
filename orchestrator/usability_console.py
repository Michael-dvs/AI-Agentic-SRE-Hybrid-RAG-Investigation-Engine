"""Unified Rich terminal console for SRE incident triage, investigation inspection, and human review (C19, P2-06)."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import webbrowser
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlencode

try:
    import select
    import termios
    import tty

    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.panel import Panel
from rich.prompt import Prompt
from rich.segment import Segment
from rich.style import Style
from rich.table import Table
from rich.text import Text

from observability.audit_chain import AuditHashChain
from orchestrator.console_config import (
    PROVIDER_PRESETS,
    EnvConfigManager,
    ModelCatalogClient,
    TelegramConfigHelper,
    mask_secret,
)
from orchestrator.console_view_models import (
    ADMINISTRATIVE_CLOSURE_SHORT,
    ARCHIVED_LIFECYCLE_STATES,
    CALIBRATION_LIMITATION_NOTE,
    INTEGRITY_SEMANTICS_NOTE,
    REVIEW_ACTION_SEMANTICS,
    AuthoritativeSnapshotCoordinator,
    ConsoleDesignTokens,
    DashboardSnapshot,
    EvidenceItemVM,
    HypothesisItemVM,
    IncidentDetailVM,
    build_incident_detail_vm,
    compact_identifier,
    format_local_timestamp,
    sanitize_terminal_text,
    tokens_for_console,
)
from orchestrator.handover import HandoverExporter
from orchestrator.llm_provider import OPENROUTER_BASE_URL, OPENROUTER_MODEL
from orchestrator.review import (
    AuthorizedReviewManager,
    InvalidDossierError,
    ReviewError,
    ReviewStateConflictError,
    StaleDossierVersionError,
    UnauthorizedReviewerError,
    build_human_correction_payload,
)
from orchestrator.state_machine import WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher


ARCHIVE_STATES = {"CLOSED", "REJECTED", "MANUAL_TRIAGE_REQUIRED", "FAILED_SAFE", "CANCELLED", "LEARNED"}

MIN_TERMINAL_WIDTH = 68
MIN_TERMINAL_HEIGHT = 16

DETAIL_LENS_ORDER = ("all", "overview", "hypotheses", "evidence", "sop", "review")
DETAIL_LENS_LABELS = {
    "all": "All Sections",
    "overview": "Triage & Progress",
    "hypotheses": "Hypotheses",
    "evidence": "Evidence Lineage",
    "sop": "SOP & RAG",
    "review": "Review & Audit",
}


def _bounded_sanitized_excerpt(value: Any, *, limit: int = 240) -> str:
    """Sanitize and bound untrusted excerpt text for terminal display (SEC-03, INV-17)."""
    safe = sanitize_terminal_text(value, max_chars=0, empty_placeholder="")
    if not safe:
        return "Excerpt unavailable."
    if len(safe) <= limit:
        return safe
    return f"{safe[: max(1, limit - 3)].rstrip()}..."


def _format_incident_time(
    incident: Mapping[str, Any],
    dossier: Mapping[str, Any] | None,
    *,
    compact: bool = False,
) -> str:
    """Format incident timestamp into local HH:MM:SS (compact) or MM-DD HH:MM:SS."""
    dos = dossier or {}
    window = dos.get("incident_window") if isinstance(dos.get("incident_window"), Mapping) else {}
    raw_ts = (
        window.get("start")
        or dos.get("window_start")
        or dos.get("event_time")
        or dos.get("alert_received_at")
        or dos.get("created_at")
        or incident.get("created_at")
        or incident.get("updated_at")
    )
    return format_local_timestamp(raw_ts, compact=compact)


def build_grafana_incident_url(
    incident: Mapping[str, Any] | None,
    dossier: Mapping[str, Any],
    *,
    base_url: str | None = None,
) -> str:
    """Build a Grafana dashboard URL zoomed into the incident's anomaly time window."""
    resolved_base = (base_url or os.getenv("GRAFANA_URL", "http://127.0.0.1:13000")).rstrip("/")
    inc = incident or {}
    window = dossier.get("incident_window") if isinstance(dossier.get("incident_window"), Mapping) else {}
    raw_start = (
        window.get("start")
        or dossier.get("window_start")
        or dossier.get("event_time")
        or dossier.get("alert_received_at")
        or dossier.get("created_at")
        or inc.get("created_at")
    )
    raw_end = window.get("end") or dossier.get("window_end") or raw_start
    service_id = str(dossier.get("service_id") or inc.get("service_id") or "api-gateway")

    def _to_epoch_ms(raw_val: Any) -> int | None:
        if not raw_val or not isinstance(raw_val, str):
            return None
        try:
            cleaned = raw_val.strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            parsed = dt.datetime.fromisoformat(cleaned)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return int(parsed.timestamp() * 1000)
        except Exception:
            return None

    start_ms = _to_epoch_ms(raw_start)
    end_ms = _to_epoch_ms(raw_end)
    if start_ms is not None:
        pad_ms = 5 * 60 * 1000  # +/- 5 minutes around anomaly
        from_param: str | int = max(0, start_ms - pad_ms)
        to_param: str | int = (end_ms if end_ms is not None else start_ms) + pad_ms
    else:
        from_param = "now-15m"
        to_param = "now"

    query = urlencode(
        {
            "orgId": "1",
            "from": str(from_param),
            "to": str(to_param),
            "var-service_id": service_id,
        }
    )
    return f"{resolved_base}/d/sre-sim-overview-v1/sre-agentic-lab-red-metrics-logs-and-traces-overview?{query}"


class _ScrollableContent:
    """Slice any Rich renderable vertically to fit the terminal viewport."""

    def __init__(self, renderable: RenderableType, offset: int, max_lines: int, *, monochrome: bool = False) -> None:
        self.renderable = renderable
        self.offset = max(0, offset)
        self.max_lines = max(4, max_lines)
        self.monochrome = monochrome

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        lines = console.render_lines(self.renderable, options, pad=False, new_lines=True)
        total = len(lines)
        if total <= self.max_lines:
            for line in lines:
                yield from line
            return
        view_lines = max(2, self.max_lines - 1)
        max_off = max(0, total - view_lines)
        off = max(0, min(self.offset, max_off))
        for line in lines[off : off + view_lines]:
            yield from line
        scroll_style = Style(bold=True) if self.monochrome else Style(color="#38bdf8", bold=True)
        yield Segment(
            f"[Scroll: line {off + 1}-{min(total, off + view_lines)}/{total} | Up/Dn or PgUp/PgDn]\n",
            scroll_style,
        )


class DashboardViewport:
    """Resolve the dashboard layout against the current terminal size on every refresh."""

    def __init__(self, dashboard: "SREDashboard") -> None:
        self.dashboard = dashboard

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        yield self.dashboard.render(
            width=options.max_width,
            height=options.max_height,
        )


class DashboardRepository:
    """Read dossiers and authoritative incident state snapshots through WorkflowStateStore."""

    def __init__(self, store: WorkflowStateStore, *, probe_ttl_seconds: float = 10.0) -> None:
        self.store = store
        self.coordinator = AuthoritativeSnapshotCoordinator(store, probe_ttl_seconds=probe_ttl_seconds)

    def read_snapshot(
        self,
        *,
        reviewer_ref: str = "sre_reviewer",
        reviewer_role: str = "L2_SRE",
        reviewer_directory: Mapping[str, Any] | None = None,
        require_registered_reviewer: bool = False,
        require_authenticated_context: bool = False,
        generation: int | None = None,
    ) -> DashboardSnapshot:
        return self.coordinator.refresh(
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            reviewer_directory=reviewer_directory,
            require_registered_reviewer=require_registered_reviewer,
            require_authenticated_context=require_authenticated_context,
            generation=generation,
        )

    def active_dossiers(self) -> list[dict[str, Any]]:
        """Return pending HUMAN_REVIEW dossier records (backward-compatible contract)."""
        return self._dossiers_for_states({"HUMAN_REVIEW"}, pending_only=True)

    def archived_dossiers(self) -> list[dict[str, Any]]:
        """Return finalized dossier records (backward-compatible contract)."""
        return self._dossiers_for_states(set(ARCHIVED_LIFECYCLE_STATES), pending_only=False)

    def latest_dossier(self, incident_id: str) -> dict[str, Any] | None:
        record = self.store.get_dossier(incident_id)
        return record["dossier_json"] if record else None

    def _dossiers_for_states(
        self,
        states: set[str],
        *,
        pending_only: bool,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self.store.transaction(immediate=False):
            incidents = self.store.list_incidents(current_states=states)
            for incident in incidents:
                dossier = self.latest_dossier(incident["incident_id"])
                if not dossier:
                    continue
                status = dossier.get("review_summary", {}).get("status", "PENDING_REVIEW")
                if pending_only and status not in ("PENDING_REVIEW", "MANUAL_TRIAGE"):
                    continue
                records.append({"incident": incident, "dossier": dossier})
        return records


class ReviewActionController:
    """Apply review-only state changes with persistent audit and clean handover export."""

    def __init__(
        self,
        store: WorkflowStateStore,
        *,
        audit_path: pathlib.Path | str = "artifacts/audit/c19-review-audit.jsonl",
        handover_root: pathlib.Path | str = "artifacts/handover",
        reviewer_directory: Mapping[str, Any] | None = None,
        require_registered_reviewer: bool = False,
        require_authenticated_context: bool = False,
    ) -> None:
        self.audit_chain = AuditHashChain(log_path=audit_path)
        self.review_manager = AuthorizedReviewManager(
            store=store,
            audit_chain=self.audit_chain,
            reviewer_directory=reviewer_directory,
            require_registered_reviewer=require_registered_reviewer,
            require_authenticated_context=require_authenticated_context,
        )
        self.exporter = HandoverExporter(export_root=handover_root)

    def apply(
        self,
        dossier: dict[str, Any],
        action: str,
        *,
        reviewer_ref: str,
        reviewer_role: str,
        rationale: str,
        corrected_hypothesis: str | None = None,
        escalation_target: str | None = None,
        target_version: int | None = None,
        auth_context: Any = None,
    ) -> dict[str, Any]:
        action_upper = action.upper()
        corrections = None
        if action_upper == "CORRECT":
            statement = " ".join((corrected_hypothesis or "").split())
            if not statement:
                raise InvalidDossierError("Corrected hypothesis statement is required.")
            corrections = build_human_correction_payload(
                dossier=dossier,
                corrected_statement=statement,
                reviewer_ref=reviewer_ref,
                reviewer_role=reviewer_role,
            )

        effective_version = (
            int(target_version)
            if isinstance(target_version, int) and not isinstance(target_version, bool)
            else int(dossier.get("dossier_version", 1))
        )
        result = self.review_manager.submit_review(
            incident_id=str(dossier.get("incident_id", "inc-unknown")),
            dossier_dict=dossier,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            decision=action_upper,
            rationale=rationale,
            edited_dossier_data=corrections,
            escalation_target=escalation_target,
            target_version=effective_version,
            auth_context=auth_context,
        )
        artifacts: dict[str, str] = {}
        if action_upper == "APPROVE":
            incident_id = str(dossier.get("incident_id", "inc-unknown"))
            paths = self.exporter.export_handover_package(
                incident_id=incident_id,
                dossier_dict=result["updated_dossier"],
                review_history=self.review_manager.get_review_history(incident_id),
            )
            artifacts = {name: str(path) for name, path in paths.items()}

        return {
            "action": action_upper,
            "review_result": result,
            "approval_semantics": result.get("approval_semantics"),
            "authorization_context": result.get("authorization_context"),
            "artifacts": artifacts,
            "auto_action_triggered": result["review_event"]["auto_action_triggered"],
        }


class ServiceHealthInspector:
    """Perform a fixed, read-only Docker Compose status inspection."""

    def __init__(self, command: Sequence[str] | None = None) -> None:
        self.command = tuple(command or ("docker", "compose", "ps", "--format", "json"))

    def inspect(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                self.command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "UNAVAILABLE", "reason": type(exc).__name__, "services": []}
        if result.returncode != 0:
            return {
                "status": "UNAVAILABLE",
                "reason": sanitize_terminal_text(result.stderr.strip(), max_chars=240, empty_placeholder="Docker unavailable"),
                "services": [],
            }

        raw = result.stdout.strip()
        if not raw:
            return {"status": "EMPTY", "reason": "No Compose containers are running", "services": []}
        try:
            parsed = json.loads(raw)
            rows = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            try:
                rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            except json.JSONDecodeError:
                return {"status": "UNAVAILABLE", "reason": "Invalid Docker status response", "services": []}

        services = [
            {
                "name": sanitize_terminal_text(row.get("Service") or row.get("Name", "unknown"), max_chars=64),
                "state": sanitize_terminal_text(row.get("State", "unknown"), max_chars=32),
                "health": sanitize_terminal_text(row.get("Health", "not-reported"), max_chars=32),
            }
            for row in rows
            if isinstance(row, Mapping)
        ]
        return {"status": "OK", "reason": "", "services": services}


class CostMetricsReader:
    """Read the C15 aggregate export without inventing operational values."""

    def __init__(self, path: pathlib.Path | str | None = None) -> None:
        configured = path or os.getenv("C15_USAGE_METRICS_PATH", "artifacts/observability/usage-cost-metrics.json")
        self.path = pathlib.Path(configured)

    def read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"status": "UNAVAILABLE", "source": str(self.path)}
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "ERROR", "source": str(self.path), "reason": type(exc).__name__}
        return {"status": "OK", "source": str(self.path), "metrics": payload}


class SREDashboard:
    """Render and operate the keyboard-driven SRE Investigation & Human Review Console."""

    _MENU_ORDER = ("active", "archive", "health", "model", "telegram")

    def __init__(
        self,
        store: WorkflowStateStore,
        *,
        console: Console | None = None,
        reviewer_ref: str = "sre_reviewer",
        reviewer_role: str = "L2_SRE",
        audit_path: pathlib.Path | str = "artifacts/audit/c19-review-audit.jsonl",
        handover_root: pathlib.Path | str = "artifacts/handover",
        telegram: TelegramDispatcher | None = None,
        health: ServiceHealthInspector | None = None,
        costs: CostMetricsReader | None = None,
        env_manager: EnvConfigManager | None = None,
        model_catalog: ModelCatalogClient | None = None,
        telegram_helper: TelegramConfigHelper | None = None,
        reviewer_directory: Mapping[str, Any] | None = None,
        require_registered_reviewer: bool = False,
        require_authenticated_context: bool = False,
        auth_context: Any = None,
        ascii_mode: bool | None = None,
        probe_ttl_seconds: float = 10.0,
    ) -> None:
        self.store = store
        self.console = console or Console()
        self.reviewer_ref = reviewer_ref
        self.reviewer_role = reviewer_role
        self.reviewer_directory = reviewer_directory
        self.require_registered_reviewer = require_registered_reviewer
        self.require_authenticated_context = require_authenticated_context
        self.auth_context = auth_context

        ascii_env = os.getenv("SRE_CONSOLE_ASCII", "").strip().lower() in ("1", "true", "yes")
        self.ascii_mode = bool(ascii_mode) if ascii_mode is not None else ascii_env

        self.repository = DashboardRepository(store, probe_ttl_seconds=probe_ttl_seconds)
        self.actions = ReviewActionController(
            store,
            audit_path=audit_path,
            handover_root=handover_root,
            reviewer_directory=reviewer_directory,
            require_registered_reviewer=require_registered_reviewer,
            require_authenticated_context=require_authenticated_context,
        )
        self.env_manager = env_manager or EnvConfigManager()
        self.model_catalog = model_catalog or ModelCatalogClient()
        self.telegram_helper = telegram_helper or TelegramConfigHelper()
        if telegram is not None:
            self.telegram = telegram
        else:
            env_vals = self.env_manager.read_all()
            self.telegram = TelegramDispatcher(
                bot_token=env_vals.get("TELEGRAM_BOT_TOKEN", ""),
                chat_id=env_vals.get("TELEGRAM_CHAT_ID", ""),
            )
        self.health = health or ServiceHealthInspector()
        self.costs = costs or CostMetricsReader()

        # View State (strictly separated from persisted domain state — Work Package E2)
        self.view = "active"
        self.focus = "menu"  # "menu" | "list"
        self.selected_incident_id: str | None = None
        self.highlighted_incident_id: str | None = None
        self.selected_index: int = 0
        self._last_synced_index: int = 0
        self.list_scroll_offset: int = 0
        self.detail_scroll_offset: int = 0

        # Detail sub-navigation & reference resolution state (Work Package D1, I5)
        self.detail_section: str = "all"  # one of DETAIL_LENS_ORDER
        self.detail_return_stack: list[tuple[str, int]] = []
        self.selected_hypothesis_idx: int = 0
        self.selected_evidence_idx: int = 0
        self.viewed_dossier_version: int = 0
        self.viewed_dossier_hash: str = ""

        # Transient Operation & Modal State (never persisted into domain workflow)
        self.initial_loading: bool = False
        self.refresh_in_progress: bool = False
        self.help_open: bool = False
        self.review_modal: dict[str, Any] | None = None
        self.unsent_review_draft: dict[str, str] = {}
        self._skip_next_render_refresh: bool = False
        self._saved_termios: list[Any] | None = None
        self._tty_fd: int | None = None
        self._pending_byte: bytes | None = None

        self._screen: Any = None
        self.fetched_models: list[str] = []
        self.last_model_check: str = "Untested"
        self.last_telegram_check: str = "Untested"
        self.notice = "Navigation: [Up/Dn] switch menu, [Right/Enter/Tab] focus incident list, [?] help."

    # ------------------------------------------------------------------
    # Glyph & Box Helpers (ASCII fallback for limited fonts/terminals)
    # ------------------------------------------------------------------

    def _tokens(self) -> ConsoleDesignTokens:
        return tokens_for_console(self.console)

    def _panel_box(self) -> box.Box:
        return box.ASCII if self.ascii_mode else box.SQUARE

    def _table_box(self) -> box.Box:
        return box.ASCII if self.ascii_mode else box.SIMPLE_HEAD

    def _sel_glyph(self) -> str:
        return ">" if self.ascii_mode else "▶"

    # ------------------------------------------------------------------
    # Authoritative Snapshot & Stable Selection Synchronization
    # ------------------------------------------------------------------

    def refresh_snapshot(self, *, generation: int | None = None, force_probes: bool = False) -> DashboardSnapshot:
        """Read an atomic snapshot from WorkflowStateStore and reconcile selection safely."""
        self.refresh_in_progress = True
        try:
            snap = self.repository.read_snapshot(
                reviewer_ref=self.reviewer_ref,
                reviewer_role=self.reviewer_role,
                reviewer_directory=self.reviewer_directory,
                require_registered_reviewer=self.require_registered_reviewer,
                require_authenticated_context=self.require_authenticated_context,
                generation=generation,
            )
            if force_probes:
                if self.view == "health":
                    self.repository.coordinator.get_cached_health(self.health.inspect, force=True)
                elif self.view == "model":
                    self.repository.coordinator.get_cached_costs(self.costs.read, force=True)
            self._reconcile_view_with_snapshot(snap)
            return snap
        finally:
            self.refresh_in_progress = False
            self.initial_loading = False

    def apply_async_snapshot(self, snapshot: DashboardSnapshot, *, expected_incident_id: str | None = None) -> bool:
        """Apply an async refresh result only if its generation is current and target still matches."""
        if expected_incident_id is not None and self.selected_incident_id != expected_incident_id:
            # Operator switched incidents while async load was in flight (A08): update cache only if newer,
            # without clobbering current selection or scroll offsets.
            return self.repository.coordinator.apply_external_snapshot(snapshot)
        accepted = self.repository.coordinator.apply_external_snapshot(snapshot)
        if accepted:
            self._reconcile_view_with_snapshot(snapshot)
        return accepted

    def _entries_for_current_tab(self, snapshot: DashboardSnapshot) -> Sequence[IncidentDetailVM]:
        if self.view == "archive":
            return snapshot.archived_entries
        return snapshot.active_entries

    def _reconcile_view_with_snapshot(self, snapshot: DashboardSnapshot) -> None:
        """Keep incident selection stable by ID across insertions, state transitions, and revisions."""
        if self.view in ("active", "archive"):
            rows = self._entries_for_current_tab(snapshot)
            if not rows:
                self.selected_index = 0
                self._last_synced_index = 0
                self.list_scroll_offset = 0
                self.highlighted_incident_id = None
            else:
                # Honor explicit programmatic or keyboard changes to selected_index first
                if self.selected_index != self._last_synced_index:
                    clamped = max(0, min(self.selected_index, len(rows) - 1))
                    self.selected_index = clamped
                    self._last_synced_index = clamped
                    self.highlighted_incident_id = rows[clamped].incident_id
                elif self.highlighted_incident_id:
                    found_idx = next(
                        (i for i, item in enumerate(rows) if item.incident_id == self.highlighted_incident_id),
                        None,
                    )
                    if found_idx is not None:
                        self.selected_index = found_idx
                        self._last_synced_index = found_idx
                    else:
                        # Highlighted incident moved to Archive or was removed
                        moved_vm = snapshot.by_incident_id.get(self.highlighted_incident_id)
                        clamped = max(0, min(self.selected_index, len(rows) - 1))
                        self.selected_index = clamped
                        self._last_synced_index = clamped
                        old_id = self.highlighted_incident_id
                        self.highlighted_incident_id = rows[clamped].incident_id
                        if moved_vm and self.view == "active" and not self.selected_incident_id:
                            self.notice = (
                                f"Incident {old_id} transitioned to {moved_vm.lifecycle_state} (available in [2] Archive)."
                            )
                else:
                    clamped = max(0, min(self.selected_index, len(rows) - 1))
                    self.selected_index = clamped
                    self._last_synced_index = clamped
                    self.highlighted_incident_id = rows[clamped].incident_id

        # Reconcile open detail view & active review modal if another process modified the incident
        if self.selected_incident_id:
            detail_vm = snapshot.by_incident_id.get(self.selected_incident_id)
            if detail_vm is not None:
                if self.review_modal is not None and self.review_modal.get("incident_id") == detail_vm.incident_id:
                    target_ver = self.review_modal.get("target_version")
                    if not detail_vm.review_eligibility.eligible:
                        # Concurrent process finalized the incident while modal was open (Scenario O8)
                        self._preserve_unsent_modal_draft()
                        self.review_modal = None
                        self.viewed_dossier_version = detail_vm.dossier_version
                        self.viewed_dossier_hash = detail_vm.dossier_hash
                        self.notice = (
                            f"[REVIEW CONFLICT] Incident finalized concurrently ({detail_vm.lifecycle_state}); "
                            "review controls are now locked."
                        )
                    elif detail_vm.dossier_version != target_ver:
                        self._preserve_unsent_modal_draft()
                        self.review_modal = None
                        self.viewed_dossier_version = detail_vm.dossier_version
                        self.viewed_dossier_hash = detail_vm.dossier_hash
                        self.notice = (
                            f"[REVISION UPDATED] Dossier advanced from v{target_ver} to v{detail_vm.dossier_version}; "
                            "reloaded latest revision (draft rationale preserved)."
                        )
                else:
                    if (
                        self.viewed_dossier_version
                        and detail_vm.dossier_version
                        and detail_vm.dossier_version != self.viewed_dossier_version
                    ):
                        self.notice = (
                            f"Reloaded newer dossier revision v{detail_vm.dossier_version} "
                            f"(previously viewing v{self.viewed_dossier_version})."
                        )
                    self.viewed_dossier_version = detail_vm.dossier_version
                    self.viewed_dossier_hash = detail_vm.dossier_hash

    def _preserve_unsent_modal_draft(self) -> None:
        if not self.review_modal:
            return
        inc_id = str(self.review_modal.get("incident_id") or "")
        rat = str(self.review_modal.get("rationale") or "").strip()
        if inc_id and rat:
            self.unsent_review_draft[inc_id] = rat

    # ------------------------------------------------------------------
    # Top-Level Render Entrypoint
    # ------------------------------------------------------------------

    def render(self, *, width: int | None = None, height: int | None = None) -> RenderableType:
        tokens = self._tokens()
        pbox = self._panel_box()
        terminal_width = width or self.console.size.width

        # Minimum size guard only when explicit viewport dims are smaller than usable threshold (Work Package L1, E10)
        if terminal_width < MIN_TERMINAL_WIDTH or (height is not None and height < MIN_TERMINAL_HEIGHT):
            cur_h = height if height is not None else self.console.size.height
            msg = Text()
            msg.append("TERMINAL VIEWPORT BELOW MINIMUM SUPPORTED SIZE\n", style=tokens.warning)
            msg.append(
                f"Current: {terminal_width} cols x {cur_h} rows | Minimum: {MIN_TERMINAL_WIDTH} cols x {MIN_TERMINAL_HEIGHT} rows.\n",
                style=tokens.primary,
            )
            msg.append(
                "Enlarge the terminal window to resume inspection. Selection, focus, and unsent review drafts are preserved.\n"
                "Controls: [B/Esc] Back | [Q] Quit",
                style=tokens.secondary,
            )
            return Panel(msg, title="SRE Console - Resize Required", border_style=tokens.border_modal, box=pbox)

        if self.initial_loading and self.repository.coordinator.current_snapshot is None:
            loading_txt = Text()
            loading_txt.append("[LOADING] Reading authoritative state store snapshot...\n", style=tokens.accent)
            loading_txt.append(
                "Source: WorkflowStateStore SQLite (read-only transaction). Press [Q] to exit.",
                style=tokens.secondary,
            )
            return Panel(loading_txt, title="SRE Investigation Console", border_style=tokens.border_focused, box=pbox)

        if self._skip_next_render_refresh and self.repository.coordinator.current_snapshot is not None:
            self._skip_next_render_refresh = False
            snapshot = self.repository.coordinator.current_snapshot
        else:
            self._skip_next_render_refresh = False
            snapshot = self.refresh_snapshot()

        # Overlay Modals (Help or Two-Step Human Review Confirmation)
        if self.help_open:
            return self._render_help_modal(snapshot, width=terminal_width, height=height)
        if self.review_modal is not None:
            return self._render_review_modal(snapshot, width=terminal_width, height=height)

        menu_focused = self.focus == "menu" and not self.selected_incident_id
        nav_title = "Navigation [FOCUSED]" if menu_focused else "Navigation"
        nav_border = tokens.border_focused if menu_focused else tokens.border_inactive
        main_title = f"{self._main_title()} [FOCUSED]" if not menu_focused else self._main_title()
        main_border = tokens.border_focused if not menu_focused else tokens.border_inactive

        is_narrow = terminal_width < 100
        nav_col_width = 28
        content_width = max(44, terminal_width - 4) if is_narrow else max(60, terminal_width - nav_col_width - 4)
        show_status_strip = height is None or height >= 22
        status_strip = self._global_status_strip(snapshot, compact=(terminal_width < 105))

        main_height: int | None = None
        if height is not None:
            # Preserve exact pagination math on ultra-short 72x18 viewports while fitting status strip on >=22
            reserved_lines = (14 if show_status_strip else 12) if is_narrow else (10 if show_status_strip else 8)
            main_height = max(6, height - reserved_lines)

        main = Panel(
            self._main_content(snapshot=snapshot, width=content_width, max_height=main_height),
            title=main_title,
            border_style=main_border,
            box=pbox,
        )
        actions = Panel(
            self._action_bar(snapshot),
            title="Review Action Bar",
            border_style=tokens.border_modal if (self.selected_incident_id or snapshot.is_stale_last_known) else tokens.border_inactive,
            box=pbox,
        )

        blocks: list[RenderableType] = []
        if show_status_strip:
            blocks.append(status_strip)

        if is_narrow:
            navigation = Panel(self._navigation_compact(width=terminal_width), title=nav_title, border_style=nav_border, box=pbox)
            blocks.extend([navigation, main, actions])
            return Group(*blocks)

        navigation = Panel(self._navigation(snapshot), title=nav_title, border_style=nav_border, box=pbox)
        two_panel = Table.grid(expand=True)
        two_panel.add_column(width=nav_col_width)
        two_panel.add_column(ratio=1)
        two_panel.add_row(navigation, main)
        blocks.extend([two_panel, actions])
        return Group(*blocks)

    # ------------------------------------------------------------------
    # Global Status Strip & Navigation Sidebar (Work Package B1, D1)
    # ------------------------------------------------------------------

    def _global_status_strip(self, snapshot: DashboardSnapshot, *, compact: bool = False) -> RenderableType:
        tokens = self._tokens()
        cfg = self._current_llm_config()
        llm_mode_str = (
            f"LLM:{cfg['provider_key']}/{compact_identifier(cfg['model'], max_cells=22)}"
            if cfg["api_key"]
            else "Mode:Offline-Deterministic($0)"
        )
        cached_health = self.repository.coordinator.peek_cached_health()
        if cached_health is None:
            svc_str = "Lab:unprobed([3])"
            svc_style = tokens.muted
        elif cached_health.get("status") == "OK":
            svcs = cached_health.get("services") or []
            healthy_n = sum(
                1 for s in svcs
                if str(s.get("state", "")).lower() == "running"
                and str(s.get("health", "")).lower() in ("healthy", "not-reported", "")
            )
            svc_str = f"Lab:{healthy_n}/{len(svcs)} up"
            svc_style = tokens.infra_healthy if healthy_n == len(svcs) and svcs else tokens.warning
        else:
            svc_str = f"Lab:{cached_health.get('status', 'DEGRADED')}"
            svc_style = tokens.warning

        line = Text()
        line.append("SRE INVESTIGATION CONSOLE ", style=tokens.primary_bold)
        if snapshot.is_stale_last_known:
            line.append(
                f"[STALE LAST-KNOWN DATA | sync failed: {snapshot.refresh_error} | last ok {snapshot.fetched_at_local}] ",
                style=tokens.critical,
            )
        elif not snapshot.store_connected and snapshot.refresh_error:
            line.append(f"[STORE ERROR: {snapshot.refresh_error}] ", style=tokens.critical)
        else:
            line.append(f"[Store:CONNECTED@{snapshot.fetched_at_local}] ", style=tokens.secondary)

        env_label = ",".join(snapshot.environments[:2])
        line.append(
            f"Env:{env_label} | ReviewQueue:{snapshot.awaiting_review_count} | "
            f"Running:{snapshot.in_progress_count} | Archive:{snapshot.archived_count} | ",
            style=tokens.primary,
        )
        line.append(svc_str, style=svc_style)
        if not compact:
            line.append(f" | {llm_mode_str} | Reviewer:{self.reviewer_ref}({self.reviewer_role}) [?]Help", style=tokens.secondary)
        return line

    def _navigation_compact(self, *, width: int = 80) -> Text:
        tokens = self._tokens()
        selected = {
            "active": "1",
            "archive": "2",
            "health": "3",
            "model": "4",
            "telegram": "5",
        }.get(self.view)
        text = Text()
        sep = " " if width < 92 else "  "
        items = (
            ("1", "Active"),
            ("2", "Archive"),
            ("3", "Health"),
            ("4", "Model"),
            ("5", "Telegram"),
            ("?", "Help"),
            ("Q", "Quit"),
        )
        for idx, (key, label) in enumerate(items):
            style = tokens.selected_nav if key == selected else (tokens.primary_bold if key in ("Q", "?") else tokens.secondary)
            if idx > 0:
                text.append(sep)
            text.append(f"[{key}] {label}", style=style)
        return text

    def _navigation(self, snapshot: DashboardSnapshot | None = None) -> Text:
        tokens = self._tokens()
        selected = {
            "active": "1",
            "archive": "2",
            "health": "3",
            "model": "4",
            "telegram": "5",
        }.get(self.view)
        act_cnt = len(snapshot.active_entries) if snapshot else 0
        arc_cnt = len(snapshot.archived_entries) if snapshot else 0
        text = Text()
        for key, label, badge in (
            ("1", "Active Incidents", f"[{act_cnt}]" if snapshot is not None else ""),
            ("2", "Archive Dossiers", f"[{arc_cnt}]" if snapshot is not None else ""),
            ("3", "Service Health", ""),
            ("4", "AI Model Config", ""),
            ("5", "Telegram Alerts", ""),
            ("?", "Keyboard & Guide", ""),
            ("Q", "Quit Console", ""),
        ):
            style = tokens.selected_nav if key == selected else (tokens.primary_bold if key == "Q" else tokens.primary)
            suffix = f" {badge}" if badge else ""
            text.append(f"[{key}] {label}{suffix}\n", style=style)
        return text

    def _main_title(self) -> str:
        base = {
            "active": "Active Incidents",
            "archive": "Archive Dossiers",
            "health": "Synthetic Service Health",
            "model": "AI Model and C15 Cost Metrics",
            "telegram": "Telegram Dispatcher",
        }[self.view]
        if self.selected_incident_id and self.view in ("active", "archive"):
            lens_name = DETAIL_LENS_LABELS.get(self.detail_section, "All Sections")
            return f"{base} > {compact_identifier(self.selected_incident_id, max_cells=32)} [{lens_name}]"
        return base

    # ------------------------------------------------------------------
    # Main Content Router
    # ------------------------------------------------------------------

    def _main_content(
        self,
        *,
        snapshot: DashboardSnapshot | None = None,
        width: int = 120,
        max_height: int | None = None,
    ) -> RenderableType:
        tokens = self._tokens()
        snap = snapshot or self.refresh_snapshot()

        def _maybe_scroll(content: RenderableType) -> RenderableType:
            if max_height is None:
                return content
            return _ScrollableContent(
                content,
                offset=self.detail_scroll_offset,
                max_lines=max(6, max_height),
                monochrome=tokens.monochrome,
            )

        if self.view in {"active", "archive"}:
            if self.selected_incident_id:
                detail_vm = snap.by_incident_id.get(self.selected_incident_id)
                if detail_vm is not None:
                    self.viewed_dossier_version = detail_vm.dossier_version
                    self.viewed_dossier_hash = detail_vm.dossier_hash
                    return _maybe_scroll(self._render_incident_detail_vm(detail_vm, width=width))
                # Fallback if dossier exists without incident row
                dossier = self.repository.latest_dossier(self.selected_incident_id)
                if dossier:
                    return _maybe_scroll(self._dossier_detail(dossier, width=width))
                missing_txt = Text()
                missing_txt.append(
                    f"Incident '{sanitize_terminal_text(self.selected_incident_id, max_chars=80)}' is not present in the state store.\n",
                    style=tokens.warning,
                )
                missing_txt.append("Press [B] or [Esc] to return to the incident overview.", style=tokens.secondary)
                return missing_txt

            rows = self._entries_for_current_tab(snap)
            return self._incident_table(rows, snapshot=snap, width=width, max_height=max_height)

        if self.view == "health":
            health_snap = self.repository.coordinator.get_cached_health(self.health.inspect)
            return _maybe_scroll(self._health_table(health_snap))

        if self.view == "model":
            all_entries = list(snap.active_entries) + list(snap.archived_entries)
            active_model = all_entries[0].model_version if all_entries else "N/A"
            cost_snap = self.repository.coordinator.get_cached_costs(self.costs.read)
            return _maybe_scroll(self._model_panel(cost_snap, active_model))

        return _maybe_scroll(self._telegram_panel())

    # ------------------------------------------------------------------
    # Incident Overview Table (Work Package B2)
    # ------------------------------------------------------------------

    def _incident_table(
        self,
        rows: Sequence[IncidentDetailVM],
        *,
        snapshot: DashboardSnapshot | None = None,
        width: int = 120,
        max_height: int | None = None,
    ) -> RenderableType:
        tokens = self._tokens()
        if snapshot is not None and not snapshot.store_connected and not rows:
            err_txt = Text()
            err_txt.append(f"[BACKEND ERROR] Failed to query WorkflowStateStore: {snapshot.refresh_error}\n", style=tokens.critical)
            err_txt.append("Next step: verify SQLite file permissions or press [U] to retry refresh.", style=tokens.secondary)
            return err_txt

        if not rows:
            empty_txt = Text()
            if self.view == "active":
                empty_txt.append("No active investigations or dossiers pending review.\n", style=tokens.primary_bold)
                empty_txt.append(
                    "Cause: zero incidents are currently in RECEIVED..HUMAN_REVIEW states.\n"
                    "Next action: press [2] to inspect Archive Dossiers, [U] to refresh, or trigger a synthetic scenario.",
                    style=tokens.secondary,
                )
            else:
                empty_txt.append("No archived dossiers recorded yet.\n", style=tokens.primary_bold)
                empty_txt.append(
                    "Cause: no incidents have reached CLOSED, REJECTED, ESCALATED, or FAILED_SAFE states.\n"
                    "Next action: press [1] to inspect Active Incidents or [B] to return.",
                    style=tokens.secondary,
                )
            return empty_txt

        if self.selected_index >= len(rows):
            self.selected_index = max(0, len(rows) - 1)
        elif self.selected_index < 0:
            self.selected_index = 0
        self._last_synced_index = self.selected_index
        self.highlighted_incident_id = rows[self.selected_index].incident_id

        if max_height is not None:
            reserve_footer = 5 if max_height < 12 else 6
            max_visible = max(3, max_height - reserve_footer)
            if self.selected_index < self.list_scroll_offset:
                self.list_scroll_offset = self.selected_index
            elif self.selected_index >= self.list_scroll_offset + max_visible:
                self.list_scroll_offset = self.selected_index - max_visible + 1
            max_offset = max(0, len(rows) - max_visible)
            self.list_scroll_offset = max(0, min(self.list_scroll_offset, max_offset))
            visible_slice = rows[self.list_scroll_offset : self.list_scroll_offset + max_visible]
        else:
            max_visible = len(rows)
            self.list_scroll_offset = 0
            visible_slice = rows

        is_compact = width < 80
        is_wide = width >= 114
        show_mode_col = width >= 74
        show_symptom_col = width >= 118

        table = Table(expand=True, box=self._table_box(), pad_edge=False, padding=(0, 1), collapse_padding=True)
        table.add_column("No.", justify="right", width=4, no_wrap=True)
        table.add_column("Time", width=8 if is_compact else 11, no_wrap=True)
        table.add_column("Incident", ratio=4, no_wrap=True, overflow="ellipsis")
        table.add_column("Sev", width=4 if is_compact else 6, no_wrap=True)
        table.add_column("Service", ratio=2, no_wrap=True, overflow="ellipsis")
        if show_mode_col:
            table.add_column("Mode", width=8, no_wrap=True)
        if not is_compact:
            table.add_column("State", width=12, no_wrap=True)
        if show_symptom_col:
            table.add_column("Observed Symptom", ratio=3, no_wrap=True, overflow="ellipsis")

        sel_mark = self._sel_glyph()
        id_budget = 24 if is_compact else (38 if is_wide else 30)
        svc_budget = 16 if is_compact else (22 if is_wide else 19)
        sym_budget = 38 if is_wide else 24
        compact_sev_map = {
            "CRITICAL": "CRIT",
            "HIGH": "HIGH",
            "MEDIUM": "MED",
            "LOW": "LOW",
            "UNKNOWN": "UNK",
        }

        for offset_idx, vm in enumerate(visible_slice):
            actual_idx = self.list_scroll_offset + offset_idx
            is_sel = actual_idx == self.selected_index
            no_str = f"{sel_mark} {actual_idx + 1}" if is_sel else f"  {actual_idx + 1}"
            time_str = vm.incident_time_compact if is_compact else vm.incident_time_display[:11]
            inc_cell = compact_identifier(vm.incident_id, max_cells=id_budget)
            sev_label = compact_sev_map.get(vm.severity, "UNK") if is_compact else vm.severity_badge.split(" ")[0]
            sev_cell = Text(
                sev_label,
                style=tokens.selected_row if is_sel else tokens.severity_style(vm.severity),
            )
            svc_cell = compact_identifier(vm.primary_service, max_cells=svc_budget)

            if vm.lifecycle_state == "MANUAL_TRIAGE_REQUIRED":
                state_cell_txt = "ESCALATED"
            elif vm.lifecycle_state == "HUMAN_REVIEW" and vm.review_eligibility.eligible:
                state_cell_txt = "NEEDS_REVIEW"
            elif vm.lifecycle_state == "CLOSED":
                state_cell_txt = "CLOSED(Adm)"
            elif "[Running " in vm.lifecycle_display:
                stage_part = vm.lifecycle_display.split("[Running ", 1)[1].rstrip("]")
                state_cell_txt = f"RUNNING({stage_part})"
            else:
                state_cell_txt = vm.lifecycle_display[:12]

            row_style = tokens.selected_row if is_sel else tokens.primary
            cells: list[RenderableType] = [no_str, time_str, inc_cell, sev_cell, svc_cell]
            if show_mode_col:
                cells.append(vm.mode_badge)
            if not is_compact:
                cells.append(state_cell_txt)
            if show_symptom_col:
                cells.append(sanitize_terminal_text(vm.observed_symptoms, max_chars=sym_budget))
            table.add_row(*cells, style=row_style)

        sel_vm = rows[self.selected_index]
        footer_items: list[RenderableType] = [table]
        if (max_height is None or max_height >= 12) and not show_symptom_col:
            preview = Text()
            preview.append("Selected Symptom: ", style=tokens.secondary)
            preview.append(
                sanitize_terminal_text(sel_vm.observed_symptoms, max_chars=max(36, width - 20)),
                style=tokens.primary,
            )
            footer_items.append(preview)

        hint_parts = [
            "Keys: [Up/Dn or j/k] Select",
            "[Enter/O] Inspect",
            "[G] Grafana",
            "[U] Refresh",
            "[?] Help",
        ]
        if len(rows) > max_visible:
            start_num = self.list_scroll_offset + 1
            end_num = self.list_scroll_offset + len(visible_slice)
            hint_parts.append(f"Showing {start_num}-{end_num} of {len(rows)}")
        footer_items.append(Text("  |  ".join(hint_parts), style=tokens.secondary))
        return Group(*footer_items)

    # ------------------------------------------------------------------
    # Incident Detail Rendering (Backward-Compatible _dossier_detail + Lens Views)
    # ------------------------------------------------------------------

    def _dossier_detail(self, dossier: Mapping[str, Any], *, width: int = 120) -> RenderableType:
        """Render a standalone dossier dictionary using the authoritative IncidentDetailVM builder."""
        inc_id = str(dossier.get("incident_id") or "")
        incident_row: Mapping[str, Any] | None = None
        checkpoint_row: Mapping[str, Any] | None = None
        transitions: Sequence[Mapping[str, Any]] = ()
        reviews: Sequence[Mapping[str, Any]] = ()
        llm_run: Mapping[str, Any] | None = None
        version_rows: list[Dict[str, Any]] = []

        if inc_id:
            try:
                with self.store.transaction(immediate=False):
                    incident_row = self.store.get_incident(inc_id)
                    checkpoint_row = self.store.get_checkpoint(inc_id)
                    transitions = self.store.get_transitions(inc_id)
                    reviews = self.store.get_reviews(inc_id)
                    conn = self.store._conn
                    for vr in conn.execute(
                        "SELECT dossier_version, dossier_hash, created_at FROM dossiers WHERE incident_id = ? ORDER BY dossier_version DESC",
                        (inc_id,),
                    ).fetchall():
                        version_rows.append(dict(vr))
                    has_llm = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='c13_llm_runs'"
                    ).fetchone()
                    if has_llm:
                        cols = {str(c[1]) for c in conn.execute("PRAGMA table_info(c13_llm_runs)").fetchall()}
                        want = [
                            c for c in ("incident_id", "provider", "model", "input_reported", "output_reported", "status", "error_code", "result", "context_diagnostics")
                            if c in cols
                        ]
                        lrow = conn.execute(
                            f"SELECT {', '.join(want)} FROM c13_llm_runs WHERE incident_id = ? ORDER BY rowid DESC LIMIT 1",
                            (inc_id,),
                        ).fetchone()
                        if lrow:
                            llm_run = dict(lrow)
            except Exception:
                pass

        vm = build_incident_detail_vm(
            incident=incident_row,
            dossier=dossier,
            dossier_versions=version_rows,
            checkpoint=checkpoint_row,
            transitions=transitions,
            reviews=reviews,
            llm_run=llm_run,
            reviewer_ref=self.reviewer_ref,
            reviewer_role=self.reviewer_role,
            reviewer_directory=self.reviewer_directory,
            require_registered_reviewer=self.require_registered_reviewer,
            require_authenticated_context=self.require_authenticated_context,
        )
        return self._render_incident_detail_vm(vm, width=width)

    def _render_lens_bar(self, vm: IncidentDetailVM) -> Text:
        tokens = self._tokens()
        bar = Text("View Lens ([Tab] switch): ", style=tokens.secondary)
        for idx, lens_key in enumerate(DETAIL_LENS_ORDER):
            if idx > 0:
                bar.append(" ")
            label = DETAIL_LENS_LABELS[lens_key]
            if lens_key == "hypotheses":
                label = f"{label}({len(vm.hypotheses)})"
            elif lens_key == "evidence":
                label = f"{label}({len(vm.evidence_items)})"
            elif lens_key == "sop":
                label = f"{label}({len(vm.rag.citations)})"
            style = tokens.selected_nav if self.detail_section == lens_key else tokens.muted
            bar.append(f" {label} ", style=style)
        return bar

    def _render_lifecycle_bar(self, vm: IncidentDetailVM) -> Text:
        tokens = self._tokens()
        line = Text("Workflow Stages: ", style=tokens.secondary)
        short_names = {
            "RECEIVED": "RCV",
            "CORRELATED": "COR",
            "TRIAGED": "TRI",
            "EVIDENCE_COLLECTED": "EVD",
            "RETRIEVED": "RAG",
            "HYPOTHESES": "HYP",
            "VALIDATED": "VAL",
            "DRAFTED": "DRF",
            "HUMAN_REVIEW": "REV",
        }
        for idx, st in enumerate(vm.stages):
            if idx > 0:
                line.append("->", style=tokens.muted)
            short = short_names.get(st.stage, st.stage[:3])
            if st.status == "COMPLETED":
                line.append(f"[x:{short}]", style=tokens.secondary)
            elif st.status == "CURRENT":
                line.append(f"[*:{short}]", style=tokens.accent)
            elif st.status == "ABORTED":
                line.append(f"[!:{short}]", style=tokens.critical)
            else:
                line.append(f"[ :{short}]", style=tokens.muted)

        if vm.lifecycle_state in ARCHIVED_LIFECYCLE_STATES:
            term_style = tokens.warning if vm.lifecycle_state in ("CLOSED", "LEARNED") else tokens.critical
            line.append(f" => [{vm.lifecycle_display}]", style=term_style)
        line.append(
            f"  (Duration: {vm.duration_display}"
            + (f", ToolCalls: {vm.tool_calls_used}" if vm.tool_calls_used is not None else "")
            + " | Stage completion != verified diagnosis)",
            style=tokens.muted,
        )
        return line

    def _render_incident_header(self, vm: IncidentDetailVM) -> RenderableType:
        tokens = self._tokens()
        header = Table.grid(expand=True, padding=(0, 2))
        header.add_column(width=22, style=tokens.secondary)
        header.add_column(ratio=1, style=tokens.primary)

        header.add_row(
            "Incident / Revision",
            Text.assemble(
                (f"{vm.incident_id} ", tokens.primary_bold),
                (f"({vm.revision_history_note})", tokens.secondary),
            ),
        )
        header.add_row(
            "Severity & Scope",
            Text.assemble(
                (f"{vm.severity_badge} ", tokens.severity_style(vm.severity)),
                (f"| env={vm.environment} | services: {', '.join(vm.affected_services)}", tokens.primary),
            ),
        )
        header.add_row("Closure / Diagnosis", Text(vm.review_eligibility.closure_display, style=tokens.warning_soft))
        header.add_row(
            "Safety & Trust",
            Text(
                f"Auto remediation: DISABLED (auto_action_triggered=False) | Reviewer Trust: {vm.review_eligibility.identity_disclosure}",
                style=tokens.secondary,
            ),
        )
        mode_style = (
            tokens.corroborated
            if vm.investigation_mode == "agentic_llm"
            else (tokens.critical if vm.investigation_mode == "manual_fallback" else tokens.warning)
        )
        header.add_row("Reasoning Mode", Text(vm.mode_headline, style=mode_style))
        header.add_row(
            "Provider / Model",
            Text(f"{vm.provider_name} / {vm.model_version}", style=tokens.primary),
        )
        header.add_row("Token Usage", Text(vm.token_usage_display, style=tokens.primary))
        header.add_row(
            "Prompt / Timing",
            Text(
                f"Prompt: {vm.prompt_version[:28]} | Alert: {vm.alert_received_at} | Ready: {vm.dossier_ready_at}",
                style=tokens.muted,
            ),
        )
        return header

    def _render_hypotheses_section(self, vm: IncidentDetailVM, *, interactive_focus: bool = False) -> RenderableType:
        tokens = self._tokens()
        pbox = self._panel_box()
        blocks: list[RenderableType] = []

        if not vm.dossier_available and not vm.hypotheses:
            pending_h = Text()
            pending_h.append(
                f"Dossier not yet available: investigation is currently at stage {vm.lifecycle_state}.\n",
                style=tokens.warning,
            )
            pending_h.append("Hypotheses and confidence scores appear once HYPOTHESES/VALIDATED stages complete.", style=tokens.secondary)
            return Panel(pending_h, title="Hypotheses & Confidence", border_style=tokens.border_inactive, box=pbox)

        cal_banner = Text()
        cal_banner.append(f"Calibration & Ranking: {CALIBRATION_LIMITATION_NOTE}\n", style=tokens.secondary)
        cal_banner.append(vm.ranking_note, style=tokens.warning_soft if "INV-16" in vm.ranking_note else tokens.muted)
        blocks.append(cal_banner)

        hypothesis_table = Table(expand=True, box=self._table_box(), pad_edge=False)
        hypothesis_table.add_column("Rank", width=6, no_wrap=True)
        hypothesis_table.add_column("Hypothesis", ratio=3)
        hypothesis_table.add_column("Support", width=15, no_wrap=True)
        hypothesis_table.add_column("Confidence", width=20, no_wrap=True)
        hypothesis_table.add_column("Evid(+/-)", width=10, justify="right", no_wrap=True)

        if vm.hypotheses:
            self.selected_hypothesis_idx = max(0, min(self.selected_hypothesis_idx, len(vm.hypotheses) - 1))
        for idx_h, h_vm in enumerate(vm.hypotheses):
            is_sel = interactive_focus and idx_h == self.selected_hypothesis_idx
            prefix = f"{self._sel_glyph()} " if is_sel else "  "
            origin_badge = (
                "[HUMAN EDIT] "
                if h_vm.origin_kind == "HUMAN_CORRECTION"
                else ("[ORIG AI] " if h_vm.origin_kind == "ORIGINAL_AI_FINDING" else "")
            )
            hypothesis_table.add_row(
                f"{prefix}#{h_vm.rank}",
                f"{origin_badge}{h_vm.statement}",
                Text(f"[{h_vm.support_label}]", style=tokens.support_style(h_vm.support_label)),
                Text(h_vm.confidence_display, style=tokens.primary_bold if not h_vm.is_unvalidated_prior else tokens.warning_soft),
                f"+{len(h_vm.supporting_ids)} / -{len(h_vm.contradicting_ids)}",
                style=tokens.selected_row if is_sel else tokens.primary,
            )
        if not vm.hypotheses:
            hypothesis_table.add_row("-", "No hypotheses formulated", "[INCONCLUSIVE]", "Not scored", "0 / 0")
        blocks.append(hypothesis_table)

        reasoning_text = Text()
        target_hyps = (
            [vm.hypotheses[self.selected_hypothesis_idx]]
            if interactive_focus and vm.hypotheses
            else list(vm.hypotheses)
        )
        for idx_d, h_vm in enumerate(target_hyps):
            if idx_d > 0:
                reasoning_text.append("\n")
            reasoning_text.append(
                f"#{h_vm.rank} ({h_vm.hypothesis_id}) [{h_vm.support_label} | {h_vm.confidence_display}] {h_vm.statement}\n",
                style=tokens.accent,
            )
            if h_vm.reason_summary:
                reasoning_text.append(f"  Why / Causal Analysis : {h_vm.reason_summary}\n", style=tokens.primary)
            if h_vm.confidence_rationale:
                reasoning_text.append(f"  Confidence Basis      : {h_vm.confidence_rationale}\n", style=tokens.secondary)
            reasoning_text.append(f"  Main Uncertainty      : {h_vm.main_uncertainty}\n", style=tokens.warning_soft)
            sup_str = ", ".join(h_vm.supporting_ids) if h_vm.supporting_ids else "none (no accepted supporting evidence)"
            reasoning_text.append(f"  Supporting Evidence   : {sup_str}\n", style=tokens.corroborated if h_vm.supporting_ids else tokens.secondary)
            if h_vm.contradicting_ids:
                reasoning_text.append(
                    f"  Contradicting Evidence: {', '.join(h_vm.contradicting_ids)}\n",
                    style=tokens.critical,
                )
            if h_vm.partial_supporting_ids:
                reasoning_text.append(
                    f"  Partial/Truncated Evid: {', '.join(h_vm.partial_supporting_ids)}\n",
                    style=tokens.warning_soft,
                )
            for excl in h_vm.excluded_supporting:
                reasoning_text.append(
                    f"  Rejected Association  : {excl['evidence_id']} ({excl['reason']})\n",
                    style=tokens.critical,
                )
        if interactive_focus and vm.hypotheses:
            reasoning_text.append(
                "\nTip: Press [[ / ]] to switch hypothesis, or [I] to jump directly to its linked Evidence Lineage.",
                style=tokens.secondary,
            )
        if not reasoning_text.plain:
            reasoning_text.append("No hypothesis reasoning available.", style=tokens.muted)

        blocks.append(
            Panel(
                reasoning_text,
                title="Hypothesis Reasoning Details (Why & How)",
                border_style=tokens.border_focused if interactive_focus else tokens.border_inactive,
                box=pbox,
            )
        )
        return Group(*blocks)

    def _render_evidence_section(self, vm: IncidentDetailVM, *, interactive_focus: bool = False) -> RenderableType:
        tokens = self._tokens()
        pbox = self._panel_box()
        evidence_text = Text()
        evidence_text.append(f"Integrity Note: {INTEGRITY_SEMANTICS_NOTE}\n", style=tokens.muted)

        if vm.unresolved_evidence_refs:
            for uref in vm.unresolved_evidence_refs:
                evidence_text.append(
                    f"[UNRESOLVED REFERENCE] Hypothesis #{uref.hypothesis_rank} ({uref.hypothesis_id}) cites "
                    f"{uref.role} evidence '{uref.evidence_id}', which is absent from authorized telemetry.\n",
                    style=tokens.critical,
                )

        if vm.evidence_items:
            self.selected_evidence_idx = max(0, min(self.selected_evidence_idx, len(vm.evidence_items) - 1))

        for idx_e, item in enumerate(vm.evidence_items):
            if idx_e > 0:
                evidence_text.append("\n")
            is_sel = interactive_focus and idx_e == self.selected_evidence_idx
            marker = f"{self._sel_glyph()} " if is_sel else "  "
            disp_style = {
                "ACCEPTED_SUPPORT": tokens.corroborated,
                "CONTRADICTING": tokens.critical,
                "REJECTED": tokens.critical,
                "CONTEXTUAL": tokens.secondary,
            }.get(item.disposition, tokens.secondary)
            temp_style = (
                tokens.critical
                if item.temporal_classification in ("OUTSIDE_INCIDENT_WINDOW", "TIMESTAMP_INVALID", "TIMESTAMP_MISSING", "SOURCE_UNAVAILABLE")
                else (tokens.warning_soft if "STALE" in item.temporal_classification or item.truncated or item.data_quality == "partial" else tokens.secondary)
            )
            refs_str = ", ".join(item.associated_hypotheses) if item.associated_hypotheses else "contextual (not cited as support)"
            qual_str = item.data_quality + ("/truncated" if item.truncated else "")

            evidence_text.append(f"{marker}{item.evidence_id} ", style=tokens.selected_row if is_sel else tokens.primary_bold)
            evidence_text.append(f"[{item.disposition}] ", style=disp_style)
            evidence_text.append(f"{item.temporal_badge}\n", style=temp_style)
            evidence_text.append(
                f"    {item.tool_name} ({item.source_ref}) | svc={item.service_id} ({item.environment}) | "
                f"obs={item.observed_at} | win={item.query_window_str} | collected={item.collected_at}\n",
                style=tokens.secondary,
            )
            evidence_text.append(
                f"    signal={item.observation_kind} | val={item.value_and_unit} | agg={item.aggregation} | "
                f"quality={qual_str} ({item.sampling_note}) | sha256={item.content_hash_short} | refs={refs_str}\n",
                style=tokens.secondary,
            )
            evidence_text.append(f"    Summary: {item.summary}\n", style=tokens.primary)
            for lim in item.limitations:
                evidence_text.append(f"    Limitation/Reason: {lim}\n", style=tokens.warning_soft)

        if not vm.evidence_items:
            evidence_text.append("No verified telemetry evidence recorded for this incident.\n", style=tokens.muted)
        if interactive_focus and vm.evidence_items:
            evidence_text.append("\nTip: Press [[ / ]] to step evidence items, or [B/Esc] to return.", style=tokens.secondary)

        return Panel(
            evidence_text,
            title="Verified Evidence IDs & Temporal Provenance",
            border_style=tokens.border_focused if interactive_focus else tokens.border_inactive,
            box=pbox,
        )

    def _render_sop_and_checks_section(self, vm: IncidentDetailVM, *, interactive_focus: bool = False) -> RenderableType:
        tokens = self._tokens()
        pbox = self._panel_box()

        citation_text = Text()
        avail_style = (
            tokens.warning
            if vm.rag.availability_code in ("CONFLICTING_OR_COMPETING_SOPS", "RETRIEVAL_UNAVAILABLE", "SOP_FILTERED_OUT", "NO_APPLICABLE_RUNBOOK")
            else tokens.corroborated
        )
        citation_text.append(f"SOP Status [{vm.rag.availability_code}]: {vm.rag.availability_banner}\n", style=avail_style)
        citation_text.append(f"Assessment: {vm.rag.availability_explanation}\n", style=tokens.secondary)
        if vm.rag.competing_sop_warning:
            citation_text.append(f"[COMPETING SOP WARNING] {vm.rag.competing_sop_warning}\n", style=tokens.critical)
        citation_text.append(f"RAG Context Delivery: {vm.rag.delivery_summary}\n", style=tokens.secondary)
        if vm.rag.omitted_reasons:
            citation_text.append(
                f"Compaction Omissions: {', '.join(vm.rag.omitted_reasons)}\n",
                style=tokens.warning_soft,
            )

        for cit in vm.rag.citations:
            citation_text.append(
                f"\n- {cit.doc_id} v{cit.version} | {cit.section_path} | {cit.chunk_id} | {cit.source_uri}\n",
                style=tokens.primary_bold,
            )
            if cit.retrieval_score_note:
                citation_text.append(f"  {cit.retrieval_score_note}\n", style=tokens.muted)
            citation_text.append(f"  {cit.excerpt}\n", style=tokens.primary)

        checks_text = Text()
        for chk in vm.rag.manual_checks:
            tag_style = tokens.critical if "ESCALATION" in chk.provenance_tag else (
                tokens.warning_soft if "NOT SOP-BACKED" in chk.provenance_tag else tokens.corroborated
            )
            checks_text.append(
                f"{chk.index}. [{chk.check_id} | STATUS={chk.status} | RISK={chk.risk_level} | SOP={chk.related_sop_doc_id}] ",
                style=tokens.primary_bold,
            )
            checks_text.append(f"[{chk.provenance_tag}]\n", style=tag_style)
            checks_text.append(f"   {chk.description}\n", style=tokens.primary)
        if vm.rag.manual_checks:
            checks_text.append(
                "Guardrail: status=NOT_PERFORMED | auto_execution_allowed=False | requires_human_approval=True",
                style=tokens.secondary,
            )
        else:
            checks_text.append("No SRE verification steps recorded.", style=tokens.muted)

        return Group(
            Panel(
                citation_text,
                title="Runbook SOP Citations & RAG Transparency",
                border_style=tokens.border_focused if interactive_focus else tokens.border_inactive,
                box=pbox,
            ),
            Panel(
                checks_text,
                title="SRE Recommended Verification (Human-Controlled)",
                border_style=tokens.border_inactive,
                box=pbox,
            ),
        )

    def _render_unknowns_section(self, vm: IncidentDetailVM) -> Panel:
        tokens = self._tokens()
        unknowns_text = Text()
        for unk in vm.unknowns:
            unknowns_text.append(f"- {unk}\n", style=tokens.primary)
        for ms in vm.missing_sources:
            unknowns_text.append(
                f"- [MISSING SOURCE] {ms['tool_name']} ({ms['error_code']}): {ms['impact_note']}\n",
                style=tokens.warning_soft,
            )
        if not unknowns_text.plain:
            unknowns_text.append("No uncertainties or missing sources recorded.", style=tokens.muted)
        return Panel(
            unknowns_text,
            title="Unknowns & Missing Sources",
            border_style=tokens.border_inactive,
            box=self._panel_box(),
        )

    def _render_review_section(self, vm: IncidentDetailVM) -> Panel:
        tokens = self._tokens()
        rev_text = Text()
        elig = vm.review_eligibility
        elig_style = tokens.accent if elig.eligible else tokens.warning
        rev_text.append(f"Eligibility : {elig.lock_message}\n", style=elig_style)
        rev_text.append(
            f"Reviewer    : {elig.reviewer_ref} ({elig.reviewer_role}) | Mode: {elig.identity_disclosure}\n",
            style=tokens.secondary,
        )
        rev_text.append(f"Semantics   : {elig.closure_display}\n", style=tokens.secondary)
        if vm.consistency_warnings:
            for cw in vm.consistency_warnings:
                rev_text.append(f"[CONSISTENCY NOTICE] {cw}\n", style=tokens.critical)
        if vm.review_history:
            rev_text.append("\nAppend-Only Review History:\n", style=tokens.primary_bold)
            for rev in vm.review_history:
                extra = f" -> v{rev['edited_dossier_version']}" if rev.get("edited_dossier_version") else (
                    f" -> {rev['escalation_target']}" if rev.get("escalation_target") else ""
                )
                rev_text.append(
                    f"  - {rev['reviewed_at']} | v{rev['target_dossier_version']} | {rev['decision']}{extra} "
                    f"by {rev['reviewer_ref']} ({rev['reviewer_role']}): {rev['rationale']}\n",
                    style=tokens.primary,
                )
        else:
            rev_text.append("No human review decisions submitted yet for this incident.", style=tokens.muted)
        return Panel(
            rev_text,
            title="Human Review Status & Audit Trail",
            border_style=tokens.border_inactive,
            box=self._panel_box(),
        )

    def _render_incident_detail_vm(self, vm: IncidentDetailVM, *, width: int = 120) -> RenderableType:
        tokens = self._tokens()
        pbox = self._panel_box()

        symptom_panel = Panel(
            Text(vm.observed_symptoms, style=tokens.primary),
            title="Observed Symptoms",
            border_style=tokens.border_inactive,
            box=pbox,
        )

        impact_text = Text()
        if vm.error_budget_impact:
            impact_text.append(f"Error Budget Impact: {vm.error_budget_impact}\n", style=tokens.primary_bold)
        if vm.topology_flow:
            impact_text.append(f"Topology Flow: {vm.topology_flow}\n", style=tokens.primary)
        if vm.cascade_summary:
            impact_text.append(f"Cascade Check: {vm.cascade_summary}\n", style=tokens.primary)
        if vm.topology_uncertainty:
            impact_text.append(f"Topology Note: {vm.topology_uncertainty}\n", style=tokens.secondary)

        compact_ctx = Text()
        compact_ctx.append(f"{vm.incident_id} ", style=tokens.primary_bold)
        compact_ctx.append(f"(v{vm.dossier_version}) | ", style=tokens.secondary)
        compact_ctx.append(f"{vm.severity_badge} ", style=tokens.severity_style(vm.severity))
        compact_ctx.append(f"| {vm.primary_service} ({vm.environment}) | State: {vm.lifecycle_display} | Mode: {vm.mode_badge}\n", style=tokens.primary)
        compact_ctx.append(
            f"Closure: {vm.review_eligibility.dossier_review_status} (diagnosis_verified=False, auto_action_triggered=False) | "
            f"Trust: {vm.review_eligibility.identity_disclosure}",
            style=tokens.secondary,
        )

        focused_blocks: list[RenderableType] = [
            self._render_lens_bar(vm),
            compact_ctx,
        ]
        if vm.consistency_warnings:
            warn_f = Text("\n".join(vm.consistency_warnings), style=tokens.critical)
            focused_blocks.append(Panel(warn_f, title="State Consistency Notice", border_style=tokens.border_modal, box=pbox))

        if self.detail_section == "hypotheses":
            focused_blocks.append(self._render_hypotheses_section(vm, interactive_focus=True))
            return Group(*focused_blocks)

        if self.detail_section == "evidence":
            focused_blocks.append(self._render_evidence_section(vm, interactive_focus=True))
            return Group(*focused_blocks)

        if self.detail_section == "sop":
            focused_blocks.append(self._render_sop_and_checks_section(vm, interactive_focus=True))
            return Group(*focused_blocks)

        if self.detail_section == "review":
            focused_blocks.append(self._render_review_section(vm))
            return Group(*focused_blocks)

        top_blocks: list[RenderableType] = [
            self._render_lens_bar(vm),
            self._render_incident_header(vm),
            self._render_lifecycle_bar(vm),
        ]
        if vm.consistency_warnings:
            warn_t = Text("\n".join(vm.consistency_warnings), style=tokens.critical)
            top_blocks.append(Panel(warn_t, title="State Consistency Notice", border_style=tokens.border_modal, box=pbox))

        if self.detail_section == "overview":
            top_blocks.append(symptom_panel)
            if impact_text.plain.strip():
                top_blocks.append(Panel(impact_text, title="Impact & Dependency Context", border_style=tokens.border_inactive, box=pbox))
            if vm.hypotheses:
                lead = vm.hypotheses[0]
                lead_txt = Text()
                lead_txt.append(f"Leading Candidate (#1): [{lead.support_label} | {lead.confidence_display}]\n", style=tokens.accent)
                lead_txt.append(f"{lead.statement}\n", style=tokens.primary)
                lead_txt.append(f"Uncertainty: {lead.main_uncertainty}", style=tokens.warning_soft)
                top_blocks.append(Panel(lead_txt, title="Leading Hypothesis Summary", border_style=tokens.border_inactive, box=pbox))
            top_blocks.append(self._render_unknowns_section(vm))
            top_blocks.append(self._render_review_section(vm))
            return Group(*top_blocks)

        # Default "all" lens: full, structured dossier inspection
        top_blocks.append(symptom_panel)
        if impact_text.plain.strip():
            top_blocks.append(Panel(impact_text, title="Impact & Dependency Context", border_style=tokens.border_inactive, box=pbox))
        top_blocks.extend([
            self._render_hypotheses_section(vm, interactive_focus=False),
            self._render_unknowns_section(vm),
            self._render_sop_and_checks_section(vm, interactive_focus=False),
            self._render_evidence_section(vm, interactive_focus=False),
            self._render_review_section(vm),
        ])
        return Group(*top_blocks)

    # ------------------------------------------------------------------
    # Help Overlay & Two-Step Safe Human Review Modal (Work Package D1, K1-K9)
    # ------------------------------------------------------------------

    def _render_help_modal(
        self,
        snapshot: DashboardSnapshot,
        *,
        width: int,
        height: int | None,
    ) -> RenderableType:
        tokens = self._tokens()
        pbox = self._panel_box()
        body = Text()
        body.append("KEYBOARD NAVIGATION & INTERACTION REFERENCE\n", style=tokens.primary_bold)
        body.append(
            "  Global          : [1-5] Switch Tab | [U] Manual Refresh | [?] Toggle Help | [Q] Quit Safely\n"
            "  Overview / List : [Up/Dn or j/k] Move Row | [Left/Right/Tab] Menu <-> List | [Enter/O] Open | [G] Grafana\n"
            "  Incident Detail : [Tab] Cycle Detail Lens (All/Overview/Hypotheses/Evidence/SOP/Review)\n"
            "                    [[ / ]] Previous/Next Hypothesis or Evidence | [I] Jump Hypothesis -> Evidence\n"
            "                    [Up/Dn or PgUp/PgDn] Scroll | [B / Esc / Left] Return (preserves selection)\n"
            "  Human Review    : [A] Approve | [R] Reject | [C] Correct (vN+1) | [E] Escalate (opens confirmation modal)\n"
            "  Review Modal    : Type into focused field | [Tab/Up/Dn] Switch Field/Button | [Enter] Next/Confirm | [Esc] Cancel\n\n",
            style=tokens.primary,
        )
        body.append("OPERATIONAL & SAFETY SEMANTICS (NON-NEGOTIABLE)\n", style=tokens.warning)
        body.append(
            "  1. Zero Auto-Remediation (INV-01 / HUM-01): Dashboard and AI never restart, scale, deploy, or mutate services.\n"
            "  2. RULE-007 & Heuristic Confidence: Scores in [5%-85%] are uncalibrated support heuristics, NEVER empirical\n"
            "     probabilities and never confirmed/proven root causes.\n"
            "  3. Administrative Closure (INV-06): APPROVE -> CLOSED accepts dossier handover only\n"
            "     (diagnosis_verified=False, technical_resolved=False, sop_compliance_confirmed=False, remediation_authorized=False).\n"
            "  4. Reviewer Identity: Local PoC caller-asserted identifier (unauthenticated; not SSO/OIDC-verified).\n\n",
            style=tokens.secondary,
        )
        body.append("Press [Esc], [?], or [B] to close help and return to your current view.", style=tokens.accent)
        return Panel(
            body,
            title="SRE Investigation Console - Keyboard & Semantics Reference",
            border_style=tokens.border_focused,
            box=pbox,
        )

    def open_review_modal(self, action: str) -> bool:
        """Validate authoritative eligibility & revision freshness, then open two-step review modal."""
        action_upper = action.upper()
        if action_upper not in REVIEW_ACTION_SEMANTICS:
            self.notice = f"Unsupported review action: {action_upper}."
            return False
        if not self.selected_incident_id:
            self.notice = "Open an incident dossier first ([Enter] or [O]) before starting a review."
            return False

        snap = self.refresh_snapshot()
        vm = snap.by_incident_id.get(self.selected_incident_id)
        if vm is None or vm.raw_dossier is None:
            self.notice = "Review unavailable: dossier is not generated for this incident."
            return False

        if not vm.review_eligibility.eligible:
            self.notice = vm.review_eligibility.lock_message
            return False

        # K8 Stale Revision Pre-Check: ensure operator actually inspected the latest persisted revision
        if (
            self.viewed_dossier_version
            and vm.dossier_version != self.viewed_dossier_version
        ) or (
            self.viewed_dossier_hash
            and self.viewed_dossier_hash != "unavailable"
            and vm.dossier_hash != self.viewed_dossier_hash
        ):
            old_v = self.viewed_dossier_version
            self.viewed_dossier_version = vm.dossier_version
            self.viewed_dossier_hash = vm.dossier_hash
            self.notice = (
                f"[REVISION CHANGED] Dossier updated from v{old_v} to v{vm.dossier_version}; "
                f"reloaded v{vm.dossier_version}. Inspect changes and press [{action_upper[0]}] again."
            )
            return False

        fields: list[str] = []
        if action_upper == "CORRECT":
            fields.append("corrected_hypothesis")
        elif action_upper == "ESCALATE":
            fields.append("escalation_target")
        fields.append("rationale")
        fields.extend(["confirm", "cancel"])

        saved_draft = self.unsent_review_draft.get(vm.incident_id, "")
        self.review_modal = {
            "action": action_upper,
            "incident_id": vm.incident_id,
            "target_version": vm.dossier_version,
            "target_hash": vm.dossier_hash,
            "dossier_snapshot": dict(vm.raw_dossier),
            "fields": fields,
            "focus_idx": 0,
            "rationale": saved_draft,
            "corrected_hypothesis": "",
            "escalation_target": "SRE_LEAD_ONCALL" if action_upper == "ESCALATE" else "",
            "error": "",
            "submitting": False,
        }
        self.notice = f"Review confirmation opened for {vm.incident_id} v{vm.dossier_version} ({action_upper})."
        return True

    def cancel_review_modal(self) -> None:
        """Cancel open review confirmation without mutating domain state (D07, B09)."""
        if self.review_modal is not None:
            inc_id = self.review_modal.get("incident_id", "")
            act = self.review_modal.get("action", "REVIEW")
            self._preserve_unsent_modal_draft()
            self.review_modal = None
            self.notice = f"{act} cancelled for {inc_id}; no state or audit changes were made."

    def submit_review_modal(self) -> bool:
        """Validate inputs and submit version-bound review decision through AuthorizedReviewManager."""
        modal = self.review_modal
        if modal is None:
            return False
        if modal.get("submitting"):
            modal["error"] = "Submission already in progress; duplicate submit ignored."
            return False

        action = str(modal["action"]).upper()
        rationale = " ".join(str(modal.get("rationale") or "").split())
        corrected = " ".join(str(modal.get("corrected_hypothesis") or "").split())
        esc_target = " ".join(str(modal.get("escalation_target") or "").split()) or "SRE_LEAD_ONCALL"

        if action == "CORRECT":
            if len(corrected) < 5:
                modal["error"] = "Validation error: Corrected hypothesis must be at least 5 characters."
                return False
            if "verified" in corrected.lower().split() or "VERIFIED" in corrected.upper():
                import re as _re
                if _re.search(r"\bVERIFIED\b", corrected, _re.IGNORECASE):
                    modal["error"] = "RULE-007 violation: Human correction cannot claim 'VERIFIED' status."
                    return False

        if len(rationale) < 5:
            modal["error"] = "Validation error: Rationale is required (minimum 5 characters)."
            return False

        modal["submitting"] = True
        modal["error"] = ""
        try:
            result = self.actions.apply(
                modal["dossier_snapshot"],
                action,
                reviewer_ref=self.reviewer_ref,
                reviewer_role=self.reviewer_role,
                rationale=rationale,
                corrected_hypothesis=corrected if action == "CORRECT" else None,
                escalation_target=esc_target if action == "ESCALATE" else None,
                target_version=int(modal["target_version"]),
                auth_context=self.auth_context,
            )
        except (StaleDossierVersionError, ReviewStateConflictError) as exc:
            modal["submitting"] = False
            self._preserve_unsent_modal_draft()
            code = getattr(exc, "code", "VERSION_CONFLICT")
            safe_msg = sanitize_terminal_text(str(exc), max_chars=180)
            snap = self.refresh_snapshot()
            updated_vm = snap.by_incident_id.get(str(modal["incident_id"]))
            self.review_modal = None
            if updated_vm is not None:
                self.viewed_dossier_version = updated_vm.dossier_version
                self.viewed_dossier_hash = updated_vm.dossier_hash
            self.notice = f"[REVIEW CONFLICT - {code}] {safe_msg} (authoritative state reloaded)."
            return False
        except (UnauthorizedReviewerError, InvalidDossierError, ReviewError) as exc:
            modal["submitting"] = False
            code = getattr(exc, "code", "REVIEW_ERROR")
            safe_msg = sanitize_terminal_text(str(exc), max_chars=180)
            modal["error"] = f"Rejected ({code}): {safe_msg}"
            self.refresh_snapshot()
            self.notice = f"Review rejected ({code}): {safe_msg}"
            return False
        except (sqlite3.Error, OSError, ValueError) as exc:
            modal["submitting"] = False
            safe_msg = sanitize_terminal_text(f"{type(exc).__name__}: {exc}", max_chars=160)
            modal["error"] = f"Persistence/audit failure (no changes committed): {safe_msg}"
            self.refresh_snapshot()
            self.notice = f"Review submission failed safely: {safe_msg}"
            return False
        except Exception as exc:
            modal["submitting"] = False
            safe_msg = sanitize_terminal_text(type(exc).__name__, max_chars=80)
            modal["error"] = f"Unexpected error ({safe_msg}); review was not marked completed."
            self.refresh_snapshot()
            self.notice = f"Review submission failed ({safe_msg})."
            return False

        inc_id = str(modal["incident_id"])
        self.unsent_review_draft.pop(inc_id, None)
        self.review_modal = None
        snap = self.refresh_snapshot()
        updated_vm = snap.by_incident_id.get(inc_id)
        if updated_vm is not None:
            self.viewed_dossier_version = updated_vm.dossier_version
            self.viewed_dossier_hash = updated_vm.dossier_hash

        semantics = result.get("approval_semantics") or {}
        meaning = semantics.get("closure_meaning", action)
        if action == "CORRECT":
            new_rev = (result.get("review_result") or {}).get("new_dossier_revision") or {}
            new_v = new_rev.get("dossier_version", (updated_vm.dossier_version if updated_vm else 2))
            self.notice = (
                f"CORRECT recorded: spawned append-only Revision v{new_v} (PENDING_REVIEW); "
                "original AI findings preserved."
            )
        else:
            self.notice = (
                f"{action} confirmed ({meaning}); diagnosis_verified=False; technical_resolved=False; "
                f"auto_action_triggered={result['auto_action_triggered']}."
            )
        return True

    def _render_review_modal(
        self,
        snapshot: DashboardSnapshot,
        *,
        width: int,
        height: int | None,
    ) -> RenderableType:
        tokens = self._tokens()
        pbox = self._panel_box()
        modal = self.review_modal or {}
        action = str(modal.get("action") or "APPROVE")
        inc_id = str(modal.get("incident_id") or "")
        vm = snapshot.by_incident_id.get(inc_id)
        sem = REVIEW_ACTION_SEMANTICS[action]

        body = Text()
        body.append(f"CONFIRM HUMAN REVIEW ACTION: {sem['label']}\n", style=tokens.warning)
        body.append(
            f"Target Incident : {inc_id} | Revision: v{modal.get('target_version')} "
            f"(sha256: {str(modal.get('target_hash', ''))[:16]}...)\n",
            style=tokens.primary_bold,
        )
        body.append(
            f"Lifecycle State : {vm.lifecycle_state if vm else 'HUMAN_REVIEW'} -> {sem['resulting_state']}\n",
            style=tokens.primary,
        )
        body.append(
            f"Reviewer Actor  : {self.reviewer_ref} ({self.reviewer_role}) | "
            "Local PoC caller-asserted identity (unauthenticated)\n\n",
            style=tokens.secondary,
        )

        if vm is not None:
            lead_str = (
                f"#{vm.hypotheses[0].rank} [{vm.hypotheses[0].support_label} | {vm.hypotheses[0].confidence_display}] "
                f"{sanitize_terminal_text(vm.hypotheses[0].statement, max_chars=96)}"
                if vm.hypotheses
                else "No hypotheses recorded"
            )
            sup_cnt = sum(1 for e in vm.evidence_items if e.disposition == "ACCEPTED_SUPPORT")
            con_cnt = sum(1 for e in vm.evidence_items if e.disposition == "CONTRADICTING")
            body.append("Pre-Submission Diagnostic Summary:\n", style=tokens.primary_bold)
            body.append(f"  Leading Hypothesis : {lead_str}\n", style=tokens.primary)
            body.append(
                f"  Evidence Balance   : {sup_cnt} supporting, {con_cnt} contradicting, {len(vm.evidence_items)} total\n"
                f"  SOP Classification : {vm.rag.availability_code} | Pending Manual Checks: {len(vm.rag.manual_checks)} (NOT_PERFORMED)\n\n",
                style=tokens.secondary,
            )

        body.append("Operational Meaning & Safety Boundary:\n", style=tokens.primary_bold)
        body.append(f"  {sem['summary']}\n\n", style=tokens.warning_soft)

        fields: list[str] = list(modal.get("fields") or ["rationale", "confirm", "cancel"])
        focus_idx = max(0, min(int(modal.get("focus_idx", 0)), len(fields) - 1))
        focused_field = fields[focus_idx]

        def _render_input_line(field_key: str, label: str, placeholder: str) -> None:
            is_f = focused_field == field_key
            val = str(modal.get(field_key) or "")
            cursor = "_" if is_f else ""
            prefix = f"{self._sel_glyph()} " if is_f else "  "
            body.append(f"{prefix}{label}:\n", style=tokens.accent if is_f else tokens.secondary)
            if val or is_f:
                body.append(f"    {val}{cursor}\n", style=tokens.primary_bold if is_f else tokens.primary)
            else:
                body.append(f"    {placeholder}\n", style=tokens.muted)

        if "corrected_hypothesis" in fields:
            _render_input_line(
                "corrected_hypothesis",
                "Corrected Hypothesis (min 5 chars, cannot claim VERIFIED)",
                "[Type candidate root-cause hypothesis...]",
            )
        if "escalation_target" in fields:
            _render_input_line(
                "escalation_target",
                "Escalation Target",
                "SRE_LEAD_ONCALL",
            )
        _render_input_line(
            "rationale",
            "Reviewer Rationale (required, min 5 chars)",
            "[Type justification grounded in observed telemetry...]",
        )

        body.append("\n")
        confirm_style = tokens.selected_nav if focused_field == "confirm" else tokens.primary_bold
        cancel_style = tokens.selected_nav if focused_field == "cancel" else tokens.secondary
        body.append(f"  [ Confirm & Submit {action} ]  ", style=confirm_style)
        body.append("  ")
        body.append("  [ Cancel (Esc) ]  \n", style=cancel_style)

        if modal.get("error"):
            body.append(f"\n[!] {modal['error']}\n", style=tokens.critical)

        body.append(
            "\nControls: Type text into active field | [Tab/Up/Dn] Switch field/button | "
            "[Enter] Next/Submit | [Esc] Cancel without changes",
            style=tokens.secondary,
        )
        return Panel(
            body,
            title=f"Human Review Confirmation - {inc_id} (v{modal.get('target_version')})",
            border_style=tokens.border_modal,
            box=pbox,
        )

    # ------------------------------------------------------------------
    # Secondary Tabs: Health, AI Model Config, Telegram Dispatcher
    # ------------------------------------------------------------------

    def _health_table(self, snapshot: Mapping[str, Any]) -> RenderableType:
        tokens = self._tokens()
        services = snapshot.get("services", [])
        checked_at = snapshot.get("checked_at_local", "-")
        note = Text(
            f"Read-only container probe (last checked: {checked_at} | press [U] to refresh). "
            "Process connectivity does not imply live synthetic banking health.\n",
            style=tokens.secondary,
        )
        if not services:
            msg = Text()
            msg.append(f"Container Status: {snapshot.get('status')}\n", style=tokens.warning)
            msg.append(
                f"Detail: {snapshot.get('reason', 'No health data available.')}\n"
                "Next action: run ./scripts/lab_up.sh if you wish to start the Docker simulation stack.",
                style=tokens.secondary,
            )
            return Group(note, msg)

        table = Table(expand=True, box=self._table_box())
        table.add_column("Service")
        table.add_column("Container State")
        table.add_column("Health")
        for service in services:
            st = str(service["state"])
            hl = str(service["health"])
            hl_style = (
                tokens.infra_healthy
                if st.lower() == "running" and hl.lower() in ("healthy", "not-reported")
                else tokens.critical
            )
            table.add_row(str(service["name"]), st, Text(hl, style=hl_style))
        return Group(note, table)

    def _current_llm_config(self) -> dict[str, str]:
        vals = self.env_manager.read_all()
        provider_key = (vals.get("LLM_PROVIDER") or "openrouter").strip().lower()
        preset = PROVIDER_PRESETS.get(provider_key, PROVIDER_PRESETS["custom"])
        base_url = vals.get("LLM_BASE_URL") or preset["base_url"] or OPENROUTER_BASE_URL
        key_env = preset["key_env"]
        api_key = vals.get(key_env) or vals.get("OPENROUTER_API_KEY") or vals.get("LLM_API_KEY") or ""
        model = vals.get("LLM_MODEL") or preset["default_model"] or OPENROUTER_MODEL
        return {
            "provider_key": provider_key,
            "provider_name": preset["name"],
            "base_url": base_url,
            "key_env": key_env,
            "api_key": api_key,
            "model": model,
        }

    def _model_panel(self, snapshot: Mapping[str, Any], active_model: str) -> RenderableType:
        tokens = self._tokens()
        cfg = self._current_llm_config()
        table = Table.grid(padding=(0, 2))
        table.add_column(style=tokens.secondary)
        table.add_column(style=tokens.primary)
        table.add_row("Provider API", f"{cfg['provider_name']} ({cfg['provider_key']})")
        table.add_row("API Base URL", cfg["base_url"] or "NOT CONFIGURED")
        api_status = f"CONFIGURED ({mask_secret(cfg['api_key'])})" if cfg["api_key"] else "EMPTY (Offline / Deterministic Rule Mode)"
        table.add_row("API Key", api_status)
        table.add_row("Configured model", cfg["model"])
        table.add_row("Active model", active_model if active_model != "N/A" else cfg["model"])
        catalog_info = (
            f"{len(self.fetched_models)} models loaded from API"
            if self.fetched_models
            else "Not loaded (press [F] to fetch from API)"
        )
        table.add_row("Available models", catalog_info)
        table.add_row("Last API check", self.last_model_check)
        table.add_row("", "")
        if snapshot.get("status") != "OK":
            table.add_row("C15 metrics", str(snapshot.get("status")))
            table.add_row("Metrics source", str(snapshot.get("source")))
            table.add_row("Accounting note", "No values fabricated.")
        else:
            metrics = snapshot["metrics"]
            table.add_row("Tracked incidents", str(metrics.get("total_incidents_tracked", "N/A")))
            table.add_row("Total tokens", str(metrics.get("total_tokens_consumed", "N/A")))
            table.add_row("Shadow cost USD", str(metrics.get("total_shadow_cost_usd", "N/A")))
            table.add_row("P95 intake to dossier ms", str(metrics.get("p95_intake_to_dossier_ms", "N/A")))

        controls = Text(
            "\nModel & API Configuration:\n"
            "  [P] Select API Provider   [K] Set API Key   [F] Fetch & Select Model from API\n"
            "  [M] Manual Model Input    [T] Test Conn.    [X] Reset to Default Offline",
            style=tokens.accent,
        )
        return Group(table, controls)

    def _telegram_panel(self) -> RenderableType:
        tokens = self._tokens()
        mode = "ACTIVE OUTBOUND" if self.telegram.configured else "DRY-RUN"
        details = Text()
        details.append(f"Status: {mode}\n", style=tokens.infra_healthy if self.telegram.configured else tokens.warning)
        details.append(f"Bot Token : {mask_secret(self.telegram.bot_token)}\n", style=tokens.primary)
        details.append(f"Chat ID   : {self.telegram.chat_id or 'NOT CONFIGURED'}\n", style=tokens.primary)
        details.append(f"Last Test : {self.last_telegram_check}\n\n", style=tokens.secondary)
        details.append("Security Policy:\n", style=tokens.primary_bold)
        details.append(
            "  Direction: outbound notification only\n"
            "  Inbound listener: DISABLED\n"
            "  Remote command execution: NOT IMPLEMENTED\n"
            "  Credentials synced to .env (TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID).\n\n",
            style=tokens.secondary,
        )
        details.append(
            "Telegram Configuration:\n"
            "  [K] Set Bot Token   [C] Set / Detect Chat ID   [T] Test Bot & Send Alert   [X] Reset Dry-Run",
            style=tokens.accent,
        )
        return details

    def _action_bar(self, snapshot: DashboardSnapshot | None = None) -> Text:
        tokens = self._tokens()
        snap = snapshot or self.repository.coordinator.current_snapshot
        safe_notice = sanitize_terminal_text(self.notice, max_chars=140, empty_placeholder="")

        if self.selected_incident_id:
            vm = snap.by_incident_id.get(self.selected_incident_id) if snap else None
            if vm is not None and not vm.review_eligibility.eligible:
                if not vm.dossier_available:
                    return Text(
                        f"[DOSSIER PENDING - {vm.lifecycle_state}]  [Tab] LENS  [U] REFRESH  [B/Esc] BACK  [?] HELP  [Q] QUIT | {safe_notice}",
                        style=tokens.warning,
                    )
                if vm.review_eligibility.lock_code == "REVIEWER_UNAUTHORIZED":
                    return Text(
                        f"[REVIEW DISABLED - UNAUTHORIZED ROLE]  [Tab] LENS  [G] GRAFANA  [B/Esc] BACK  [?] HELP  [Q] QUIT | {safe_notice}",
                        style=tokens.critical,
                    )
                return Text(
                    f"[REVIEW LOCKED - FINALIZED ({vm.lifecycle_state})]  [Tab] LENS  [G] GRAFANA  [B/Esc] BACK  [?] HELP  [Q] QUIT | {safe_notice}",
                    style=tokens.warning,
                )
            inc = self.store.get_incident(self.selected_incident_id)
            if inc and inc.get("current_state") != "HUMAN_REVIEW":
                return Text(
                    f"[REVIEW LOCKED - FINALIZED ({inc.get('current_state')})]  [Tab] LENS  [G] GRAFANA  [B/Esc] BACK  [Q] QUIT",
                    style=tokens.warning,
                )
            return Text(
                f"[A] APPROVE  [R] REJECT  [C] CORRECT  [E] ESCALATE  [Tab] LENS  [G] GRAFANA  [B/Esc] BACK  [?] HELP  [Q] QUIT | {safe_notice}",
                style=tokens.warning,
            )

        if self.view == "model":
            return Text(
                f"[P] PROVIDER  [K] API KEY  [F] FETCH MODEL  [M] MANUAL  [T] TEST  [X] RESET  [?] HELP | {safe_notice}",
                style=tokens.primary_bold,
            )
        if self.view == "telegram":
            return Text(
                f"[K] BOT TOKEN  [C] CHAT ID  [T] TEST ALERT  [X] RESET DRY-RUN  [?] HELP | {safe_notice}",
                style=tokens.primary_bold,
            )
        if self.focus == "list":
            return Text(
                f"[Up/Dn] SELECT ROW  [Enter/O] OPEN  [G] GRAFANA  [Left/Tab] TO MENU  [U] REFRESH  [?] HELP  [Q] QUIT | {safe_notice}",
                style=tokens.primary_bold,
            )
        return Text(
            f"[Up/Dn] SWITCH MENU  [Right/Enter/Tab] INCIDENT LIST  [1-5] JUMP  [U] REFRESH  [?] HELP  [Q] QUIT | {safe_notice}",
            style=tokens.primary_bold,
        )

    # ------------------------------------------------------------------
    # Actions & Interactive Configuration Helpers
    # ------------------------------------------------------------------

    def _open_grafana_for_selected(self) -> None:
        """Open Grafana dashboard zoomed to the selected incident's anomaly time window."""
        snap = self.repository.coordinator.current_snapshot or self.refresh_snapshot()
        incident: Mapping[str, Any] | None = None
        dossier: Mapping[str, Any] | None = None
        if self.selected_incident_id:
            vm = snap.by_incident_id.get(self.selected_incident_id)
            if vm and vm.raw_dossier:
                incident = vm.raw_incident
                dossier = vm.raw_dossier
            else:
                dossier = self.repository.latest_dossier(self.selected_incident_id)
                incident = self.repository.store.get_incident(self.selected_incident_id)
        elif self.view in ("active", "archive"):
            rows = self._entries_for_current_tab(snap)
            if rows and 0 <= self.selected_index < len(rows):
                vm = rows[self.selected_index]
                incident = vm.raw_incident
                dossier = vm.raw_dossier or {"service_id": vm.primary_service, "event_time": vm.alert_received_at}

        if not dossier:
            self.notice = "Select an incident first to open Grafana."
            return

        url = build_grafana_incident_url(incident, dossier)
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        svc = sanitize_terminal_text(dossier.get("service_id") or (incident or {}).get("service_id") or "unknown", max_chars=48)
        if opened:
            self.notice = f"Grafana opened ({svc}): {url}"
        else:
            self.notice = f"Open Grafana URL ({svc}): {url}"

    def _select_by_index(self) -> None:
        snap = self.refresh_snapshot()
        rows = self._entries_for_current_tab(snap)
        if not rows:
            self.notice = "No incidents available to open."
            return
        if 0 <= self.selected_index < len(rows):
            selected = rows[self.selected_index]
            self.selected_incident_id = selected.incident_id
            self.highlighted_incident_id = selected.incident_id
            self.viewed_dossier_version = selected.dossier_version
            self.viewed_dossier_hash = selected.dossier_hash
            self.detail_section = "all"
            self.detail_return_stack.clear()
            self.selected_hypothesis_idx = 0
            self.selected_evidence_idx = 0
            self.detail_scroll_offset = 0
            self.notice = f"Incident {self.selected_incident_id} opened (Revision v{selected.dossier_version})."
        else:
            self.notice = "Invalid incident selection."

    def _jump_hypothesis_to_evidence(self) -> None:
        """Follow selected hypothesis's supporting/contradicting evidence reference (Work Package I5)."""
        if not self.selected_incident_id:
            return
        snap = self.repository.coordinator.current_snapshot or self.refresh_snapshot()
        vm = snap.by_incident_id.get(self.selected_incident_id)
        if vm is None or not vm.hypotheses:
            self.notice = "No hypotheses available for evidence reference resolution."
            return
        h_idx = max(0, min(self.selected_hypothesis_idx, len(vm.hypotheses) - 1))
        h_vm = vm.hypotheses[h_idx]
        ref_ids = list(h_vm.supporting_ids) + list(h_vm.contradicting_ids)
        if not ref_ids:
            self.notice = f"Hypothesis #{h_vm.rank} has no linked supporting or contradicting evidence IDs."
            return
        target_eid = ref_ids[0]
        ev_idx = next((i for i, e in enumerate(vm.evidence_items) if e.evidence_id == target_eid), None)
        self.detail_return_stack.append((self.detail_section, self.detail_scroll_offset))
        self.detail_section = "evidence"
        self.detail_scroll_offset = 0
        if ev_idx is not None:
            self.selected_evidence_idx = ev_idx
            self.notice = f"Resolved #{h_vm.rank} -> evidence {target_eid} (press [B/Esc] to return to Hypotheses)."
        else:
            self.notice = (
                f"Reference '{target_eid}' from #{h_vm.rank} is UNRESOLVED in authorized telemetry "
                "(shown in Evidence Lineage warnings)."
            )

    def _set_mouse_tracking(self, enabled: bool) -> None:
        """Enable or disable SGR/X10 mouse tracking to block trackpad wheel scrolling."""
        if not self.console.is_terminal or not sys.stdin.isatty():
            return
        try:
            seq = "\x1b[?1000h\x1b[?1006h" if enabled else "\x1b[?1006l\x1b[?1000l"
            sys.stdout.write(seq)
            sys.stdout.flush()
        except OSError:
            pass

    def _prompt_text(self, prompt: str, *, password: bool = False, default: str = "") -> str:
        """Temporarily suspend cbreak & mouse tracking, prompt user cleanly, and restore cbreak."""
        self._set_mouse_tracking(False)
        if self._tty_fd is not None and self._saved_termios is not None:
            try:
                termios.tcsetattr(self._tty_fd, termios.TCSADRAIN, self._saved_termios)
            except termios.error:
                pass
        self.console.clear()
        self.console.print(self.render())
        self.console.print()
        try:
            if default:
                return Prompt.ask(prompt, console=self.console, password=password, default=default).strip()
            return Prompt.ask(prompt, console=self.console, password=password).strip()
        finally:
            if self._tty_fd is not None and self._saved_termios is not None:
                try:
                    tty.setcbreak(self._tty_fd)
                except termios.error:
                    pass
            self._set_mouse_tracking(True)

    def _prompt_cancellable(
        self,
        prompt: str,
        *,
        password: bool = False,
        default: str = "",
        empty_cancels: bool = True,
    ) -> str | None:
        """Prompt user with explicit cancel support (Enter/empty, 'batal', 'cancel', or Ctrl+C)."""
        val = self._prompt_text(prompt, password=password, default=default)
        if empty_cancels and not val:
            return None
        if val.strip().lower() in ("batal", "cancel", "esc"):
            return None
        return val

    def _configure_model_provider(self) -> None:
        self._set_mouse_tracking(False)
        self.console.clear()
        table = Table(title="Select AI API Provider", expand=False, box=self._table_box())
        table.add_column("No.", justify="right")
        table.add_column("Provider")
        table.add_column("Default Base URL")
        keys = list(PROVIDER_PRESETS.keys())
        for idx, pkey in enumerate(keys, 1):
            p = PROVIDER_PRESETS[pkey]
            table.add_row(str(idx), p["name"], p["base_url"] or "(custom URL)")
        self.console.print(table)
        try:
            choice = Prompt.ask("Select provider number (1-5, or press Enter to cancel)", console=self.console, default="").strip()
            if not choice:
                self.notice = "Provider selection cancelled."
                return
            try:
                selected_key = keys[int(choice) - 1]
            except (ValueError, IndexError):
                self.notice = "Invalid provider number."
                return
            preset = PROVIDER_PRESETS[selected_key]
            base_url = preset["base_url"]
            if selected_key == "custom" or not base_url:
                base_url = Prompt.ask("Enter OpenAI-compatible Base URL (e.g., https://api.groq.com/openai/v1)", console=self.console).strip()
            else:
                custom_override = Prompt.ask("Base URL", console=self.console, default=base_url).strip()
                if custom_override:
                    base_url = custom_override
            updates: dict[str, str] = {
                "LLM_PROVIDER": selected_key,
                "LLM_BASE_URL": base_url.rstrip("/"),
            }
            if preset["default_model"]:
                updates["LLM_MODEL"] = preset["default_model"]
            self.env_manager.set_values(updates)
            self.fetched_models = []
            self.notice = f"Provider set to {preset['name']} ({updates['LLM_BASE_URL']})."
        except (KeyboardInterrupt, EOFError, ValueError) as exc:
            self.notice = f"Provider configuration cancelled: {type(exc).__name__}"
        finally:
            self._set_mouse_tracking(True)

    def _configure_model_api_key(self) -> None:
        cfg = self._current_llm_config()
        try:
            key_val = self._prompt_cancellable(
                f"Enter API Key for {cfg['provider_name']} ({cfg['key_env']}) "
                "[Enter/cancel = Cancel, type 'CLEAR' = Empty]",
                password=True,
                empty_cancels=True,
            )
            if key_val is None:
                self.notice = "API Key setup cancelled (existing configuration preserved)."
                return
            if key_val.strip().upper() in ("HAPUS", "CLEAR"):
                key_val = ""
            updates = {cfg["key_env"]: key_val}
            if cfg["provider_key"] == "openrouter":
                updates["OPENROUTER_API_KEY"] = key_val
            self.env_manager.set_values(updates)
            if key_val:
                self.notice = f"API Key {cfg['key_env']} saved ({mask_secret(key_val)})."
            else:
                self.notice = f"API Key {cfg['key_env']} cleared (offline/mock mode)."
        except (KeyboardInterrupt, EOFError, ValueError):
            self.notice = "API Key configuration cancelled."

    def _render_model_picker(
        self,
        models: list[str],
        selected_idx: int,
        scroll_offset: int,
        *,
        keyword: str = "",
        total_count: int = 0,
        height: int | None = None,
        active_model: str = "",
    ) -> Panel:
        tokens = self._tokens()
        term_h = height or self.console.size.height
        max_visible = max(5, term_h - 10)
        total = len(models)
        sel_mark = self._sel_glyph()
        if total == 0:
            body: RenderableType = Text(
                "No models match the filter.\nPress [/] to edit filter or [Esc/B] to cancel.",
                style=tokens.warning,
            )
        else:
            sel = max(0, min(selected_idx, total - 1))
            if sel < scroll_offset:
                scroll_offset = sel
            elif sel >= scroll_offset + max_visible:
                scroll_offset = sel - max_visible + 1
            scroll_offset = max(0, min(scroll_offset, max(0, total - max_visible)))
            visible = models[scroll_offset : scroll_offset + max_visible]

            table = Table(expand=True, show_header=True, box=self._table_box())
            table.add_column("No.", justify="right", width=6, no_wrap=True)
            table.add_column("Model ID", no_wrap=True)
            table.add_column("Status", width=10, no_wrap=True)
            for offset_i, m_id in enumerate(visible):
                actual_i = scroll_offset + offset_i
                is_sel = actual_i == sel
                is_active = m_id == active_model
                no_str = f"{sel_mark} {actual_i + 1}" if is_sel else f"  {actual_i + 1}"
                status_str = "ACTIVE" if is_active else ""
                row_style = tokens.selected_row if is_sel else (tokens.infra_healthy if is_active else tokens.primary)
                table.add_row(no_str, sanitize_terminal_text(m_id, max_chars=96), status_str, style=row_style)

            end_i = scroll_offset + len(visible)
            info = Text(
                f"Showing {scroll_offset + 1}-{end_i} of {total} models"
                + (f" (filter: '{keyword}', total {total_count})" if keyword else "")
                + "\nNavigation: [Up/Dn or j/k] Select  |  [PgUp/PgDn] Page Scroll  |  [/] Filter  |  [Enter] Save  |  [Esc/B] Cancel",
                style=tokens.secondary,
            )
            body = Group(table, info)

        return Panel(
            body,
            title="Select Model from API (Arrow Key Scrollable)",
            border_style=tokens.border_focused,
            box=self._panel_box(),
        )

    def _fetch_and_select_model(self) -> None:
        cfg = self._current_llm_config()
        self.notice = f"Fetching model list from {cfg['base_url']}..."
        res = self.model_catalog.fetch_models(cfg["base_url"], cfg["api_key"])
        if res["status"] != "OK":
            err_clean = sanitize_terminal_text(res.get("error"), max_chars=80)
            self.last_model_check = f"ERROR: {err_clean[:65]}"
            self.notice = f"Failed to fetch models: {err_clean}"
            return

        self.fetched_models = list(res["models"])
        self.last_model_check = f"OK ({res['count']} models available, {res['latency_ms']} ms)"
        if not self.fetched_models:
            self.notice = "API returned no models."
            return

        keyword = ""
        filtered = list(self.fetched_models)
        selected_idx = 0
        if cfg["model"] in filtered:
            selected_idx = filtered.index(cfg["model"])
        scroll_offset = 0

        try:
            while True:
                term_h = self.console.size.height
                max_visible = max(5, term_h - 10)
                if filtered:
                    selected_idx = max(0, min(selected_idx, len(filtered) - 1))
                    if selected_idx < scroll_offset:
                        scroll_offset = selected_idx
                    elif selected_idx >= scroll_offset + max_visible:
                        scroll_offset = selected_idx - max_visible + 1
                    scroll_offset = max(0, min(scroll_offset, max(0, len(filtered) - max_visible)))

                picker_panel = self._render_model_picker(
                    filtered,
                    selected_idx,
                    scroll_offset,
                    keyword=keyword,
                    total_count=len(self.fetched_models),
                    height=term_h,
                    active_model=cfg["model"],
                )
                if self._screen is not None:
                    self._screen.update(picker_panel)
                else:
                    self.console.clear()
                    self.console.print(picker_panel)

                raw_key = self._read_key(timeout=None)
                key = raw_key.upper()
                if key in ("ESC", "B", "Q"):
                    self.notice = "Model selection cancelled."
                    return
                if key in ("UP", "K") and filtered:
                    selected_idx = (selected_idx - 1) % len(filtered)
                elif key in ("DOWN", "J") and filtered:
                    selected_idx = (selected_idx + 1) % len(filtered)
                elif key == "PGUP" and filtered:
                    selected_idx = max(0, selected_idx - max_visible)
                elif key == "PGDN" and filtered:
                    selected_idx = min(len(filtered) - 1, selected_idx + max_visible)
                elif raw_key == "/":
                    self._set_mouse_tracking(False)
                    try:
                        self.console.clear()
                        self.console.print(picker_panel)
                        kw = Prompt.ask(
                            "Filter keywords (leave empty to show all)",
                            console=self.console,
                            default="",
                        ).strip().lower()
                        keyword = kw
                        filtered = (
                            [m for m in self.fetched_models if keyword in m.lower()]
                            if keyword
                            else list(self.fetched_models)
                        )
                        selected_idx = 0
                        scroll_offset = 0
                    finally:
                        self._set_mouse_tracking(True)
                elif key == "ENTER" and filtered:
                    chosen = filtered[selected_idx]
                    self.env_manager.set_values({"LLM_MODEL": chosen})
                    self.notice = f"Active model updated to '{chosen}'."
                    return
        except (KeyboardInterrupt, EOFError, ValueError):
            self.notice = "Model selection cancelled."

    def _configure_model_manual(self) -> None:
        cfg = self._current_llm_config()
        try:
            model_name = self._prompt_cancellable(
                f"Enter model name/ID [Enter/cancel = Cancel, current: {cfg['model']}]",
                empty_cancels=True,
            )
            if model_name is None:
                self.notice = "Model configuration cancelled (model unchanged)."
                return
            self.env_manager.set_values({"LLM_MODEL": model_name})
            self.notice = f"Active model set to '{model_name}'."
        except (KeyboardInterrupt, EOFError, ValueError):
            self.notice = "Model configuration cancelled."

    def _test_model_connection(self) -> None:
        cfg = self._current_llm_config()
        res = self.model_catalog.test_connection(cfg["base_url"], cfg["api_key"], cfg["model"])
        if res["status"] == "OK":
            if res.get("model_found"):
                self.last_model_check = f"CONNECTED ({res['latency_ms']} ms, verified model)"
                self.notice = f"Connection to {cfg['provider_name']} OK! Model '{cfg['model']}' available."
            else:
                self.last_model_check = f"CONNECTED ({res['latency_ms']} ms, custom model)"
                self.notice = sanitize_terminal_text(res.get("error") or "Endpoint connection successful.", max_chars=96)
        else:
            err_s = sanitize_terminal_text(res.get("error"), max_chars=80)
            self.last_model_check = f"FAILED ({err_s[:60]})"
            self.notice = f"Connection test failed: {err_s}"

    def _reset_model_config(self) -> None:
        self.env_manager.set_values({
            "LLM_PROVIDER": "openrouter",
            "LLM_BASE_URL": OPENROUTER_BASE_URL,
            "LLM_MODEL": OPENROUTER_MODEL,
            "OPENROUTER_API_KEY": "",
            "LLM_API_KEY": "",
        })
        self.fetched_models = []
        self.last_model_check = "Reset to offline/mock mode ($0.00)"
        self.notice = "AI configuration reset to default offline baseline."

    def _configure_telegram_token(self) -> None:
        try:
            token = self._prompt_cancellable(
                "Enter Telegram Bot Token (from @BotFather) [Enter/cancel = Cancel, type 'CLEAR' = Dry-run]",
                password=True,
                empty_cancels=True,
            )
            if token is None:
                self.notice = "Bot Token configuration cancelled (existing token preserved)."
                return
            if token.strip().upper() in ("HAPUS", "CLEAR"):
                token = ""
            self.env_manager.set_values({"TELEGRAM_BOT_TOKEN": token})
            self.telegram = TelegramDispatcher(bot_token=token, chat_id=self.telegram.chat_id)
            if token:
                check = self.telegram_helper.test_bot(token)
                if check["status"] == "OK":
                    self.last_telegram_check = f"Bot verified: @{check['username']}"
                    self.notice = f"Bot Token saved (@{check['username']})."
                else:
                    err_s = sanitize_terminal_text(check.get("error"), max_chars=80)
                    self.last_telegram_check = f"Token saved, verification: {err_s}"
                    self.notice = f"Token saved but verification failed: {err_s}"
            else:
                self.last_telegram_check = "Dry-run (token cleared)"
                self.notice = "Bot Token cleared (DRY-RUN mode)."
        except (KeyboardInterrupt, EOFError, ValueError):
            self.notice = "Bot Token input cancelled."

    def _configure_telegram_chat_id(self) -> None:
        self._set_mouse_tracking(False)
        try:
            self.console.clear()
            discovered: list[tuple[str, str]] = []
            if self.telegram.bot_token:
                res = self.telegram_helper.discover_chats(self.telegram.bot_token)
                if res["status"] == "OK" and res["chats"]:
                    discovered = res["chats"]
                    table = Table(title="Detected Chat IDs from Bot getUpdates", box=self._table_box())
                    table.add_column("No.", justify="right")
                    table.add_column("Chat ID")
                    table.add_column("Info")
                    for idx, (cid, desc) in enumerate(discovered, 1):
                        table.add_row(str(idx), sanitize_terminal_text(cid, max_chars=40), sanitize_terminal_text(desc, max_chars=80))
                    self.console.print(table)
                else:
                    self.console.print(Text("No incoming messages to bot yet or unable to detect. Enter Chat ID manually."))

            val = Prompt.ask(
                "Select number from list or enter Chat ID manually (e.g., -1001234567890)",
                console=self.console,
                default=self.telegram.chat_id or "",
            ).strip()
            if val.isdigit() and 1 <= int(val) <= len(discovered):
                chat_id = discovered[int(val) - 1][0]
            else:
                chat_id = val

            self.env_manager.set_values({"TELEGRAM_CHAT_ID": chat_id})
            self.telegram = TelegramDispatcher(bot_token=self.telegram.bot_token, chat_id=chat_id)
            self.notice = f"Telegram Chat ID set to '{chat_id or 'EMPTY'}'."
        except (KeyboardInterrupt, EOFError, ValueError) as exc:
            self.notice = f"Chat ID configuration cancelled: {type(exc).__name__}"
        finally:
            self._set_mouse_tracking(True)

    def _test_telegram_alert(self) -> None:
        if not self.telegram.bot_token:
            self.last_telegram_check = "ERROR: Bot Token is empty."
            self.notice = "Configure Bot Token first using key [K]."
            return
        bot_check = self.telegram_helper.test_bot(self.telegram.bot_token)
        if bot_check["status"] != "OK":
            err_s = sanitize_terminal_text(bot_check.get("error"), max_chars=80)
            self.last_telegram_check = f"FAILED: {err_s}"
            self.notice = f"Bot verification failed: {err_s}"
            return

        if not self.telegram.chat_id:
            self.last_telegram_check = f"Bot @{bot_check['username']} OK, Chat ID empty."
            self.notice = f"Bot @{bot_check['username']} valid! Press [C] to configure Chat ID."
            return

        test_dossier = {
            "incident_id": "inc-test-telegram-ping",
            "severity": "low",
            "service_id": "sre-command-center",
            "review_summary": {"status": "PENDING_REVIEW"},
            "impact_summary": {
                "affected_services": ["sre-command-center"],
                "observed_symptoms": "Outbound Telegram connectivity test from SRE Investigation Console.",
            },
            "hypotheses": [{"statement": "Outbound Telegram notification test", "confidence_score": 0.50}],
            "sop_citations": [{"doc_id": "SOP-TEST-001", "section_path": "Outbound Alert Verification"}],
        }
        res = self.telegram.dispatch_pending_review(test_dossier)
        if res.delivered:
            self.last_telegram_check = f"DELIVERED to {self.telegram.chat_id} (@{bot_check['username']})"
            self.notice = f"Test alert delivered to Chat ID {self.telegram.chat_id}."
        else:
            self.last_telegram_check = f"{res.status}: {res.reason}"
            self.notice = f"Test alert failed ({res.reason})."

    def _reset_telegram_config(self) -> None:
        self.env_manager.set_values({"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})
        self.telegram = TelegramDispatcher(bot_token="", chat_id="")
        self.last_telegram_check = "Reset to DRY-RUN mode"
        self.notice = "Telegram configuration cleared (DRY-RUN mode)."

    # ------------------------------------------------------------------
    # Keyboard Reading & Deterministic Event Dispatch (Work Package D2, D3)
    # ------------------------------------------------------------------

    def _read_key(self, timeout: float | None = 2.0, *, raw_text_mode: bool = False) -> str:
        """Read a single keypress, arrow key, or escape sequence; return 'REFRESH' on timeout."""
        if not sys.stdin.isatty() or not _HAS_TERMIOS:
            try:
                line = sys.stdin.readline()
                if not line:
                    return "Q"
                stripped = line.rstrip("\r\n")
                if raw_text_mode:
                    if stripped.upper() in ("ESC", "TAB", "ENTER", "BACKSPACE", "UP", "DOWN"):
                        return stripped.upper()
                    return stripped
                cmd = stripped.strip().upper()
                if cmd in (
                    "UP", "DOWN", "LEFT", "RIGHT", "PGUP", "PGDN", "TAB", "ENTER", "ESC",
                    "BACKSPACE", "Q", "B", "O", "A", "R", "C", "E", "P", "K", "F", "M", "T", "X",
                    "G", "U", "I", "?", "[", "]",
                ):
                    return cmd
                return cmd[:1] if cmd else "ENTER"
            except (OSError, EOFError):
                return "Q"

        fd = sys.stdin.fileno()
        manage_cbreak_locally = self._tty_fd is None
        local_saved = termios.tcgetattr(fd) if manage_cbreak_locally else None
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        try:
            if manage_cbreak_locally:
                tty.setcbreak(fd)
            while True:
                if self._pending_byte is not None:
                    b = self._pending_byte
                    self._pending_byte = None
                else:
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return "REFRESH"
                        ready, _, _ = select.select([fd], [], [], remaining)
                        if not ready:
                            return "REFRESH"
                    b = os.read(fd, 1)
                if not b:
                    return "Q"
                if b == b"\x1b":
                    r, _, _ = select.select([fd], [], [], 0.05)
                    if r:
                        b2 = os.read(fd, 1)
                        if b2 in (b"[", b"O"):
                            r2, _, _ = select.select([fd], [], [], 0.05)
                            if r2:
                                b3 = os.read(fd, 1)
                                # Consume & discard SGR mouse events (\x1b[<btn;x;yM/m)
                                if b2 == b"[" and b3 == b"<":
                                    for _ in range(64):
                                        if not select.select([fd], [], [], 0.02)[0]:
                                            break
                                        mb = os.read(fd, 1)
                                        if mb in (b"M", b"m"):
                                            break
                                    continue
                                # Consume & discard legacy X10 mouse events
                                if b2 == b"[" and b3 == b"M":
                                    for _ in range(3):
                                        if select.select([fd], [], [], 0.02)[0]:
                                            os.read(fd, 1)
                                    continue
                                if b3 == b"A":
                                    return "UP"
                                if b3 == b"B":
                                    return "DOWN"
                                if b3 == b"C":
                                    return "RIGHT"
                                if b3 == b"D":
                                    return "LEFT"
                                if b3 == b"Z":
                                    return "SHIFT_TAB"
                                if b3 == b"5":
                                    while select.select([fd], [], [], 0.01)[0]:
                                        if os.read(fd, 1) == b"~":
                                            break
                                    return "PGUP"
                                if b3 == b"6":
                                    while select.select([fd], [], [], 0.01)[0]:
                                        if os.read(fd, 1) == b"~":
                                            break
                                    return "PGDN"
                                while select.select([fd], [], [], 0.01)[0]:
                                    extra = os.read(fd, 1)
                                    if extra == b"~":
                                        break
                        return "ESC"
                    return "ESC"
                if b in (b"\r", b"\n"):
                    return "ENTER"
                if b == b"\t":
                    return "TAB"
                if b in (b"\x7f", b"\x08"):
                    return "BACKSPACE"
                if b == b"\x03":
                    raise KeyboardInterrupt
                # Handle multi-byte UTF-8 input cleanly
                first = b[0]
                extra_bytes = 0
                if (first & 0xE0) == 0xC0:
                    extra_bytes = 1
                elif (first & 0xF0) == 0xE0:
                    extra_bytes = 2
                elif (first & 0xF8) == 0xF0:
                    extra_bytes = 3
                buf = bytearray(b)
                for _ in range(extra_bytes):
                    if select.select([fd], [], [], 0.02)[0]:
                        buf.extend(os.read(fd, 1))
                ch = bytes(buf).decode("utf-8", errors="ignore")
                if raw_text_mode:
                    # Coalesce burst/pasted printable ASCII bytes into one token to avoid per-char redraw lag
                    out_chars = [ch]
                    while len(out_chars) < 256 and select.select([fd], [], [], 0.0)[0]:
                        peek_b = os.read(fd, 1)
                        if not peek_b:
                            break
                        pb = peek_b[0]
                        if 32 <= pb < 127:
                            out_chars.append(chr(pb))
                        else:
                            # Put control byte back via unconsumed pending buffer
                            self._pending_byte = peek_b
                            break
                    return "".join(out_chars)
                if ch == " ":
                    return "ENTER"
                return ch.upper()
        finally:
            if manage_cbreak_locally and local_saved is not None:
                termios.tcsetattr(fd, termios.TCSADRAIN, local_saved)

    def _handle_review_modal_key(self, raw_key: str) -> None:
        """Process keypresses strictly inside the review confirmation modal (isolates global shortcuts)."""
        modal = self.review_modal
        if modal is None:
            return

        if raw_key == "REFRESH":
            self.refresh_snapshot()
            return
        if raw_key == "ESC":
            self.cancel_review_modal()
            return

        fields: list[str] = list(modal.get("fields") or ["rationale", "confirm", "cancel"])
        focus_idx = max(0, min(int(modal.get("focus_idx", 0)), len(fields) - 1))
        focused_field = fields[focus_idx]

        if raw_key in ("TAB", "DOWN"):
            modal["focus_idx"] = (focus_idx + 1) % len(fields)
            self._skip_next_render_refresh = True
            return
        if raw_key in ("SHIFT_TAB", "UP"):
            modal["focus_idx"] = (focus_idx - 1) % len(fields)
            self._skip_next_render_refresh = True
            return

        if raw_key == "ENTER":
            if focused_field == "cancel":
                self.cancel_review_modal()
                return
            if focused_field == "confirm":
                self.submit_review_modal()
                return
            # On a text field, Enter advances focus to the next field / Confirm button (never auto-submits!)
            modal["focus_idx"] = min(len(fields) - 1, focus_idx + 1)
            self._skip_next_render_refresh = True
            return

        if focused_field in ("rationale", "corrected_hypothesis", "escalation_target"):
            cur_val = str(modal.get(focused_field) or "")
            if raw_key == "BACKSPACE":
                modal[focused_field] = cur_val[:-1]
                self._skip_next_render_refresh = True
            elif len(raw_key) >= 1 and raw_key not in ("LEFT", "RIGHT", "PGUP", "PGDN"):
                # Sanitize control sequences immediately while preserving printable user input
                cleaned = "".join(c for c in raw_key if c >= " " and c != "\x7f")
                if cleaned:
                    modal[focused_field] = (cur_val + cleaned)[:512]
                    self._skip_next_render_refresh = True
        elif focused_field in ("confirm", "cancel"):
            if raw_key in ("LEFT", "RIGHT"):
                modal["focus_idx"] = fields.index("cancel" if focused_field == "confirm" else "confirm")
                self._skip_next_render_refresh = True

    def handle_key(self, raw_key: str) -> bool:
        """Process a single navigation or modal event; return False when quitting."""
        if raw_key == "REFRESH":
            self.refresh_snapshot()
            return True

        # Modal focus trap: Help overlay
        if self.help_open:
            if raw_key.upper() in ("ESC", "B", "?", "ENTER", "Q"):
                self.help_open = False
                self.notice = "Closed help overlay."
            return True

        # Modal focus trap: Human Review confirmation
        if self.review_modal is not None:
            self._handle_review_modal_key(raw_key)
            return True

        key = raw_key.upper()
        if key == "Q":
            self.notice = "Console closed without automated actions."
            return False

        if raw_key == "?" or key == "?":
            self.help_open = True
            self.notice = "Opened keyboard & safety semantics reference."
            return True

        if key == "U":
            self.refresh_snapshot(force_probes=True)
            self.notice = "Refreshed authoritative state snapshot."
            return True

        snap = self.repository.coordinator.current_snapshot or self.refresh_snapshot()
        rows = self._entries_for_current_tab(snap)
        num_rows = len(rows)

        # Tab-specific configuration shortcuts on AI Model Config & Telegram Alerts
        if self.view == "model" and not self.selected_incident_id:
            if key == "P":
                self._configure_model_provider()
                return True
            if key == "K":
                self._configure_model_api_key()
                return True
            if key == "F":
                self._fetch_and_select_model()
                return True
            if key == "M":
                self._configure_model_manual()
                return True
            if key == "T":
                self._test_model_connection()
                return True
            if key == "X":
                self._reset_model_config()
                return True

        if self.view == "telegram" and not self.selected_incident_id:
            if key == "K":
                self._configure_telegram_token()
                return True
            if key == "C":
                self._configure_telegram_chat_id()
                return True
            if key == "T":
                self._test_telegram_alert()
                return True
            if key == "X":
                self._reset_telegram_config()
                return True

        if key in ("UP", "K"):
            if self.selected_incident_id:
                self.detail_scroll_offset = max(0, self.detail_scroll_offset - 2)
            elif self.focus == "menu":
                idx = self._MENU_ORDER.index(self.view)
                self.view = self._MENU_ORDER[(idx - 1) % len(self._MENU_ORDER)]
                self.selected_index = 0
                self._last_synced_index = 0
                self.highlighted_incident_id = None
                self.list_scroll_offset = 0
                self.detail_scroll_offset = 0
                self.notice = f"Menu: {self._main_title()}."
            elif self.focus == "list" and num_rows > 0:
                self.selected_index = (self.selected_index - 1) % num_rows
                self._last_synced_index = self.selected_index
                self.highlighted_incident_id = rows[self.selected_index].incident_id
                self.notice = f"Selected row {self.selected_index + 1} ({self.highlighted_incident_id})."
            return True

        if key in ("DOWN", "J"):
            if self.selected_incident_id:
                self.detail_scroll_offset += 2
            elif self.focus == "menu":
                idx = self._MENU_ORDER.index(self.view)
                self.view = self._MENU_ORDER[(idx + 1) % len(self._MENU_ORDER)]
                self.selected_index = 0
                self._last_synced_index = 0
                self.highlighted_incident_id = None
                self.list_scroll_offset = 0
                self.detail_scroll_offset = 0
                self.notice = f"Menu: {self._main_title()}."
            elif self.focus == "list" and num_rows > 0:
                self.selected_index = (self.selected_index + 1) % num_rows
                self._last_synced_index = self.selected_index
                self.highlighted_incident_id = rows[self.selected_index].incident_id
                self.notice = f"Selected row {self.selected_index + 1} ({self.highlighted_incident_id})."
            return True

        if key == "PGUP":
            if self.selected_incident_id or self.view not in ("active", "archive"):
                self.detail_scroll_offset = max(0, self.detail_scroll_offset - 6)
            elif self.focus == "list" and num_rows > 0:
                self.selected_index = max(0, self.selected_index - 5)
                self._last_synced_index = self.selected_index
                self.highlighted_incident_id = rows[self.selected_index].incident_id
            return True

        if key == "PGDN":
            if self.selected_incident_id or self.view not in ("active", "archive"):
                self.detail_scroll_offset += 6
            elif self.focus == "list" and num_rows > 0:
                self.selected_index = min(num_rows - 1, self.selected_index + 5)
                self._last_synced_index = self.selected_index
                self.highlighted_incident_id = rows[self.selected_index].incident_id
            return True

        if key in ("[", "]") and self.selected_incident_id:
            vm = snap.by_incident_id.get(self.selected_incident_id)
            delta = -1 if key == "[" else 1
            if vm is not None:
                if self.detail_section == "evidence" and vm.evidence_items:
                    self.selected_evidence_idx = (self.selected_evidence_idx + delta) % len(vm.evidence_items)
                    ev = vm.evidence_items[self.selected_evidence_idx]
                    self.notice = f"Selected evidence {ev.evidence_id} ({self.selected_evidence_idx + 1}/{len(vm.evidence_items)})."
                elif vm.hypotheses:
                    if self.detail_section not in ("hypotheses", "evidence"):
                        self.detail_section = "hypotheses"
                    self.selected_hypothesis_idx = (self.selected_hypothesis_idx + delta) % len(vm.hypotheses)
                    hy = vm.hypotheses[self.selected_hypothesis_idx]
                    self.notice = f"Selected hypothesis #{hy.rank} ({hy.hypothesis_id})."
            return True

        if key == "I" and self.selected_incident_id:
            self._jump_hypothesis_to_evidence()
            return True

        if key == "RIGHT":
            if not self.selected_incident_id and self.view in ("active", "archive") and num_rows > 0:
                self.focus = "list"
                self.notice = "Focused on incident list."
            return True

        if key in ("TAB", "SHIFT_TAB"):
            if self.selected_incident_id:
                cur_l = DETAIL_LENS_ORDER.index(self.detail_section) if self.detail_section in DETAIL_LENS_ORDER else 0
                step = -1 if key == "SHIFT_TAB" else 1
                self.detail_section = DETAIL_LENS_ORDER[(cur_l + step) % len(DETAIL_LENS_ORDER)]
                self.detail_scroll_offset = 0
                self.notice = f"Detail lens: {DETAIL_LENS_LABELS[self.detail_section]}."
            elif self.view in ("active", "archive") and num_rows > 0:
                self.focus = "list" if self.focus == "menu" else "menu"
                self.notice = f"Focus switched to {'incident list' if self.focus == 'list' else 'navigation menu'}."
            return True

        if key == "LEFT":
            if self.selected_incident_id:
                if self.detail_return_stack:
                    prev_sec, prev_off = self.detail_return_stack.pop()
                    self.detail_section = prev_sec
                    self.detail_scroll_offset = prev_off
                    self.notice = f"Returned to {DETAIL_LENS_LABELS.get(prev_sec, prev_sec)}."
                else:
                    self.selected_incident_id = None
                    self.detail_scroll_offset = 0
                    self.notice = "Returned to incident list."
            elif self.focus == "list":
                self.focus = "menu"
                self.notice = "Focused on navigation menu."
            return True

        if key in ("ENTER", "O"):
            if self.selected_incident_id and self.detail_section == "hypotheses" and key == "ENTER":
                self._jump_hypothesis_to_evidence()
                return True
            if not self.selected_incident_id and self.view in ("active", "archive"):
                if self.focus == "menu" and key == "ENTER" and num_rows > 0:
                    self.focus = "list"
                    self.notice = "Focused on incident list. Press [Enter] again to inspect incident."
                elif num_rows > 0:
                    self._select_by_index()
                else:
                    self.notice = "No incidents available in this tab."
            return True

        if key in ("B", "ESC"):
            if self.selected_incident_id:
                if self.detail_return_stack:
                    prev_sec, prev_off = self.detail_return_stack.pop()
                    self.detail_section = prev_sec
                    self.detail_scroll_offset = prev_off
                    self.notice = f"Returned to {DETAIL_LENS_LABELS.get(prev_sec, prev_sec)}."
                elif self.detail_section != "all":
                    self.detail_section = "all"
                    self.detail_scroll_offset = 0
                    self.notice = "Returned to full dossier view."
                else:
                    self.selected_incident_id = None
                    self.detail_scroll_offset = 0
                    self.notice = "Returned to incident list."
            elif self.focus == "list":
                self.focus = "menu"
                self.notice = "Returned to navigation menu."
            else:
                self.view = "active"
                self.selected_index = 0
                self._last_synced_index = 0
                self.list_scroll_offset = 0
                self.detail_scroll_offset = 0
            return True

        if key in ("1", "2", "3", "4", "5"):
            self.view = {
                "1": "active",
                "2": "archive",
                "3": "health",
                "4": "model",
                "5": "telegram",
            }[key]
            self.selected_incident_id = None
            self.detail_return_stack.clear()
            self.selected_index = 0
            self._last_synced_index = 0
            self.highlighted_incident_id = None
            self.list_scroll_offset = 0
            self.detail_scroll_offset = 0
            if self.view not in ("active", "archive"):
                self.focus = "menu"
            self.notice = f"Switched to tab {self._main_title()}."
            return True

        if key == "G":
            if self.selected_incident_id or self.view in ("active", "archive"):
                self._open_grafana_for_selected()
            else:
                self.notice = "Shortcut [G] is available in incident list or incident detail."
            return True

        if key in ("A", "R", "C", "E"):
            if self.selected_incident_id:
                self.open_review_modal(
                    {"A": "APPROVE", "R": "REJECT", "C": "CORRECT", "E": "ESCALATE"}[key]
                )
            else:
                self.notice = "Open an incident first ([Enter] or [O]) before starting a review."
            return True

        self.notice = f"Unrecognized key '{sanitize_terminal_text(key, max_chars=16)}'. Press [?] for keyboard reference."
        return True

    def _review_selected(self, action: str) -> None:
        """Programmatic / legacy prompt-driven fallback wrapper around version-bound review."""
        if not self.open_review_modal(action):
            return
        modal = self.review_modal
        if modal is None:
            return
        action_upper = action.upper()
        try:
            if action_upper == "CORRECT":
                corrected = self._prompt_cancellable("Corrected root-cause hypothesis [Enter/cancel = Cancel]")
                if corrected is None:
                    self.cancel_review_modal()
                    return
                modal["corrected_hypothesis"] = corrected
            elif action_upper == "ESCALATE":
                target = self._prompt_text("Escalation target", default="SRE_LEAD_ONCALL")
                modal["escalation_target"] = target or "SRE_LEAD_ONCALL"
            rationale = self._prompt_cancellable("Rationale (min 5 chars) [Enter/cancel = Cancel]")
            if rationale is None:
                self.cancel_review_modal()
                return
            modal["rationale"] = rationale
            self.submit_review_modal()
        except (KeyboardInterrupt, EOFError):
            self.cancel_review_modal()

    # ------------------------------------------------------------------
    # Interactive Terminal Loop & Clean Shutdown (Work Package M4)
    # ------------------------------------------------------------------

    def run(self, *, refresh_interval: float = 2.0, close_store_on_exit: bool = True) -> None:
        """Run the interactive keyboard-driven SRE Investigation Console loop."""
        bounded_interval = max(0.5, float(refresh_interval))
        if sys.stdin.isatty() and _HAS_TERMIOS:
            try:
                self._tty_fd = sys.stdin.fileno()
                self._saved_termios = termios.tcgetattr(self._tty_fd)
                tty.setcbreak(self._tty_fd)
            except (OSError, termios.error):
                self._tty_fd = None
                self._saved_termios = None
        try:
            with self.console.screen(hide_cursor=False) as screen:
                self._screen = screen
                self._set_mouse_tracking(True)
                while True:
                    tokens = self._tokens()
                    footer = Text(
                        "Controls: Up/Dn or j/k=Move | Left/Right/Tab=Switch | Enter=Open | 1-5=Tab | ?=Help | B/Esc=Back | Q=Quit",
                        style=tokens.muted,
                    )
                    screen.update(Group(self.render(height=self.console.size.height), footer))

                    try:
                        raw_key = self._read_key(
                            timeout=bounded_interval,
                            raw_text_mode=(self.review_modal is not None),
                        )
                    except KeyboardInterrupt:
                        self.notice = "Console closed (SIGINT) without automated actions."
                        break

                    if not self.handle_key(raw_key):
                        break
        finally:
            self._screen = None
            self._set_mouse_tracking(False)
            if self._tty_fd is not None and self._saved_termios is not None:
                try:
                    termios.tcsetattr(self._tty_fd, termios.TCSADRAIN, self._saved_termios)
                except termios.error:
                    pass
                self._tty_fd = None
                self._saved_termios = None
            if close_store_on_exit:
                self.store.close()
        self.console.print(Text("SRE Investigation Console closed without automated actions.", style=self._tokens().warning_soft))
