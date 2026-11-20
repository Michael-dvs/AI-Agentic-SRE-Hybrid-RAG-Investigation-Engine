"""Unified Rich terminal console for human dossier review in the simulation lab."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
from typing import Any, Mapping, Sequence

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from observability.audit_chain import AuditHashChain
from orchestrator.handover import HandoverExporter
from orchestrator.review import AuthorizedReviewManager
from orchestrator.state_machine import WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher


ARCHIVE_STATES = {"CLOSED", "REJECTED", "MANUAL_TRIAGE_REQUIRED"}


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
            if pending_only and status != "PENDING_REVIEW":
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
    ) -> None:
        self.audit_chain = AuditHashChain(log_path=audit_path)
        self.review_manager = AuthorizedReviewManager(
            store=store,
            audit_chain=self.audit_chain,
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
    ) -> dict[str, Any]:
        action_upper = action.upper()
        corrections = None
        if action_upper == "CORRECT":
            statement = " ".join((corrected_hypothesis or "").split())
            if not statement:
                raise ValueError("Corrected hypothesis is required")
            corrections = {
                "hypotheses": [
                    {
                        "hypothesis_id": f"hyp-{dossier.get('incident_id', 'unknown')}-human-001",
                        "statement": statement[:2048],
                        "status": "SUPPORTED",
                        "confidence_score": 1.0,
                        "supporting_evidence_ids": [],
                        "refuting_evidence_ids": [],
                    }
                ]
            }

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
        )
        if action_upper != "APPROVE":
            review_event = result["review_event"]
            self.audit_chain.record_event(
                actor_ref="principal_reviewer",
                action="HUMAN_REVIEW_DECISION",
                target_ref=f"{review_event['incident_id']}:v{review_event['target_dossier_version']}",
                result_code="ALLOW",
                reason_code="OK",
                request_payload=review_event,
                incident_id=review_event["incident_id"],
                target_version=str(review_event["target_dossier_version"]),
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
        self.telegram = telegram or TelegramDispatcher()
        self.health = health or ServiceHealthInspector()
        self.costs = costs or CostMetricsReader()
        self.view = "active"
        self.selected_incident_id: str | None = None
        self.notice = "Pilih insiden untuk menelaah dossier."

    def render(self, *, width: int | None = None) -> RenderableType:
        terminal_width = width or self.console.size.width
        navigation = Panel(self._navigation(), title="Navigasi", border_style="cyan")
        main = Panel(self._main_content(), title=self._main_title(), border_style="white")
        actions = Panel(self._action_bar(), title="Review Action Bar", border_style="yellow")

        if terminal_width < 100:
            return Group(navigation, main, actions)

        two_panel = Table.grid(expand=True)
        two_panel.add_column(width=32)
        two_panel.add_column(ratio=1)
        two_panel.add_row(navigation, main)
        return Group(two_panel, actions)

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
            ("Q", "Keluar"),
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

    def _main_content(self) -> RenderableType:
        if self.view in {"active", "archive"}:
            rows = self.repository.active_dossiers() if self.view == "active" else self.repository.archived_dossiers()
            if self.selected_incident_id:
                dossier = self.repository.latest_dossier(self.selected_incident_id)
                if dossier:
                    return self._dossier_detail(dossier)
            return self._incident_table(rows)
        if self.view == "health":
            return self._health_table(self.health.inspect())
        if self.view == "model":
            dossiers = self.repository.active_dossiers() or self.repository.archived_dossiers()
            active_model = "N/A"
            if dossiers:
                reproducibility = dossiers[0]["dossier"].get("reproducibility", {})
                active_model = str(reproducibility.get("model_version", "N/A"))
            return self._model_panel(self.costs.read(), active_model)
        return self._telegram_panel()

    def _incident_table(self, rows: list[dict[str, Any]]) -> RenderableType:
        if not rows:
            reason = "Tidak ada dossier yang menunggu review." if self.view == "active" else "Belum ada dossier arsip."
            return Text(f"{reason}\nGunakan [B] untuk kembali atau pilih menu lain.", style="dim")
        table = Table(expand=True)
        table.add_column("No.", justify="right", width=4)
        table.add_column("Incident")
        table.add_column("Severity")
        table.add_column("Service")
        table.add_column("State")
        for index, row in enumerate(rows, start=1):
            incident = row["incident"]
            dossier = row["dossier"]
            state = str(incident.get("current_state", "unknown"))
            display_state = "ESCALATED" if state == "MANUAL_TRIAGE_REQUIRED" else state
            table.add_row(
                str(index),
                str(dossier.get("incident_id", incident["incident_id"])),
                str(dossier.get("severity", "unknown")).upper(),
                str(dossier.get("service_id", incident.get("service_id") or "unknown")),
                display_state,
            )
        return Group(table, Text("[O] Buka dossier berdasarkan nomor.", style="bold"))

    def _dossier_detail(self, dossier: Mapping[str, Any]) -> RenderableType:
        impact = dossier.get("impact_summary") if isinstance(dossier.get("impact_summary"), Mapping) else {}
        services = impact.get("affected_services") or dossier.get("investigation_scope") or [dossier.get("service_id", "unknown")]
        hypotheses = dossier.get("hypotheses") if isinstance(dossier.get("hypotheses"), list) else []
        citations = dossier.get("sop_citations") if isinstance(dossier.get("sop_citations"), list) else []
        evidence_source = dossier.get("evidence") or dossier.get("evidence_items")
        evidence = evidence_source if isinstance(evidence_source, list) else []

        header = Table.grid(expand=True)
        header.add_column(ratio=1)
        header.add_column(ratio=1)
        header.add_row("Incident", str(dossier.get("incident_id", "unknown")))
        header.add_row("Severity", str(dossier.get("severity", "unknown")).upper())
        header.add_row("Services", ", ".join(str(item) for item in services))
        header.add_row("Status", str(dossier.get("review_summary", {}).get("status", "PENDING_REVIEW")))
        header.add_row("Auto remediation", "DISABLED | auto_action_triggered=False")

        symptom = Text(str(impact.get("observed_symptoms") or dossier.get("message") or "Tidak ada gejala tercatat."))
        hypothesis_table = Table(expand=True)
        hypothesis_table.add_column("Rank", width=5)
        hypothesis_table.add_column("Hypothesis")
        hypothesis_table.add_column("Support", width=14)
        hypothesis_table.add_column("Confidence", width=12)
        for rank, hypothesis in enumerate(hypotheses, start=1):
            if not isinstance(hypothesis, Mapping):
                continue
            statement = hypothesis.get("statement") or hypothesis.get("hypothesis_statement") or hypothesis.get("title") or hypothesis.get("description", "")
            support = hypothesis.get("support_status") or hypothesis.get("evaluation_status") or hypothesis.get("status", "INCONCLUSIVE")
            confidence = hypothesis.get("confidence_score")
            confidence_text = f"{float(confidence):.0%}" if isinstance(confidence, (int, float)) else "N/A"
            hypothesis_table.add_row(str(hypothesis.get("rank", rank)), str(statement), str(support), confidence_text)
        if not hypothesis_table.rows:
            hypothesis_table.add_row("-", "Belum ada hipotesis", "INCONCLUSIVE", "N/A")

        citation_text = Text()
        for item in citations:
            if isinstance(item, Mapping):
                citation_text.append(
                    f"{item.get('doc_id') or item.get('document_id', 'Runbook')} | "
                    f"{item.get('section_path') or item.get('section', 'bagian tidak tersedia')}\n"
                )
        if not citation_text.plain:
            citation_text.append("Tidak ada sitasi SOP aktif.", style="dim")

        evidence_text = Text()
        for item in evidence:
            if isinstance(item, Mapping):
                evidence_text.append(f"{item.get('evidence_id', 'unknown')} | {item.get('tool_name', 'source unknown')}\n")
        if not evidence_text.plain:
            evidence_text.append("Tidak ada bukti telemetri terverifikasi.", style="dim")

        return Group(
            header,
            Panel(symptom, title="Observed Symptoms"),
            hypothesis_table,
            Panel(citation_text, title="Runbook SOP Citations"),
            Panel(evidence_text, title="Verified Evidence IDs"),
        )

    @staticmethod
    def _health_table(snapshot: Mapping[str, Any]) -> RenderableType:
        services = snapshot.get("services", [])
        if not services:
            return Text(f"Status: {snapshot.get('status')}\n{snapshot.get('reason', 'Tidak ada data health.')}", style="yellow")
        table = Table(expand=True)
        table.add_column("Service")
        table.add_column("Container State")
        table.add_column("Health")
        for service in services:
            table.add_row(str(service["name"]), str(service["state"]), str(service["health"]))
        return table

    @staticmethod
    def _model_panel(snapshot: Mapping[str, Any], active_model: str) -> RenderableType:
        table = Table.grid(padding=(0, 2))
        table.add_row("Active model", active_model)
        if snapshot.get("status") != "OK":
            table.add_row("C15 metrics", str(snapshot.get("status")))
            table.add_row("Metrics source", str(snapshot.get("source")))
            table.add_row("Accounting note", "Tidak ada nilai yang difabrikasi.")
            return table
        metrics = snapshot["metrics"]
        table.add_row("Tracked incidents", str(metrics.get("total_incidents_tracked", "N/A")))
        table.add_row("Total tokens", str(metrics.get("total_tokens_consumed", "N/A")))
        table.add_row("Shadow cost USD", str(metrics.get("total_shadow_cost_usd", "N/A")))
        table.add_row("P95 intake to dossier ms", str(metrics.get("p95_intake_to_dossier_ms", "N/A")))
        return table

    def _telegram_panel(self) -> RenderableType:
        mode = "ACTIVE OUTBOUND" if self.telegram.configured else "DRY-RUN"
        details = Text()
        details.append(f"Status: {mode}\n", style="bold green" if self.telegram.configured else "bold yellow")
        details.append("Direction: outbound notification only\n")
        details.append("Inbound listener: DISABLED\n")
        details.append("Remote command execution: NOT IMPLEMENTED\n")
        details.append("Credentials are read from TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return details

    def _action_bar(self) -> Text:
        if self.selected_incident_id:
            return Text("[A] APPROVE  [R] REJECT  [C] CORRECT  [E] ESCALATE  [B] BACK", style="bold")
        return Text(f"[O] OPEN  [B] BACK  | {self.notice}")

    def _select_by_index(self) -> None:
        rows = self.repository.active_dossiers() if self.view == "active" else self.repository.archived_dossiers()
        if not rows:
            self.notice = "Tidak ada dossier untuk dibuka."
            return
        choice = Prompt.ask("Nomor dossier", console=self.console, default="1")
        try:
            selected = rows[int(choice) - 1]
        except (ValueError, IndexError):
            self.notice = "Nomor dossier tidak valid."
            return
        self.selected_incident_id = str(selected["dossier"]["incident_id"])
        self.notice = f"Dossier {self.selected_incident_id} dibuka."

    def _review_selected(self, action: str) -> None:
        if not self.selected_incident_id:
            self.notice = "Pilih dossier lebih dahulu."
            return
        dossier = self.repository.latest_dossier(self.selected_incident_id)
        if dossier is None:
            self.notice = "Dossier tidak ditemukan."
            return
        rationale = Prompt.ask("Rationale", console=self.console)
        corrected = None
        target = None
        if action == "CORRECT":
            corrected = Prompt.ask("Corrected root-cause hypothesis", console=self.console)
        elif action == "ESCALATE":
            target = Prompt.ask("Escalation target", console=self.console, default="SRE_LEAD_ONCALL")
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
            self.notice = f"Review gagal: {type(exc).__name__}: {exc}"
            return
        self.notice = f"{action} tercatat; auto_action_triggered={result['auto_action_triggered']}."
        self.selected_incident_id = None

    def run(self) -> None:
        """Run a line-oriented keyboard loop that works without mouse support."""
        try:
            while True:
                self.console.clear()
                self.console.print(self.render())
                command = Prompt.ask("Command", console=self.console).strip().upper()
                if command == "Q":
                    self.notice = "Console ditutup tanpa tindakan otomatis."
                    break
                if command in {"1", "2", "3", "4", "5"}:
                    self.view = {"1": "active", "2": "archive", "3": "health", "4": "model", "5": "telegram"}[command]
                    self.selected_incident_id = None
                elif command == "O" and self.view in {"active", "archive"}:
                    self._select_by_index()
                elif command == "B":
                    self.selected_incident_id = None
                    self.view = "active"
                elif command in {"A", "R", "C", "E"}:
                    self._review_selected({"A": "APPROVE", "R": "REJECT", "C": "CORRECT", "E": "ESCALATE"}[command])
                else:
                    self.notice = "Command tidak dikenal. Gunakan 1-5, O, A/R/C/E/B, atau Q."
        finally:
            self.store.close()
