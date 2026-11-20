"""5-Dimension Human Review Rubric & Pilot Defects Registry (C19, KPI-06, HUM-01, AT-010, BRD §15.4)."""

from __future__ import annotations

from math import isfinite
import re
from statistics import median
from typing import Any, Mapping, Sequence

from evaluator.manual_baseline import assert_no_gt_leak

RUBRIC_DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "evidence_sufficiency",
    "actionability",
    "clarity",
    "uncertainty_handling",
)

ALLOWED_DECISIONS: tuple[str, ...] = (
    "APPROVED",
    "APPROVED_WITH_MINOR_EDIT",
    "REJECTED",
)

ALLOWED_DEFECT_CATEGORIES: tuple[str, ...] = (
    "USABILITY",
    "PERFORMANCE",
    "RAG_NAVIGATION",
    "BASELINE_BIAS",
)

ALLOWED_DEFECT_SEVERITIES: tuple[str, ...] = (
    "P1-CRITICAL",
    "P2-HIGH",
    "P3-MEDIUM",
    "P3-LOW",
)

_DEFECT_ID_RE = re.compile(r"^C19-DEF-\d{3}$")


class PilotRubricError(ValueError):
    """Raised when a 5-dimension rubric entry or pilot defect record violates governance rules."""


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def validate_rubric_entry(entry: Mapping[str, Any]) -> None:
    """Validate one 5-dimension reviewer assessment record."""
    try:
        assert_no_gt_leak(entry)
    except Exception as exc:
        raise PilotRubricError(str(exc)) from exc

    incident_id = entry.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id.startswith("inc-"):
        raise PilotRubricError(f"Invalid incident_id in rubric entry: {incident_id!r}")

    if entry.get("auto_action_triggered") is not False:
        raise PilotRubricError("HUM-01 / RULE-008 violation: auto_action_triggered must be False")

    if entry.get("assessment_kind") != "self_review_lab_owner":
        raise PilotRubricError("assessment_kind must be 'self_review_lab_owner'")
    if entry.get("label_source") != "SELF_EVALUATED_DEVELOPER_LABELS":
        raise PilotRubricError("label_source must be 'SELF_EVALUATED_DEVELOPER_LABELS'")

    scores = entry.get("scores")
    if not isinstance(scores, Mapping) or set(scores.keys()) != set(RUBRIC_DIMENSIONS):
        raise PilotRubricError(f"scores must contain exact keys {RUBRIC_DIMENSIONS}")
    for dim in RUBRIC_DIMENSIONS:
        val = scores.get(dim)
        if not isinstance(val, int) or isinstance(val, bool) or not (1 <= val <= 5):
            raise PilotRubricError(f"Dimension {dim!r} score must be an integer 1..5, got {val!r}")

    sys_tti = entry.get("system_time_to_dossier_seconds")
    human_sec = entry.get("human_review_effort_seconds")
    if not _is_finite_number(sys_tti) or sys_tti < 0:
        raise PilotRubricError(f"system_time_to_dossier_seconds must be >= 0, got {sys_tti!r}")
    if not _is_finite_number(human_sec) or human_sec <= 0:
        raise PilotRubricError(f"human_review_effort_seconds must be > 0, got {human_sec!r}")

    decision = entry.get("decision")
    if decision not in ALLOWED_DECISIONS:
        raise PilotRubricError(f"decision must be one of {ALLOWED_DECISIONS}, got {decision!r}")

    accepted = entry.get("accepted_without_substantial_rework")
    if not isinstance(accepted, bool):
        raise PilotRubricError("accepted_without_substantial_rework must be a boolean")
    if decision == "REJECTED" and accepted is True:
        raise PilotRubricError("REJECTED decision cannot set accepted_without_substantial_rework=True")
    if decision == "APPROVED" and accepted is False:
        raise PilotRubricError("APPROVED decision without edit must set accepted_without_substantial_rework=True")


def build_rubric_entry(
    *,
    incident_id: str,
    service_id: str,
    case_label: str,
    scores: Mapping[str, int],
    decision: str,
    accepted_without_substantial_rework: bool,
    system_time_to_dossier_seconds: float,
    human_review_effort_seconds: float,
    tui_actions_applied: Sequence[str],
    final_dossier_version: int,
    final_dossier_hash: str,
    final_state: str,
    reviewer_notes: str,
    auto_action_triggered: bool = False,
    assessment_kind: str = "self_review_lab_owner",
    label_source: str = "SELF_EVALUATED_DEVELOPER_LABELS",
) -> dict[str, Any]:
    """Construct and validate a 5-dimension rubric entry."""
    mean_score = round(sum(int(scores[d]) for d in RUBRIC_DIMENSIONS) / len(RUBRIC_DIMENSIONS), 2)
    entry = {
        "incident_id": incident_id,
        "service_id": service_id,
        "case_label": case_label,
        "scores": {dim: int(scores[dim]) for dim in RUBRIC_DIMENSIONS},
        "mean_dimension_score": mean_score,
        "decision": decision,
        "accepted_without_substantial_rework": accepted_without_substantial_rework,
        "system_time_to_dossier_seconds": round(float(system_time_to_dossier_seconds), 3),
        "human_review_effort_seconds": round(float(human_review_effort_seconds), 3),
        "tui_actions_applied": list(tui_actions_applied),
        "final_dossier_version": int(final_dossier_version),
        "final_dossier_hash": final_dossier_hash,
        "final_state": final_state,
        "auto_action_triggered": auto_action_triggered,
        "assessment_kind": assessment_kind,
        "label_source": label_source,
        "reviewer_notes": reviewer_notes,
    }
    validate_rubric_entry(entry)
    return entry


def to_scorer_review_fields(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the review sub-object expected by evaluator.scorer.score_cases."""
    validate_rubric_entry(entry)
    return {
        "accepted_without_substantial_rework": entry["accepted_without_substantial_rework"],
        "label_source": entry["label_source"],
    }


def summarize_rubric(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize 5-dimension rubric scores and KPI-06 acceptance rate."""
    if not entries:
        raise PilotRubricError("Cannot summarize empty rubric entries")
    validated = list(entries)
    for item in validated:
        validate_rubric_entry(item)

    dim_means = {
        dim: round(sum(int(item["scores"][dim]) for item in validated) / len(validated), 3)
        for dim in RUBRIC_DIMENSIONS
    }
    overall_mean = round(sum(dim_means.values()) / len(RUBRIC_DIMENSIONS), 3)
    accepted_count = sum(1 for item in validated if item["accepted_without_substantial_rework"])
    decision_counts = {
        dec: sum(1 for item in validated if item["decision"] == dec)
        for dec in ALLOWED_DECISIONS
    }
    sys_ttis = [float(item["system_time_to_dossier_seconds"]) for item in validated]
    human_efforts = [float(item["human_review_effort_seconds"]) for item in validated]

    return {
        "reviewed_count": len(validated),
        "dimension_means": dim_means,
        "overall_mean_score": overall_mean,
        "accepted_without_substantial_rework_count": accepted_count,
        "kpi_06_acceptance_rate": round(accepted_count / len(validated), 4),
        "decision_counts": decision_counts,
        "median_system_tti_seconds": round(median(sys_ttis), 3),
        "median_human_review_effort_seconds": round(median(human_efforts), 3),
        "auto_action_triggered_count": sum(1 for item in validated if item["auto_action_triggered"]),
        "assessment_kind": "self_review_lab_owner",
        "label_source": "SELF_EVALUATED_DEVELOPER_LABELS",
        "honesty_disclosure": (
            "Skor rubrik 5 dimensi dan KPI-06 dinilai oleh pengembang tunggal lab "
            "(SELF_EVALUATED_DEVELOPER_LABELS / self_review_lab_owner) per ADR-S08."
        ),
    }


def build_pilot_defects_registry() -> list[dict[str, Any]]:
    """Return operational friction and usability defects identified during C19 shadow pilot."""
    defects = [
        {
            "defect_id": "C19-DEF-001",
            "category": "USABILITY",
            "severity": "P2-HIGH",
            "component": "orchestrator/usability_console.py (SREDashboard.run)",
            "title": "Reflow layout terminal TUI tertunda saat resize mendadak",
            "description": (
                "Loop input Prompt.ask dengan console.clear() per perintah tidak memicu reflow "
                "otomatis ketika ukuran terminal berubah antara <100 kolom dan >=100 kolom "
                "sebelum pengguna menekan Enter."
            ),
            "observed_during": "Uji navigasi TUI dua panel pada layar lebar (120 cols) dan sempit (72 cols).",
            "remediation_plan_c20": (
                "Tambahkan dukungan refresh viewport eksplisit dan manajemen ukuran panel responsif "
                "serta pengujian regresi layout pada berbagai lebar terminal di C20."
            ),
            "status": "OPEN_FOR_C20",
        },
        {
            "defect_id": "C19-DEF-002",
            "category": "USABILITY",
            "severity": "P2-HIGH",
            "component": "orchestrator/usability_console.py (SREDashboard._dossier_detail)",
            "title": "Pratinjau isi bukti telemetri dan kutipan teks SOP belum tersedia langsung di TUI",
            "description": (
                "Panel detail insiden hanya menampilkan baris ringkas doc_id | section_path dan "
                "evidence_id | tool_name tanpa cuplikan isi log/metrik atau excerpt SOP, sehingga "
                "penelaah masih perlu membuka berkas handover untuk verifikasi detail saat koreksi."
            ),
            "observed_during": "Penelaahan skenario DEV-03 (SOP-LEDGER-001 v2) dan DEV-06 (aksi CORRECT v1->v2).",
            "remediation_plan_c20": (
                "Tambahkan tampilan ringkasan terikat-panjang (bounded excerpt) yang aman dan ter-sanitasi "
                "untuk evidence summary dan metadata versi SOP di panel detail TUI pada C20."
            ),
            "status": "OPEN_FOR_C20",
        },
        {
            "defect_id": "C19-DEF-003",
            "category": "PERFORMANCE",
            "severity": "P3-MEDIUM",
            "component": "orchestrator/usability_console.py & observability/audit_chain.py",
            "title": "Pembacaan ulang penuh audit JSONL saat inisialisasi ReviewActionController",
            "description": (
                "Setiap instansiasi AuditHashChain/ReviewActionController membaca seluruh log audit "
                "append-only secara sinkron; berpotensi menambah latensi I/O ketika jumlah insiden "
                "meningkat pada uji burst 100 alert dan konkurensi C20."
            ),
            "observed_during": "Simulasi multi-skenario berurutan dengan pencatatan audit rantai SHA-256.",
            "remediation_plan_c20": (
                "Profilkan I/O audit append dan evaluasi tail/incremental verification pada skenario "
                "OPS-01 burst 100 alert serta gelombang konkurensi 5/20/50 di C20."
            ),
            "status": "OPEN_FOR_C20",
        },
        {
            "defect_id": "C19-DEF-004",
            "category": "RAG_NAVIGATION",
            "severity": "P2-HIGH",
            "component": "orchestrator/review.py & orchestrator/dossier.py (DossierSerializer.serialize)",
            "title": "Revisi append-only CORRECT v(N)->v(N+1) tidak mewariskan field evidence/sop_citations dossier terserialisasi",
            "description": (
                "Ketika AuthorizedReviewManager.submit_review(decision='edit') memanggil "
                "DossierSerializer.serialize(edit_ctx, revision=new_rev), edit_ctx memakai kunci "
                "dossier terserialisasi ('evidence', 'sop_citations', 'alert_received_at') sementara "
                "DossierSerializer membaca kunci konteks investigasi ('evidence_items', "
                "'runbook_citations', 'event_time'). Akibatnya revisi v2 kehilangan daftar bukti "
                "dan sitasi SOP dari v1 dan menurunkan status hipotesis koreksi."
            ),
            "observed_during": "Eksekusi skenario DEV-06 (inc-pilot-dev-sc07-006) saat menjalankan aksi TUI CORRECT -> APPROVE.",
            "remediation_plan_c20": (
                "Normalisasi pemetaan field dossier terserialisasi di AuthorizedReviewManager/DossierSerializer "
                "pada C20 agar revisi v(N+1) mempertahankan evidence, sop_citations, dan alert_received_at v(N)."
            ),
            "status": "OPEN_FOR_C20",
        },
        {
            "defect_id": "C19-DEF-005",
            "category": "BASELINE_BIAS",
            "severity": "P3-MEDIUM",
            "component": "evaluator/manual_baseline.py & evaluator/pilot_rubric.py",
            "title": "Keterbatasan validasi solo-developer dan potensi carryover familiarity",
            "description": (
                "Pengukuran manual baseline dan penilaian rubrik 5 dimensi dilakukan oleh pemilik proyek "
                "tunggal (SELF_EVALUATED_DEVELOPER_LABELS / TBD-02 / TBD-08) tanpa reviewer SME bank "
                "eksternal independen."
            ),
            "observed_during": "Penyusunan manual-timing-protocol-and-records dan review-rubric C19.",
            "remediation_plan_c20": (
                "Pertahankan label caveat eksplisit pada laporan KPI-06/KPI-08 di C21 dan dokumentasikan "
                "kebutuhan validasi panel SME independen pada analisis kesenjangan enterprise C23."
            ),
            "status": "DOCUMENTED_LIMITATION",
        },
        {
            "defect_id": "C19-DEF-006",
            "category": "RAG_NAVIGATION",
            "severity": "P2-HIGH",
            "component": "orchestrator/investigator.py & knowledge_base/retrieval/prefilter.py",
            "title": "Ketidakselarasan kontrak index_version_policy ('active_only' vs 'kb_active_alias') dan formulasi query_text",
            "description": (
                "DeterministicInvestigator._step_retrieved mengirim index_version_policy='active_only', "
                "sedangkan StrictPreFilter.is_chunk_applicable hanya menerima 'latest', 'kb_active_alias', "
                "atau ID versi indeks aktual (mis. 'kb-idx-20261111-v1'), sehingga retrieval mengembalikan "
                "status no_match (NO_APPLICABLE_RUNBOOK) kecuali dinormalisasi."
            ),
            "observed_during": "Eksekusi awal lab shadow pilot DEV dengan ToolDispatcher default.",
            "remediation_plan_c20": (
                "Selaraskan index_version_policy menjadi 'kb_active_alias' pada DeterministicInvestigator "
                "(atau dukung alias 'active_only' di StrictPreFilter) serta perkaya formulasi query_text "
                "dari ringkasan error log aktual pada C20 sebelum pembekuan rilis final."
            ),
            "status": "OPEN_FOR_C20",
        },
    ]
    validate_pilot_defects(defects)
    return defects


def validate_pilot_defects(defects: Sequence[Mapping[str, Any]]) -> None:
    """Validate structure, uniqueness, and GT isolation of pilot defect records."""
    if not defects:
        raise PilotRubricError("Pilot defects registry must not be empty")
    seen_ids: set[str] = set()
    for defect in defects:
        try:
            assert_no_gt_leak(defect)
        except Exception as exc:
            raise PilotRubricError(str(exc)) from exc
        defect_id = defect.get("defect_id")
        if not isinstance(defect_id, str) or not _DEFECT_ID_RE.match(defect_id):
            raise PilotRubricError(f"Invalid defect_id: {defect_id!r}")
        if defect_id in seen_ids:
            raise PilotRubricError(f"Duplicate defect_id: {defect_id!r}")
        seen_ids.add(defect_id)

        if defect.get("category") not in ALLOWED_DEFECT_CATEGORIES:
            raise PilotRubricError(f"Invalid defect category: {defect.get('category')!r}")
        if defect.get("severity") not in ALLOWED_DEFECT_SEVERITIES:
            raise PilotRubricError(f"Invalid defect severity: {defect.get('severity')!r}")
        for field_name in ("component", "title", "description", "observed_during", "remediation_plan_c20", "status"):
            val = defect.get(field_name)
            if not isinstance(val, str) or not val.strip():
                raise PilotRubricError(f"Defect {defect_id} missing required string field {field_name!r}")


def render_review_rubric_markdown(payload: Mapping[str, Any]) -> str:
    """Render review-rubric.md report."""
    summary = payload["summary"]
    means = summary["dimension_means"]
    lines = [
        "# Penilaian Rubrik Reviewer 5 Dimensi — Lab Shadow Pilot (C19)",
        "",
        f"- **Run ID:** `{payload.get('run_id', 'c19-rubric')}`",
        f"- **Assessment Kind:** `{summary['assessment_kind']}`",
        f"- **Label Source:** `{summary['label_source']}`",
        f"- **Reviewed Dossiers:** {summary['reviewed_count']}",
        f"- **KPI-06 (Accepted Without Substantial Rework):** {summary['accepted_without_substantial_rework_count']}/{summary['reviewed_count']} (`{summary['kpi_06_acceptance_rate'] * 100:.2f}%`)",
        f"- **Zero Auto-Remediation (`HUM-01`, `RULE-008`):** `auto_action_triggered_count == {summary['auto_action_triggered_count']}`",
        f"- **Median System TTI (`KPI-07`):** {summary['median_system_tti_seconds']:.3f} s",
        f"- **Median Human Review Effort:** {summary['median_human_review_effort_seconds']:.3f} s",
        "",
        f"> {summary['honesty_disclosure']}",
        "",
        "## 1. Rata-Rata Skor per Dimensi (Skala 1–5)",
        "",
        "| Dimensi Rubrik (`BRD §15.4`) | Skor Rata-Rata |",
        "|---|---:|",
        f"| Correctness | {means['correctness']:.2f} / 5.00 |",
        f"| Evidence Sufficiency | {means['evidence_sufficiency']:.2f} / 5.00 |",
        f"| Actionability | {means['actionability']:.2f} / 5.00 |",
        f"| Clarity | {means['clarity']:.2f} / 5.00 |",
        f"| Uncertainty Handling | {means['uncertainty_handling']:.2f} / 5.00 |",
        f"| **Overall Mean** | **{summary['overall_mean_score']:.2f} / 5.00** |",
        "",
        "## 2. Rincian Penilaian per Dossier Pilot (`DEV`)",
        "",
        "| Incident ID | Layanan | Decision | No Substantial Rework | Corr | Evid | Act | Clar | Unc | Mean | System TTI (s) | Human Review (s) | Auto Action |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in payload["entries"]:
        sc = item["scores"]
        lines.append(
            f"| `{item['incident_id']}` | `{item['service_id']}` | `{item['decision']}` | "
            f"`{item['accepted_without_substantial_rework']}` | "
            f"{sc['correctness']} | {sc['evidence_sufficiency']} | {sc['actionability']} | "
            f"{sc['clarity']} | {sc['uncertainty_handling']} | {item['mean_dimension_score']:.2f} | "
            f"{item['system_time_to_dossier_seconds']:.3f} | {item['human_review_effort_seconds']:.2f} | "
            f"`{item['auto_action_triggered']}` |"
        )
    lines.append("")
    lines.append("## 3. Catatan Penelaahan per Insiden")
    lines.append("")
    for item in payload["entries"]:
        lines.append(
            f"- **`{item['incident_id']}`** (`{' -> '.join(item['tui_actions_applied'])}`, "
            f"v{item['final_dossier_version']}, state=`{item['final_state']}`): {item['reviewer_notes']}"
        )
    lines.append("")
    return "\n".join(lines)


def render_pilot_defects_markdown(payload: Mapping[str, Any]) -> str:
    """Render pilot-defects.md registry report for C20 handover."""
    lines = [
        "# Registri Cacat & Friksi Operasional Lab Shadow Pilot (C19 -> C20)",
        "",
        f"- **Run ID:** `{payload.get('run_id', 'c19-defects')}`",
        f"- **Total Temuan:** {len(payload['defects'])}",
        "",
        "| Defect ID | Kategori | Keparahan | Komponen | Judul | Status |",
        "|---|---|---|---|---|---|",
    ]
    for d in payload["defects"]:
        lines.append(
            f"| `{d['defect_id']}` | `{d['category']}` | `{d['severity']}` | "
            f"`{d['component']}` | {d['title']} | `{d['status']}` |"
        )
    lines.append("")
    lines.append("## Detail Temuan & Rencana Perbaikan Chapter 20")
    lines.append("")
    for d in payload["defects"]:
        lines.extend(
            [
                f"### {d['defect_id']}: {d['title']}",
                f"- **Kategori / Keparahan:** `{d['category']}` / `{d['severity']}`",
                f"- **Komponen:** `{d['component']}`",
                f"- **Deskripsi:** {d['description']}",
                f"- **Konteks Observasi:** {d['observed_during']}",
                f"- **Rencana Perbaikan (C20):** {d['remediation_plan_c20']}",
                f"- **Status:** `{d['status']}`",
                "",
            ]
        )
    return "\n".join(lines)
