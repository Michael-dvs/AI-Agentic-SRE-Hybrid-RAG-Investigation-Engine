"""Unified Rich terminal console for human dossier review in the simulation lab."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import webbrowser
from typing import Any, Dict, Mapping, Sequence
from urllib.parse import urlencode

try:
    import termios
    import tty
    import select
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.segment import Segment
from rich.style import Style
from rich.table import Table
from rich.text import Text

from gateway.sanitizer import DeterministicSanitizer
from observability.audit_chain import AuditHashChain
from orchestrator.confidence import confidence_label_for_score
from orchestrator.console_config import (
    PROVIDER_PRESETS,
    EnvConfigManager,
    ModelCatalogClient,
    TelegramConfigHelper,
    mask_secret,
)
from orchestrator.handover import HandoverExporter
from orchestrator.llm_provider import OPENROUTER_BASE_URL, OPENROUTER_MODEL
from orchestrator.review import AuthorizedReviewManager, build_human_correction_payload
from orchestrator.state_machine import WorkflowStateStore
from orchestrator.verification_plan import availability_text, hypothesis_label
from orchestrator.telegram_dispatcher import TelegramDispatcher


ARCHIVE_STATES = {"CLOSED", "REJECTED", "MANUAL_TRIAGE_REQUIRED"}

_DISPLAY_SANITIZER = DeterministicSanitizer()


def _bounded_sanitized_excerpt(value: Any, *, limit: int = 240) -> str:
    raw = " ".join(str(value or "").split())
    sanitized, _ = _DISPLAY_SANITIZER.sanitize_text(raw)
    safe = "".join(char for char in sanitized if char >= " " and char != "\x7f")
    if not safe:
        return "Excerpt unavailable."
    if len(safe) <= limit:
        return safe
    return f"{safe[: limit - 1].rstrip()}…"


def _format_incident_time(
    incident: Mapping[str, Any],
    dossier: Mapping[str, Any],
    *,
    compact: bool = False,
) -> str:
    """Format incident timestamp into local HH:MM:SS (compact) or MM-DD HH:MM:SS."""
    window = dossier.get("incident_window") if isinstance(dossier.get("incident_window"), Mapping) else {}
    raw_ts = (
        window.get("start")
        or dossier.get("event_time")
        or dossier.get("created_at")
        or incident.get("created_at")
        or incident.get("updated_at")
    )
    if not raw_ts or not isinstance(raw_ts, str):
        return "-"
    try:
        cleaned = raw_ts.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        local_dt = parsed.astimezone()
        return local_dt.strftime("%H:%M:%S" if compact else "%m-%d %H:%M:%S")
    except Exception:
        return raw_ts[:16]


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
        or dossier.get("event_time")
        or dossier.get("created_at")
        or inc.get("created_at")
    )
    raw_end = window.get("end") or raw_start
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

    def __init__(self, renderable: RenderableType, offset: int, max_lines: int) -> None:
        self.renderable = renderable
        self.offset = max(0, offset)
        self.max_lines = max(4, max_lines)

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
        yield Segment(
            f"[Scroll: line {off + 1}-{min(total, off + view_lines)}/{total} | ↑/↓ or PgUp/PgDn]\n",
            Style(color="cyan", bold=True),
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
    """Read dossiers and incident state through the durable workflow store."""

    def __init__(self, store: WorkflowStateStore) -> None:
        self.store = store

    def active_dossiers(self) -> list[dict[str, Any]]:
        return self._dossiers_for_states({"HUMAN_REVIEW"}, pending_only=True)

    def archived_dossiers(self) -> list[dict[str, Any]]:
        return self._dossiers_for_states(ARCHIVE_STATES, pending_only=False)

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
        for incident in self.store.list_incidents(current_states=states):
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
        auth_context: Any = None,
    ) -> dict[str, Any]:
        action_upper = action.upper()
        corrections = None
        if action_upper == "CORRECT":
            statement = " ".join((corrected_hypothesis or "").split())
            if not statement:
                raise ValueError("Corrected hypothesis is required")
            corrections = build_human_correction_payload(
                dossier=dossier,
                corrected_statement=statement,
                reviewer_ref=reviewer_ref,
                reviewer_role=reviewer_role,
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
            target_version=int(dossier.get("dossier_version", 1)),
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
            return {"status": "UNAVAILABLE", "reason": result.stderr.strip()[:300], "services": []}

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
                "name": row.get("Service") or row.get("Name", "unknown"),
                "state": row.get("State", "unknown"),
                "health": row.get("Health", "not-reported"),
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
    """Render and operate the keyboard-driven Unified SRE Command Center."""

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
    ) -> None:
        self.store = store
        self.console = console or Console()
        self.reviewer_ref = reviewer_ref
        self.reviewer_role = reviewer_role
        self.repository = DashboardRepository(store)
        self.actions = ReviewActionController(
            store,
            audit_path=audit_path,
            handover_root=handover_root,
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
        self.view = "active"
        self.focus = "menu"  # "menu" | "list"
        self.selected_incident_id: str | None = None
        self.selected_index: int = 0
        self.list_scroll_offset: int = 0
        self.detail_scroll_offset: int = 0
        self._screen: Any = None
        self.fetched_models: list[str] = []
        self.last_model_check: str = "Untested"
        self.last_telegram_check: str = "Untested"
        self.notice = "Navigation: [↑/↓] switch menu, [→/Enter/Tab] focus incident list."

    def render(self, *, width: int | None = None, height: int | None = None) -> RenderableType:
        terminal_width = width or self.console.size.width
        menu_focused = (self.focus == "menu" and not self.selected_incident_id)
        nav_title = "Navigation [FOCUSED]" if menu_focused else "Navigation"
        nav_border = "bright_cyan" if menu_focused else "dim"
        main_title = f"{self._main_title()} [FOCUSED]" if not menu_focused else self._main_title()
        main_border = "bright_cyan" if not menu_focused else "white"

        is_narrow = terminal_width < 100
        # Only clip/paginate to viewport height when height is explicitly bounded (interactive TUI / viewport)
        main_height: int | None = None
        if height is not None:
            reserved_lines = 12 if is_narrow else 8
            main_height = max(6, height - reserved_lines)

        main = Panel(
            self._main_content(width=terminal_width, max_height=main_height),
            title=main_title,
            border_style=main_border,
        )
        actions = Panel(self._action_bar(), title="Review Action Bar", border_style="yellow")

        if is_narrow:
            navigation = Panel(self._navigation_compact(), title=nav_title, border_style=nav_border)
            return Group(navigation, main, actions)

        navigation = Panel(self._navigation(), title=nav_title, border_style=nav_border)
        two_panel = Table.grid(expand=True)
        two_panel.add_column(width=32)
        two_panel.add_column(ratio=1)
        two_panel.add_row(navigation, main)
        return Group(two_panel, actions)

    def _navigation_compact(self) -> Text:
        selected = {
            "active": "1",
            "archive": "2",
            "health": "3",
            "model": "4",
            "telegram": "5",
        }.get(self.view)
        text = Text()
        items = (
            ("1", "Active"),
            ("2", "Archive"),
            ("3", "Health"),
            ("4", "Model"),
            ("5", "Telegram"),
            ("Q", "Quit"),
        )
        for idx, (key, label) in enumerate(items):
            style = "bold reverse" if key == selected else "bold" if key == "Q" else ""
            if idx > 0:
                text.append("  ")
            text.append(f"[{key}] {label}", style=style)
        return text

    def _navigation(self) -> Text:
        selected = {
            "active": "1",
            "archive": "2",
            "health": "3",
            "model": "4",
            "telegram": "5",
        }.get(self.view)
        text = Text()
        for key, label in (
            ("1", "Active Incidents"),
            ("2", "Archive Dossiers"),
            ("3", "Service Health"),
            ("4", "AI Model Config"),
            ("5", "Telegram Alerts"),
            ("Q", "Quit"),
        ):
            style = "bold reverse" if key == selected else "bold" if key == "Q" else ""
            text.append(f"[{key}] {label}\n", style=style)
        return text

    def _main_title(self) -> str:
        return {
            "active": "Active Incidents",
            "archive": "Archive Dossiers",
            "health": "Synthetic Service Health",
            "model": "AI Model and C15 Cost Metrics",
            "telegram": "Telegram Dispatcher",
        }[self.view]

    def _main_content(self, *, width: int = 120, max_height: int | None = None) -> RenderableType:
        def _maybe_scroll(content: RenderableType) -> RenderableType:
            if max_height is None:
                return content
            return _ScrollableContent(
                content,
                offset=self.detail_scroll_offset,
                max_lines=max(6, max_height),
            )

        if self.view in {"active", "archive"}:
            rows = self.repository.active_dossiers() if self.view == "active" else self.repository.archived_dossiers()
            if self.selected_incident_id:
                dossier = self.repository.latest_dossier(self.selected_incident_id)
                if dossier:
                    return _maybe_scroll(self._dossier_detail(dossier))
            return self._incident_table(rows, width=width, max_height=max_height)
        if self.view == "health":
            return _maybe_scroll(self._health_table(self.health.inspect()))
        if self.view == "model":
            dossiers = self.repository.active_dossiers() or self.repository.archived_dossiers()
            active_model = "N/A"
            if dossiers:
                reproducibility = dossiers[0]["dossier"].get("reproducibility", {})
                active_model = str(reproducibility.get("model_version", "N/A"))
            return _maybe_scroll(self._model_panel(self.costs.read(), active_model))
        return _maybe_scroll(self._telegram_panel())

    def _incident_table(
        self,
        rows: list[dict[str, Any]],
        *,
        width: int = 120,
        max_height: int | None = None,
    ) -> RenderableType:
        if not rows:
            reason = "No dossiers pending review." if self.view == "active" else "No archived dossiers available."
            return Text(f"{reason}\nPress [B] to return or select another menu item.", style="dim")
        if self.selected_index >= len(rows):
            self.selected_index = max(0, len(rows) - 1)
        elif self.selected_index < 0:
            self.selected_index = 0

        if max_height is not None:
            # Reserve ~5 lines for table header, borders, and footer hint
            max_visible = max(3, max_height - 5)
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
        is_compact = width < 85
        show_mode_col = width >= 78

        table = Table(expand=True)
        table.add_column("No.", justify="right", min_width=4, max_width=5, no_wrap=True)
        table.add_column("Time", min_width=8 if is_compact else 14, no_wrap=True)
        table.add_column("Incident", ratio=2, max_width=24 if is_compact else None, no_wrap=True, overflow="ellipsis")
        table.add_column("Sev" if is_compact else "Severity", min_width=4, max_width=8, no_wrap=True)
        table.add_column("Service", ratio=1, max_width=14 if is_compact else None, no_wrap=True, overflow="ellipsis")
        if show_mode_col:
            table.add_column("Mode", min_width=7, max_width=8, no_wrap=True)
        if not is_compact:
            table.add_column("State", min_width=12, no_wrap=True)

        for offset_idx, row in enumerate(visible_slice):
            actual_idx = self.list_scroll_offset + offset_idx
            incident = row["incident"]
            dossier = row["dossier"]
            state = str(incident.get("current_state", "unknown"))
            display_state = "ESCALATED" if state == "MANUAL_TRIAGE_REQUIRED" else state
            inv_mode = str(dossier.get("investigation_mode") or "deterministic_baseline").lower()
            mode_badge = "AI LLM" if inv_mode == "agentic_llm" else ("FALLBACK" if inv_mode == "manual_fallback" else "OFFLINE")
            is_sel = (actual_idx == self.selected_index)
            no_str = f"▶ {actual_idx + 1}" if is_sel else f"  {actual_idx + 1}"
            row_style = "bold cyan" if is_sel else ""
            time_str = _format_incident_time(incident, dossier, compact=is_compact)
            row_cells = [
                no_str,
                time_str,
                str(dossier.get("incident_id", incident["incident_id"])),
                str(dossier.get("severity", "unknown")).upper(),
                str(dossier.get("service_id", incident.get("service_id") or "unknown")),
            ]
            if show_mode_col:
                row_cells.append(mode_badge)
            if not is_compact:
                row_cells.append(display_state)
            table.add_row(*row_cells, style=row_style)

        hint_parts = ["Navigation: [↑/↓ or j/k] Select", "[Enter/O] Open Dossier", "[G] Open Grafana"]
        if len(rows) > max_visible:
            start_num = self.list_scroll_offset + 1
            end_num = self.list_scroll_offset + len(visible_slice)
            hint_parts.append(f"Showing {start_num}-{end_num} of {len(rows)}")
        return Group(
            table,
            Text("  |  ".join(hint_parts), style="bold green"),
        )

    def _dossier_detail(self, dossier: Mapping[str, Any]) -> RenderableType:
        impact = dossier.get("impact_summary") if isinstance(dossier.get("impact_summary"), Mapping) else {}
        services = impact.get("affected_services") or dossier.get("investigation_scope") or [dossier.get("service_id", "unknown")]
        hypotheses = dossier.get("hypotheses") if isinstance(dossier.get("hypotheses"), list) else []
        citations = dossier.get("sop_citations") if isinstance(dossier.get("sop_citations"), list) else []
        evidence_source = dossier.get("evidence") or dossier.get("evidence_items")
        evidence = evidence_source if isinstance(evidence_source, list) else []

        repro = dossier.get("reproducibility") if isinstance(dossier.get("reproducibility"), Mapping) else {}
        inv_mode = str(dossier.get("investigation_mode") or "deterministic_baseline").lower()
        model_ver = str(repro.get("model_version") or "deterministic_rule_engine_v1")
        provider_name = str(repro.get("provider") or ("openrouter" if inv_mode == "agentic_llm" else "local-rule-engine"))
        prompt_ver = str(repro.get("prompt_version") or "deterministic_baseline_rules_v1")
        in_tok = repro.get("input_tokens")
        out_tok = repro.get("output_tokens")
        tot_tok = repro.get("total_tokens")
        inc_id = str(dossier.get("incident_id") or "")
        db_path = getattr(self.store, "db_path", None)
        if inv_mode == "agentic_llm" and tot_tok is None:
            if inc_id and db_path:
                try:
                    import sqlite3
                    with sqlite3.connect(str(db_path)) as conn:
                        row = conn.execute(
                            "SELECT input_reported, output_reported FROM c13_llm_runs WHERE incident_id = ?",
                            (inc_id,),
                        ).fetchone()
                        if row and (row[0] or row[1]):
                            in_tok, out_tok = int(row[0] or 0), int(row[1] or 0)
                            tot_tok = in_tok + out_tok
                except Exception:
                    pass

        if inv_mode == "agentic_llm":
            mode_text = Text("AI MODEL (ONLINE)", style="bold green")
            tok_str = (
                f"in={in_tok}, out={out_tok}, total={tot_tok}"
                if tot_tok is not None
                else "recorded via AI provider"
            )
        elif inv_mode == "manual_fallback":
            reason_code = repro.get("llm_reason")
            if not reason_code:
                for u in dossier.get("unknowns") or []:
                    m = re.search(r"LLM synthesis unavailable \(([^)]+)\)", str(u))
                    if m:
                        reason_code = m.group(1)
                        break
            reason_code = str(reason_code or "UNAVAILABLE")
            mode_text = Text(f"MANUAL FALLBACK ({reason_code})", style="bold red")
            tok_str = "0 tokens (LLM failed/fallback to rule baseline)"
        else:
            mode_text = Text("OFFLINE DETERMINISTIC (NO AI MODEL)", style="bold yellow")
            tok_str = "0 tokens (Offline Rule Engine)"

        review_status = str(dossier.get("review_summary", {}).get("status", "PENDING_REVIEW"))
        closure_display = (
            "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED (diagnosis_verified=False, technical_resolved=False, remediation_authorized=False)"
            if review_status.upper() == "APPROVED"
            else f"{review_status} (diagnosis_verified=False, remediation_authorized=False)"
        )

        header = Table.grid(expand=True)
        header.add_column(ratio=1)
        header.add_column(ratio=2)
        header.add_row("Incident", str(dossier.get("incident_id", "unknown")))
        header.add_row("Severity", str(dossier.get("severity", "unknown")).upper())
        header.add_row("Services", ", ".join(str(item) for item in services))
        header.add_row("Status", review_status)
        header.add_row("Closure / Diagnosis", closure_display)
        header.add_row("Reviewer Trust", "Local PoC caller-asserted identity (unauthenticated)")
        header.add_row("Auto remediation", "DISABLED | auto_action_triggered=False")
        header.add_row("Reasoning Mode", mode_text)
        header.add_row("Provider / Model", f"{provider_name} / {model_ver}")
        header.add_row("Prompt / Engine", prompt_ver[:24] + ("…" if len(prompt_ver) > 24 else ""))
        header.add_row("Token Usage", tok_str)

        symptom = Text(str(impact.get("observed_symptoms") or dossier.get("message") or "No symptoms recorded."))

        hyp_conf_map: dict[str, dict[str, Any]] = {}
        impact_graph_data: dict[str, Any] = {}
        validation_meta: dict[str, Any] = {}
        if inc_id and db_path:
            try:
                import sqlite3
                with sqlite3.connect(str(db_path)) as conn:
                    row = conn.execute(
                        "SELECT context_blob FROM checkpoints WHERE incident_id = ? ORDER BY rowid DESC LIMIT 1",
                        (inc_id,),
                    ).fetchone()
                    if row and row[0]:
                        c_blob = json.loads(row[0])
                        if isinstance(c_blob.get("impact_graph"), dict):
                            impact_graph_data = c_blob["impact_graph"]
                        v_reports = c_blob.get("validation_reports")
                        if isinstance(v_reports, list) and v_reports and isinstance(v_reports[0], dict):
                            validation_meta = v_reports[0]
                        for h_item in c_blob.get("hypotheses", []):
                            hid = h_item.get("hypothesis_id")
                            if hid:
                                hyp_conf_map[hid] = {
                                    "confidence_score": h_item.get("confidence_score"),
                                    "confidence": h_item.get("confidence"),
                                    "confidence_rationale": h_item.get("confidence_rationale"),
                                    "llm_proposed_confidence": h_item.get("llm_proposed_confidence"),
                                    "unvalidated": False,
                                }
                    if not hyp_conf_map:
                        run_row = conn.execute(
                            "SELECT result FROM c13_llm_runs WHERE incident_id = ?",
                            (inc_id,),
                        ).fetchone()
                        if run_row and run_row[0]:
                            res = json.loads(run_row[0])
                            cands = res.get("candidates") or {}
                            prim = cands.get("primary_hypothesis") or {}
                            alts = cands.get("alternative_hypotheses") or []
                            if prim:
                                p_score = {"HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.2}.get(prim.get("confidence"))
                                hyp_conf_map[f"hyp-{inc_id}-001"] = {
                                    "confidence": prim.get("confidence"),
                                    "confidence_score": p_score,
                                    "unvalidated": True,
                                    "llm_proposed_confidence": prim.get("confidence"),
                                }
                            for idx, a in enumerate(alts, start=2):
                                a_score = {"HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.2}.get(a.get("confidence"))
                                hyp_conf_map[f"hyp-{inc_id}-{idx:03d}"] = {
                                    "confidence": a.get("confidence"),
                                    "confidence_score": a_score,
                                    "unvalidated": True,
                                    "llm_proposed_confidence": a.get("confidence"),
                                }
            except Exception:
                pass

        impact_text = Text()
        budget_imp = impact.get("error_budget_impact")
        if budget_imp:
            impact_text.append(f"Error Budget Impact: {budget_imp}\n", style="bold")
        primary_svc = str(dossier.get("service_id") or impact_graph_data.get("primary_service") or "unknown")
        upstreams = impact_graph_data.get("upstream_callers") if isinstance(impact_graph_data.get("upstream_callers"), list) else []
        downstreams = impact_graph_data.get("downstream_dependencies") if isinstance(impact_graph_data.get("downstream_dependencies"), list) else []
        if upstreams or downstreams:
            up_str = ", ".join(str(x) for x in upstreams) if upstreams else "-"
            down_str = ", ".join(str(x) for x in downstreams) if downstreams else "-"
            impact_text.append(f"Topology Flow: [{up_str}] -> {primary_svc} -> [{down_str}]\n")
        origin_svc = validation_meta.get("origin_service")
        is_cascade = validation_meta.get("is_cascade")
        reason_codes = validation_meta.get("reason_codes") if isinstance(validation_meta.get("reason_codes"), list) else []
        if origin_svc or is_cascade is not None or reason_codes:
            flags = ", ".join(str(rc) for rc in reason_codes) if reason_codes else "-"
            impact_text.append(
                f"Cascade Check: origin={origin_svc or primary_svc} | is_cascade={bool(is_cascade)} | flags={flags}\n"
            )
        topo_unc = impact_graph_data.get("uncertainty")
        if topo_unc:
            impact_text.append(f"Topology Note: {topo_unc}\n", style="dim")

        hypothesis_table = Table(expand=True)
        hypothesis_table.add_column("Rank", width=5)
        hypothesis_table.add_column("Hypothesis")
        hypothesis_table.add_column("Support", width=14)
        hypothesis_table.add_column("Confidence", width=14)
        hyp_details: list[dict[str, Any]] = []
        for rank, hypothesis in enumerate(hypotheses, start=1):
            if not isinstance(hypothesis, Mapping):
                continue
            statement = hypothesis.get("statement") or hypothesis.get("hypothesis_statement") or hypothesis.get("title") or hypothesis.get("description", "")
            support = hypothesis_label(hypothesis)
            confidence = hypothesis.get("confidence_score")
            conf_str = hypothesis.get("confidence")
            conf_rationale = hypothesis.get("confidence_rationale")
            is_unvalidated = False
            hid = str(hypothesis.get("hypothesis_id") or "")
            if confidence is None and hid in hyp_conf_map:
                confidence = hyp_conf_map[hid].get("confidence_score")
                conf_str = hyp_conf_map[hid].get("confidence")
                conf_rationale = conf_rationale or hyp_conf_map[hid].get("confidence_rationale")
                is_unvalidated = bool(hyp_conf_map[hid].get("unvalidated"))
            elif confidence is None:
                for candidate_id, cdata in hyp_conf_map.items():
                    if candidate_id.endswith(f"-{rank:03d}"):
                        confidence = cdata.get("confidence_score")
                        conf_str = cdata.get("confidence")
                        conf_rationale = conf_rationale or cdata.get("confidence_rationale")
                        is_unvalidated = bool(cdata.get("unvalidated"))
                        break
            elif hid in hyp_conf_map and not conf_rationale:
                conf_rationale = hyp_conf_map[hid].get("confidence_rationale")

            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                derived_label = confidence_label_for_score(float(confidence))
                confidence_text = f"{float(confidence):.0%} ({derived_label})"
                if is_unvalidated:
                    confidence_text += " [unvalidated prior]"
            elif conf_str:
                confidence_text = f"{conf_str} [unvalidated]"
            else:
                confidence_text = "N/A"
            rank_label = str(hypothesis.get("rank", rank))
            hypothesis_table.add_row(rank_label, str(statement), str(support), confidence_text)
            sup_ids = hypothesis.get("supporting_evidence_ids") if isinstance(hypothesis.get("supporting_evidence_ids"), list) else []
            con_ids = (
                hypothesis.get("contradicting_evidence_ids")
                if isinstance(hypothesis.get("contradicting_evidence_ids"), list)
                else (hypothesis.get("refuting_evidence_ids") if isinstance(hypothesis.get("refuting_evidence_ids"), list) else [])
            )
            reason_summary = hypothesis.get("reason_summary") or hypothesis.get("description") or ""
            hyp_details.append({
                "rank": rank_label,
                "statement": str(statement),
                "support": str(support),
                "confidence": confidence_text,
                "confidence_rationale": str(conf_rationale) if conf_rationale else "",
                "reason_summary": str(reason_summary),
                "supporting": [str(x) for x in sup_ids],
                "contradicting": [str(x) for x in con_ids],
            })
        if not hypothesis_table.rows:
            hypothesis_table.add_row("-", "No hypotheses formulated", "INCONCLUSIVE", "N/A")

        reasoning_text = Text()
        for idx_h, item in enumerate(hyp_details):
            if idx_h > 0:
                reasoning_text.append("\n")
            reasoning_text.append(
                f"#{item['rank']} [{item['support']} | {item['confidence']}] {item['statement']}\n",
                style="bold cyan",
            )
            if item["reason_summary"]:
                reasoning_text.append(f"  Why / Causal Analysis: {item['reason_summary']}\n")
            if item.get("confidence_rationale"):
                reasoning_text.append(f"  Confidence Basis    : {item['confidence_rationale']}\n", style="dim")
            sup_str = ", ".join(item["supporting"]) if item["supporting"] else "none"
            reasoning_text.append(f"  Supporting Evidence : {sup_str}\n", style="green")
            if item["contradicting"]:
                reasoning_text.append(
                    f"  Contradicting Evid. : {', '.join(item['contradicting'])}\n",
                    style="yellow",
                )
        if not reasoning_text.plain:
            reasoning_text.append("No hypothesis reasoning available.", style="dim")

        unknowns_list = dossier.get("unknowns") if isinstance(dossier.get("unknowns"), list) else []
        missing_sources = dossier.get("missing_sources") if isinstance(dossier.get("missing_sources"), list) else []
        unknowns_text = Text()
        for unk in unknowns_list:
            unknowns_text.append(f"- {unk}\n")
        for ms in missing_sources:
            if isinstance(ms, Mapping):
                unknowns_text.append(
                    f"- [MISSING SOURCE] {ms.get('tool_name', 'unknown')} ({ms.get('error_code', 'UNAVAILABLE')}): {ms.get('impact_note', '')}\n",
                    style="yellow",
                )
        if not unknowns_text.plain:
            unknowns_text.append("No uncertainties or missing sources recorded.", style="dim")

        rec_checks = dossier.get("recommended_checks") if isinstance(dossier.get("recommended_checks"), list) else []
        checks_text = Text()
        for idx_c, chk in enumerate(rec_checks, start=1):
            if isinstance(chk, Mapping):
                cid = chk.get("check_id", f"chk-{idx_c:02d}")
                risk = str(chk.get("risk_level", "medium")).upper()
                sop_ref = chk.get("related_sop_doc_id") or "-"
                desc = chk.get("description", "")
                checks_text.append(f"{idx_c}. [{cid} | RISK={risk} | SOP={sop_ref}] {desc}\n")
            elif isinstance(chk, str):
                checks_text.append(f"{idx_c}. {chk}\n")
        if checks_text.plain:
            checks_text.append("Guardrail: auto_execution_allowed=False | requires_human_approval=True", style="dim")
        else:
            checks_text.append("No SRE verification steps recorded.", style="dim")

        citation_text = Text(availability_text(dossier) + "\n")
        for item in citations:
            if isinstance(item, Mapping):
                metadata = (
                    f"{item.get('doc_id') or item.get('document_id', 'Runbook')} "
                    f"v{item.get('version') or item.get('document_version', 'unknown')} | "
                    f"{item.get('section_path') or item.get('section', 'section unavailable')} | "
                    f"{item.get('chunk_id', 'chunk unavailable')} | {item.get('source_uri', 'source unavailable')}"
                )
                excerpt = (
                    item.get("excerpt")
                    or item.get("text_excerpt")
                    or item.get("summary")
                )
                citation_text.append(f"{metadata}\n  {_bounded_sanitized_excerpt(excerpt)}\n")

        evidence_text = Text()
        for item in evidence:
            if isinstance(item, Mapping):
                metadata = (
                    f"{item.get('evidence_id', 'unknown')} | "
                    f"{item.get('tool_name', 'source unknown')} | "
                    f"quality={item.get('data_quality', 'unknown')}"
                )
                evidence_text.append(
                    f"{metadata}\n  {_bounded_sanitized_excerpt(item.get('summary'))}\n"
                )
        if not evidence_text.plain:
            evidence_text.append("No verified telemetry evidence.", style="dim")

        detail_blocks: list[RenderableType] = [
            header,
            Panel(symptom, title="Observed Symptoms"),
        ]
        if impact_text.plain.strip():
            detail_blocks.append(Panel(impact_text, title="Impact & Dependency Context"))
        detail_blocks.extend([
            hypothesis_table,
            Panel(reasoning_text, title="Hypothesis Reasoning Details (Why & How)"),
            Panel(unknowns_text, title="Unknowns & Missing Sources"),
            Panel(checks_text, title="SRE Recommended Verification (Human-Controlled)"),
            Panel(citation_text, title="Runbook SOP Citations"),
            Panel(evidence_text, title="Verified Evidence IDs"),
        ])
        return Group(*detail_blocks)

    @staticmethod
    def _health_table(snapshot: Mapping[str, Any]) -> RenderableType:
        services = snapshot.get("services", [])
        if not services:
            return Text(f"Status: {snapshot.get('status')}\n{snapshot.get('reason', 'No health data available.')}", style="yellow")
        table = Table(expand=True)
        table.add_column("Service")
        table.add_column("Container State")
        table.add_column("Health")
        for service in services:
            table.add_row(str(service["name"]), str(service["state"]), str(service["health"]))
        return table

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
        cfg = self._current_llm_config()
        table = Table.grid(padding=(0, 2))
        table.add_row("Provider API", f"{cfg['provider_name']} ({cfg['provider_key']})")
        table.add_row("API Base URL", cfg["base_url"] or "NOT CONFIGURED")
        api_status = f"CONFIGURED ({mask_secret(cfg['api_key'])})" if cfg["api_key"] else "EMPTY (Offline / Mock Mode)"
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
            style="bold cyan",
        )
        return Group(table, controls)

    def _telegram_panel(self) -> RenderableType:
        mode = "ACTIVE OUTBOUND" if self.telegram.configured else "DRY-RUN"
        details = Text()
        details.append(f"Status: {mode}\n", style="bold green" if self.telegram.configured else "bold yellow")
        details.append(f"Bot Token : {mask_secret(self.telegram.bot_token)}\n")
        details.append(f"Chat ID   : {self.telegram.chat_id or 'NOT CONFIGURED'}\n")
        details.append(f"Last Test : {self.last_telegram_check}\n\n")
        details.append("Security Policy:\n", style="bold")
        details.append("  Direction: outbound notification only\n")
        details.append("  Inbound listener: DISABLED\n")
        details.append("  Remote command execution: NOT IMPLEMENTED\n")
        details.append("  Credentials synced to .env (TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID).\n\n")
        details.append(
            "Telegram Configuration:\n"
            "  [K] Set Bot Token   [C] Set / Detect Chat ID   [T] Test Bot & Send Alert   [X] Reset Dry-Run",
            style="bold cyan",
        )
        return details

    _MENU_ORDER = ("active", "archive", "health", "model", "telegram")

    def _action_bar(self) -> Text:
        if self.selected_incident_id:
            inc = self.store.get_incident(self.selected_incident_id)
            if inc and inc.get("current_state") != "HUMAN_REVIEW":
                return Text("[REVIEW LOCKED - FINALIZED]  [G] GRAFANA  [B/Esc] BACK  [Q] QUIT", style="bold yellow")
            return Text("[A] APPROVE  [R] REJECT  [C] CORRECT  [E] ESCALATE  [G] GRAFANA  [B/Esc] BACK  [Q] QUIT", style="bold yellow")
        if self.view == "model":
            return Text(f"[P] PROVIDER  [K] API KEY  [F] FETCH MODEL  [M] MANUAL  [T] TEST  [X] RESET | {self.notice}", style="bold")
        if self.view == "telegram":
            return Text(f"[K] BOT TOKEN  [C] CHAT ID  [T] TEST ALERT  [X] RESET DRY-RUN | {self.notice}", style="bold")
        if self.focus == "list":
            return Text(f"[↑/↓] SELECT ROW  [Enter/O] OPEN  [G] GRAFANA  [←/Tab] TO MENU  [Q] QUIT | {self.notice}", style="bold")
        return Text(f"[↑/↓] SWITCH MENU  [→/Enter/Tab] INCIDENT LIST  [1-5] JUMP  [Q] QUIT | {self.notice}", style="bold")

    def _open_grafana_for_selected(self) -> None:
        """Open Grafana dashboard zoomed to the selected incident's anomaly time window."""
        incident: Mapping[str, Any] | None = None
        dossier: Mapping[str, Any] | None = None
        if self.selected_incident_id:
            dossier = self.repository.latest_dossier(self.selected_incident_id)
            incident = self.repository.store.get_incident(self.selected_incident_id)
        elif self.view in ("active", "archive"):
            rows = self.repository.active_dossiers() if self.view == "active" else self.repository.archived_dossiers()
            if rows and 0 <= self.selected_index < len(rows):
                incident = rows[self.selected_index]["incident"]
                dossier = rows[self.selected_index]["dossier"]

        if not dossier:
            self.notice = "Select an incident first to open Grafana."
            return

        url = build_grafana_incident_url(incident, dossier)
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        svc = str(dossier.get("service_id") or (incident or {}).get("service_id") or "unknown")
        if opened:
            self.notice = f"Grafana opened ({svc}): {url}"
        else:
            self.notice = f"Open Grafana URL ({svc}): {url}"

    def _select_by_index(self) -> None:
        rows = self.repository.active_dossiers() if self.view == "active" else self.repository.archived_dossiers()
        if not rows:
            self.notice = "No dossiers available to open."
            return
        if 0 <= self.selected_index < len(rows):
            selected = rows[self.selected_index]
            self.selected_incident_id = str(selected["dossier"]["incident_id"])
            self.notice = f"Dossier {self.selected_incident_id} opened."
        else:
            self.notice = "Invalid dossier selection."

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
        """Temporarily suspend mouse tracking, prompt user cleanly, and re-enable mouse tracking."""
        self._set_mouse_tracking(False)
        self.console.clear()
        self.console.print(self.render())
        self.console.print()
        try:
            if default:
                return Prompt.ask(prompt, console=self.console, password=password, default=default).strip()
            return Prompt.ask(prompt, console=self.console, password=password).strip()
        finally:
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
        table = Table(title="Select AI API Provider", expand=False)
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
            self.notice = f"Provider configuration cancelled: {exc}"
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
        term_h = height or self.console.size.height
        max_visible = max(5, term_h - 10)
        total = len(models)
        if total == 0:
            body: RenderableType = Text(
                "No models match the filter.\nPress [/] to edit filter or [Esc/B] to cancel.",
                style="yellow",
            )
        else:
            sel = max(0, min(selected_idx, total - 1))
            if sel < scroll_offset:
                scroll_offset = sel
            elif sel >= scroll_offset + max_visible:
                scroll_offset = sel - max_visible + 1
            scroll_offset = max(0, min(scroll_offset, max(0, total - max_visible)))
            visible = models[scroll_offset : scroll_offset + max_visible]

            table = Table(expand=True, show_header=True)
            table.add_column("No.", justify="right", width=6, no_wrap=True)
            table.add_column("Model ID", no_wrap=True, overflow="ellipsis")
            table.add_column("Status", width=10, no_wrap=True)
            for offset_i, m_id in enumerate(visible):
                actual_i = scroll_offset + offset_i
                is_sel = actual_i == sel
                is_active = m_id == active_model
                no_str = f"▶ {actual_i + 1}" if is_sel else f"  {actual_i + 1}"
                status_str = "ACTIVE" if is_active else ""
                row_style = "bold cyan" if is_sel else ("green" if is_active else "")
                table.add_row(no_str, m_id, status_str, style=row_style)

            end_i = scroll_offset + len(visible)
            info = Text(
                f"Showing {scroll_offset + 1}-{end_i} of {total} models"
                + (f" (filter: '{keyword}', total {total_count})" if keyword else "")
                + "\nNavigation: [↑/↓ or j/k] Select  |  [PgUp/PgDn] Page Scroll  |  [/] Filter  |  [Enter] Save  |  [Esc/B] Cancel",
                style="bold green",
            )
            body = Group(table, info)

        return Panel(
            body,
            title="Select Model from API (Arrow Key Scrollable)",
            border_style="bright_cyan",
        )

    def _fetch_and_select_model(self) -> None:
        cfg = self._current_llm_config()
        self.notice = f"Fetching model list from {cfg['base_url']}..."
        res = self.model_catalog.fetch_models(cfg["base_url"], cfg["api_key"])
        if res["status"] != "OK":
            self.last_model_check = f"ERROR: {res['error'][:65]}"
            self.notice = f"Failed to fetch models: {res['error'][:80]}"
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

                key = self._read_key(timeout=None)
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
                elif key == "/":
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
                self.notice = res.get("error") or "Endpoint connection successful."
        else:
            self.last_model_check = f"FAILED ({res['error'][:60]})"
            self.notice = f"Connection test failed: {res['error'][:80]}"

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
                    self.last_telegram_check = f"Token saved, verification: {check['error']}"
                    self.notice = f"Token saved but verification failed: {check['error']}"
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
                    table = Table(title="Detected Chat IDs from Bot getUpdates")
                    table.add_column("No.", justify="right")
                    table.add_column("Chat ID")
                    table.add_column("Info")
                    for idx, (cid, desc) in enumerate(discovered, 1):
                        table.add_row(str(idx), cid, desc)
                    self.console.print(table)
                else:
                    self.console.print("[dim]No incoming messages to bot yet or unable to detect. Enter Chat ID manually.[/dim]")

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
            self.notice = f"Chat ID configuration cancelled: {exc}"
        finally:
            self._set_mouse_tracking(True)

    def _test_telegram_alert(self) -> None:
        if not self.telegram.bot_token:
            self.last_telegram_check = "ERROR: Bot Token is empty."
            self.notice = "Configure Bot Token first using key [K]."
            return
        bot_check = self.telegram_helper.test_bot(self.telegram.bot_token)
        if bot_check["status"] != "OK":
            self.last_telegram_check = f"FAILED: {bot_check['error']}"
            self.notice = f"Bot verification failed: {bot_check['error']}"
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
                "observed_symptoms": "Outbound Telegram connectivity test from Unified SRE Command Center.",
            },
            "hypotheses": [{"statement": "Outbound Telegram notification test verified", "confidence_score": 1.0}],
            "sop_citations": [{"doc_id": "SOP-TEST-001", "section_path": "Outbound Alert Verification"}],
        }
        res = self.telegram.dispatch_pending_review(test_dossier)
        if res.delivered:
            self.last_telegram_check = f"DELIVERED to {self.telegram.chat_id} (@{bot_check['username']})"
            self.notice = f"Test alert delivered to Chat ID {self.telegram.chat_id}!"
        else:
            self.last_telegram_check = f"{res.status}: {res.reason}"
            self.notice = f"Test alert failed ({res.reason})."

    def _reset_telegram_config(self) -> None:
        self.env_manager.set_values({"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})
        self.telegram = TelegramDispatcher(bot_token="", chat_id="")
        self.last_telegram_check = "Reset to DRY-RUN mode"
        self.notice = "Telegram configuration cleared (DRY-RUN mode)."

    def _read_key(self, timeout: float | None = 2.0) -> str:
        """Read a single keypress, arrow key, or escape sequence; return 'REFRESH' on timeout."""
        if not sys.stdin.isatty() or not _HAS_TERMIOS:
            try:
                line = sys.stdin.readline()
                if not line:
                    return "Q"
                cmd = line.strip().upper()
                if cmd in ("UP", "DOWN", "LEFT", "RIGHT", "PGUP", "PGDN", "TAB", "ENTER", "ESC", "Q", "B", "O", "A", "R", "C", "E", "P", "K", "F", "M", "T", "X"):
                    return cmd
                return cmd[:1] if cmd else "ENTER"
            except (OSError, EOFError):
                return "Q"

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        try:
            tty.setcbreak(fd)
            while True:
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
                                # Consume & discard SGR mouse events (\x1b[<btn;x;yM/m) to disable trackpad scroll
                                if b2 == b"[" and b3 == b"<":
                                    for _ in range(64):
                                        if not select.select([fd], [], [], 0.02)[0]:
                                            break
                                        mb = os.read(fd, 1)
                                        if mb in (b"M", b"m"):
                                            break
                                    continue
                                # Consume & discard legacy X10 mouse events (\x1b[M + 3 bytes)
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
                                    if extra == b"A":
                                        return "UP"
                                    if extra == b"B":
                                        return "DOWN"
                                    if extra == b"C":
                                        return "RIGHT"
                                    if extra == b"D":
                                        return "LEFT"
                                    if extra == b"~":
                                        break
                        return "ESC"
                    return "ESC"
                if b in (b"\r", b"\n"):
                    return "ENTER"
                if b == b"\t":
                    return "TAB"
                if b == b"\x03":  # Ctrl+C
                    raise KeyboardInterrupt
                if b == b" ":
                    return "ENTER"
                return b.decode("utf-8", errors="ignore").upper()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _review_selected(self, action: str) -> None:
        if not self.selected_incident_id:
            self.notice = "Select a dossier first."
            return
        inc = self.store.get_incident(self.selected_incident_id)
        if inc and inc.get("current_state") != "HUMAN_REVIEW":
            self.notice = f"Incident is already finalized ({inc.get('current_state')}); review actions are locked."
            return
        dossier = self.repository.latest_dossier(self.selected_incident_id)
        if dossier is None:
            self.notice = "Dossier not found."
            return
        rationale = self._prompt_text("Rationale")
        corrected = None
        target = None
        if action == "CORRECT":
            corrected = self._prompt_text("Corrected root-cause hypothesis")
        elif action == "ESCALATE":
            target = self._prompt_text("Escalation target", default="SRE_LEAD_ONCALL")
        try:
            result = self.actions.apply(
                dossier,
                action,
                reviewer_ref=self.reviewer_ref,
                reviewer_role=self.reviewer_role,
                rationale=rationale,
                corrected_hypothesis=corrected,
                escalation_target=target,
            )
        except Exception as exc:
            self.notice = f"Review failed: {type(exc).__name__}: {exc}"
            return
        semantics = result.get("approval_semantics") or {}
        meaning = semantics.get("closure_meaning", action)
        self.notice = (
            f"{action} recorded ({meaning}); diagnosis_verified=False; "
            f"auto_action_triggered={result['auto_action_triggered']}."
        )
        self.selected_incident_id = None

    def run(self) -> None:
        """Run the interactive keyboard-driven Unified SRE Command Center loop."""
        try:
            with self.console.screen(hide_cursor=False) as screen:
                self._screen = screen
                self._set_mouse_tracking(True)
                while True:
                    footer = Text(
                        "Controls: ↑/↓ or j/k=Move | ←/→/Tab=Switch Panel | Enter=Open | 1-5=Menu | B/Esc=Back | Q=Quit",
                        style="dim",
                    )
                    screen.update(Group(self.render(height=self.console.size.height), footer))

                    try:
                        key = self._read_key(timeout=2.0)
                    except KeyboardInterrupt:
                        self.notice = "Console closed (SIGINT)."
                        break

                    if key == "REFRESH":
                        continue

                    if key == "Q":
                        self.notice = "Console closed without automated actions."
                        break

                    rows = self.repository.active_dossiers() if self.view == "active" else self.repository.archived_dossiers()
                    num_rows = len(rows)

                    # Tab-specific configuration shortcuts on AI Model Config & Telegram Alerts
                    if self.view == "model" and not self.selected_incident_id:
                        if key == "P":
                            self._configure_model_provider()
                            continue
                        if key == "K":
                            self._configure_model_api_key()
                            continue
                        if key == "F":
                            self._fetch_and_select_model()
                            continue
                        if key == "M":
                            self._configure_model_manual()
                            continue
                        if key == "T":
                            self._test_model_connection()
                            continue
                        if key == "X":
                            self._reset_model_config()
                            continue

                    if self.view == "telegram" and not self.selected_incident_id:
                        if key == "K":
                            self._configure_telegram_token()
                            continue
                        if key == "C":
                            self._configure_telegram_chat_id()
                            continue
                        if key == "T":
                            self._test_telegram_alert()
                            continue
                        if key == "X":
                            self._reset_telegram_config()
                            continue

                    if key in ("UP", "K"):
                        if self.selected_incident_id:
                            self.detail_scroll_offset = max(0, self.detail_scroll_offset - 2)
                        elif self.focus == "menu":
                            idx = self._MENU_ORDER.index(self.view)
                            self.view = self._MENU_ORDER[(idx - 1) % len(self._MENU_ORDER)]
                            self.selected_index = 0
                            self.list_scroll_offset = 0
                            self.detail_scroll_offset = 0
                            self.notice = f"Menu: {self._main_title()}."
                        elif self.focus == "list" and num_rows > 0:
                            self.selected_index = (self.selected_index - 1) % num_rows
                            self.notice = f"Selected row {self.selected_index + 1}."
                    elif key in ("DOWN", "J"):
                        if self.selected_incident_id:
                            self.detail_scroll_offset += 2
                        elif self.focus == "menu":
                            idx = self._MENU_ORDER.index(self.view)
                            self.view = self._MENU_ORDER[(idx + 1) % len(self._MENU_ORDER)]
                            self.selected_index = 0
                            self.list_scroll_offset = 0
                            self.detail_scroll_offset = 0
                            self.notice = f"Menu: {self._main_title()}."
                        elif self.focus == "list" and num_rows > 0:
                            self.selected_index = (self.selected_index + 1) % num_rows
                            self.notice = f"Selected row {self.selected_index + 1}."
                    elif key == "PGUP":
                        if self.selected_incident_id or self.view not in ("active", "archive"):
                            self.detail_scroll_offset = max(0, self.detail_scroll_offset - 6)
                        elif self.focus == "list" and num_rows > 0:
                            self.selected_index = max(0, self.selected_index - 5)
                    elif key == "PGDN":
                        if self.selected_incident_id or self.view not in ("active", "archive"):
                            self.detail_scroll_offset += 6
                        elif self.focus == "list" and num_rows > 0:
                            self.selected_index = min(num_rows - 1, self.selected_index + 5)
                    elif key == "RIGHT":
                        if not self.selected_incident_id and self.view in ("active", "archive") and num_rows > 0:
                            self.focus = "list"
                            self.notice = "Focused on incident list."
                    elif key == "TAB":
                        if not self.selected_incident_id and self.view in ("active", "archive") and num_rows > 0:
                            self.focus = "list" if self.focus == "menu" else "menu"
                            self.notice = f"Focus switched to {'incident list' if self.focus == 'list' else 'navigation menu'}."
                    elif key == "LEFT":
                        if self.selected_incident_id:
                            self.selected_incident_id = None
                            self.detail_scroll_offset = 0
                            self.notice = "Returned to incident list."
                        elif self.focus == "list":
                            self.focus = "menu"
                            self.notice = "Focused on navigation menu."
                    elif key in ("ENTER", "O"):
                        if not self.selected_incident_id and self.view in ("active", "archive"):
                            if self.focus == "menu" and key == "ENTER" and num_rows > 0:
                                self.focus = "list"
                                self.notice = "Focused on incident list. Press [Enter] again to open dossier."
                            elif num_rows > 0:
                                self.detail_scroll_offset = 0
                                self._select_by_index()
                            else:
                                self.notice = "No dossiers available in this tab."
                    elif key in ("B", "ESC"):
                        if self.selected_incident_id:
                            self.selected_incident_id = None
                            self.detail_scroll_offset = 0
                            self.notice = "Returned to incident list."
                        elif self.focus == "list":
                            self.focus = "menu"
                            self.notice = "Returned to navigation menu."
                        else:
                            self.view = "active"
                            self.selected_index = 0
                            self.list_scroll_offset = 0
                            self.detail_scroll_offset = 0
                    elif key in ("1", "2", "3", "4", "5"):
                        self.view = {
                            "1": "active",
                            "2": "archive",
                            "3": "health",
                            "4": "model",
                            "5": "telegram",
                        }[key]
                        self.selected_incident_id = None
                        self.selected_index = 0
                        self.list_scroll_offset = 0
                        self.detail_scroll_offset = 0
                        if self.view not in ("active", "archive"):
                            self.focus = "menu"
                        self.notice = f"Switched to tab {self._main_title()}."
                    elif key == "G":
                        if self.selected_incident_id or self.view in ("active", "archive"):
                            self._open_grafana_for_selected()
                        else:
                            self.notice = "Shortcut [G] is available in incident list or dossier detail."
                    elif key in ("A", "R", "C", "E"):
                        if self.selected_incident_id:
                            self._review_selected(
                                {"A": "APPROVE", "R": "REJECT", "C": "CORRECT", "E": "ESCALATE"}[key]
                            )
                        else:
                            self.notice = "Open a dossier first ([Enter] or [O]) before review."
                    else:
                        self.notice = f"Unrecognized key '{key}'. Use ↑/↓, ←/→/Tab, Enter, 1-5, B, or Q."
        finally:
            self._set_mouse_tracking(False)
            self.store.close()
        self.console.print("[yellow]SRE Command Center closed without automated actions.[/yellow]")
