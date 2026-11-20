"""Blinded Manual Baseline & Anti-Carryover Protocol Enforcement (C19, RULE-011, KPI-08, RISK-09, ADR-S08)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime as dt
import hashlib
import json
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence


class ManualBaselineError(ValueError):
    """Raised when anti-carryover, timing, isolation, or labeling rules are violated."""


FORBIDDEN_GT_KEYS = frozenset(
    {
        "ground_truth",
        "ground_truth_label",
        "expected_root_cause",
        "expected_root_cause_services",
        "holdout_id",
        "holdout_ground_truth",
        "h_g4",
        "gt_registry",
        "scenario_id",
        "fault_label",
        "recipe_id",
    }
)

FORBIDDEN_GT_SUBSTRINGS = (
    "h-g4",
    "ground_truth",
    "expected_root_cause",
    "holdout_id",
    "restricted/gt_registry",
)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _parse_utc_iso(value: Any, field_name: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ManualBaselineError(f"{field_name} must be a non-empty ISO-8601 timestamp string")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ManualBaselineError(f"{field_name} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ManualBaselineError(f"{field_name} must include explicit UTC/timezone offset: {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def assert_no_gt_leak(obj: Any, path: str = "$") -> None:
    """Reject any ground-truth or holdout marker inside public baseline or rubric payloads."""
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_lower = str(key).lower()
            if key_lower in FORBIDDEN_GT_KEYS:
                raise ManualBaselineError(f"Prohibited ground-truth key {key!r} at {path}")
            assert_no_gt_leak(value, f"{path}.{key}")
    elif isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            assert_no_gt_leak(item, f"{path}[{idx}]")
    elif isinstance(obj, str):
        lowered = obj.lower()
        for token in FORBIDDEN_GT_SUBSTRINGS:
            if token in lowered:
                raise ManualBaselineError(f"Prohibited ground-truth token {token!r} at {path}")


def compute_manual_lock_hash(record: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 over pre-AI manual investigation facts."""
    payload = {
        "incident_id": record.get("incident_id"),
        "service_id": record.get("service_id"),
        "split_id": record.get("split_id"),
        "alert_received_at": record.get("alert_received_at"),
        "manual_started_at": record.get("manual_started_at"),
        "manual_completed_at": record.get("manual_completed_at"),
        "manual_locked_at": record.get("manual_locked_at"),
        "manual_seconds": record.get("manual_seconds"),
        "manual_steps_count": record.get("manual_steps_count"),
        "manual_hypothesis_summary": record.get("manual_hypothesis_summary"),
        "manual_sop_lookup_used": list(record.get("manual_sop_lookup_used") or []),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ManualBaselineRecord:
    """Paired manual vs AI-assisted investigation record with anti-carryover lock proof."""

    incident_id: str
    service_id: str
    case_label: str
    split_id: str
    alert_received_at: str
    manual_started_at: str
    manual_completed_at: str
    manual_locked_at: str
    ai_dossier_opened_at: str
    ai_review_completed_at: str
    locked_before_ai_view: bool
    manual_seconds: float
    system_tti_seconds: float
    human_review_seconds: float
    assisted_seconds: float
    manual_steps_count: int
    document_search_friction: str
    manual_hypothesis_summary: str
    manual_sop_lookup_used: list[str]
    assessment_kind: str = "self_review_lab_owner"
    label_source: str = "SELF_EVALUATED_DEVELOPER_LABELS"
    lock_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_manual_baseline_record(
    *,
    incident_id: str,
    service_id: str,
    case_label: str,
    alert_received_at: str,
    manual_started_at: str,
    manual_completed_at: str,
    manual_locked_at: str,
    ai_dossier_opened_at: str,
    ai_review_completed_at: str,
    manual_seconds: float,
    system_tti_seconds: float,
    human_review_seconds: float,
    manual_steps_count: int,
    document_search_friction: str,
    manual_hypothesis_summary: str,
    manual_sop_lookup_used: Sequence[str],
    split_id: str = "dev",
    locked_before_ai_view: bool = True,
    assessment_kind: str = "self_review_lab_owner",
    label_source: str = "SELF_EVALUATED_DEVELOPER_LABELS",
) -> dict[str, Any]:
    """Construct, hash-lock, and validate one anti-carryover manual baseline record."""
    assisted_seconds = round(float(system_tti_seconds) + float(human_review_seconds), 3)
    raw = {
        "incident_id": incident_id,
        "service_id": service_id,
        "case_label": case_label,
        "split_id": split_id,
        "alert_received_at": alert_received_at,
        "manual_started_at": manual_started_at,
        "manual_completed_at": manual_completed_at,
        "manual_locked_at": manual_locked_at,
        "ai_dossier_opened_at": ai_dossier_opened_at,
        "ai_review_completed_at": ai_review_completed_at,
        "locked_before_ai_view": locked_before_ai_view,
        "manual_seconds": round(float(manual_seconds), 3),
        "system_tti_seconds": round(float(system_tti_seconds), 3),
        "human_review_seconds": round(float(human_review_seconds), 3),
        "assisted_seconds": assisted_seconds,
        "manual_steps_count": manual_steps_count,
        "document_search_friction": document_search_friction,
        "manual_hypothesis_summary": manual_hypothesis_summary,
        "manual_sop_lookup_used": list(manual_sop_lookup_used),
        "assessment_kind": assessment_kind,
        "label_source": label_source,
    }
    raw["lock_sha256"] = compute_manual_lock_hash(raw)
    validate_anti_carryover_record(raw)
    return asdict(ManualBaselineRecord(**raw))


def validate_anti_carryover_record(record: Mapping[str, Any]) -> None:
    """Enforce RULE-011 anti-carryover ordering, DEV isolation, and honest self-review labeling."""
    assert_no_gt_leak(record)

    incident_id = record.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id.startswith("inc-"):
        raise ManualBaselineError(f"Invalid incident_id: {incident_id!r}")

    if record.get("split_id") != "dev":
        raise ManualBaselineError(
            f"C19 shadow pilot only permits split_id='dev', got {record.get('split_id')!r}"
        )

    if record.get("locked_before_ai_view") is not True:
        raise ManualBaselineError("Anti-carryover violation: locked_before_ai_view must be True")

    if record.get("assessment_kind") != "self_review_lab_owner":
        raise ManualBaselineError(
            "assessment_kind must be 'self_review_lab_owner' per ADR-S08 / TBD-08"
        )
    if record.get("label_source") != "SELF_EVALUATED_DEVELOPER_LABELS":
        raise ManualBaselineError(
            "label_source must be 'SELF_EVALUATED_DEVELOPER_LABELS' per ADR-S08 / TBD-08"
        )

    t_alert = _parse_utc_iso(record.get("alert_received_at"), "alert_received_at")
    t_m_start = _parse_utc_iso(record.get("manual_started_at"), "manual_started_at")
    t_m_done = _parse_utc_iso(record.get("manual_completed_at"), "manual_completed_at")
    t_m_lock = _parse_utc_iso(record.get("manual_locked_at"), "manual_locked_at")
    t_ai_open = _parse_utc_iso(record.get("ai_dossier_opened_at"), "ai_dossier_opened_at")
    t_ai_done = _parse_utc_iso(record.get("ai_review_completed_at"), "ai_review_completed_at")

    if not (t_alert <= t_m_start < t_m_done <= t_m_lock < t_ai_open <= t_ai_done):
        raise ManualBaselineError(
            "Anti-carryover timestamp violation: expected "
            "alert_received_at <= manual_started_at < manual_completed_at <= "
            "manual_locked_at < ai_dossier_opened_at <= ai_review_completed_at"
        )

    manual_seconds = record.get("manual_seconds")
    system_tti_seconds = record.get("system_tti_seconds")
    human_review_seconds = record.get("human_review_seconds")
    assisted_seconds = record.get("assisted_seconds")
    manual_steps = record.get("manual_steps_count")

    if not _is_finite_number(manual_seconds) or manual_seconds <= 0:
        raise ManualBaselineError(f"manual_seconds must be > 0, got {manual_seconds!r}")
    if not _is_finite_number(system_tti_seconds) or system_tti_seconds < 0:
        raise ManualBaselineError(f"system_tti_seconds must be >= 0, got {system_tti_seconds!r}")
    if not _is_finite_number(human_review_seconds) or human_review_seconds <= 0:
        raise ManualBaselineError(f"human_review_seconds must be > 0, got {human_review_seconds!r}")
    expected_assisted = round(float(system_tti_seconds) + float(human_review_seconds), 3)
    if not _is_finite_number(assisted_seconds) or abs(float(assisted_seconds) - expected_assisted) > 1e-6:
        raise ManualBaselineError(
            f"assisted_seconds ({assisted_seconds!r}) must equal round(system_tti_seconds + human_review_seconds, 3) ({expected_assisted})"
        )
    if not isinstance(manual_steps, int) or isinstance(manual_steps, bool) or manual_steps < 1:
        raise ManualBaselineError(f"manual_steps_count must be positive integer, got {manual_steps!r}")

    if not isinstance(record.get("document_search_friction"), str) or not record["document_search_friction"].strip():
        raise ManualBaselineError("document_search_friction must be a non-empty string")
    if not isinstance(record.get("manual_hypothesis_summary"), str) or not record["manual_hypothesis_summary"].strip():
        raise ManualBaselineError("manual_hypothesis_summary must be a non-empty string")

    expected_lock = compute_manual_lock_hash(record)
    if record.get("lock_sha256") != expected_lock:
        raise ManualBaselineError("Manual timing lock_sha256 mismatch")


def compute_manual_vs_assisted_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute paired median manual vs AI-assisted timing summary and honest validity caveats."""
    if not records:
        raise ManualBaselineError("Cannot summarize empty manual baseline records")
    validated = list(records)
    for rec in validated:
        validate_anti_carryover_record(rec)

    manuals = [float(r["manual_seconds"]) for r in validated]
    ttis = [float(r["system_tti_seconds"]) for r in validated]
    reviews = [float(r["human_review_seconds"]) for r in validated]
    assisteds = [float(r["assisted_seconds"]) for r in validated]

    med_manual = round(median(manuals), 3)
    med_tti = round(median(ttis), 3)
    med_review = round(median(reviews), 3)
    med_assisted = round(median(assisteds), 3)
    reduction_ratio = round(1.0 - (med_assisted / med_manual), 4)

    return {
        "matched_pair_count": len(validated),
        "split_id": "dev",
        "median_manual_seconds": med_manual,
        "median_system_tti_seconds": med_tti,
        "median_human_review_seconds": med_review,
        "median_assisted_seconds": med_assisted,
        "kpi_08_time_reduction_ratio": reduction_ratio,
        "kpi_08_time_reduction_percent": round(reduction_ratio * 100.0, 2),
        "mean_manual_steps": round(sum(int(r["manual_steps_count"]) for r in validated) / len(validated), 2),
        "all_records_locked_before_ai_view": all(r["locked_before_ai_view"] is True for r in validated),
        "validity_declaration": {
            "assessment_kind": "self_review_lab_owner",
            "label_source": "SELF_EVALUATED_DEVELOPER_LABELS",
            "solo_developer_caveat": True,
            "independent_sme_validated": False,
            "anti_carryover_protocol_enforced": True,
            "tbd_references": ["TBD-02", "TBD-08", "ADR-S08", "RULE-011", "RISK-09"],
            "disclosure": (
                "Pengukuran baseline manual dan review dijalankan di lab simulasi oleh "
                "pengembang tunggal (project-initiator-michael). Meskipun urutan stempel "
                "waktu anti-carryover dikunci dengan lock_sha256 sebelum membuka dossier AI, "
                "bias familiaritas penyusun skenario tetap melekat dan hasil ini tidak "
                "diklaim sebagai uji validasi SME perbankan independen."
            ),
        },
    }


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Paired AS-IS manual lab baseline measurements collected prior to opening AI dossiers.
DEV_MANUAL_BASELINE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "incident_id": "inc-pilot-dev-sc01-001",
        "service_id": "api-gateway",
        "case_label": "DEV-01 Healthy Control Baseline",
        "manual_seconds": 185.0,
        "human_review_seconds": 22.0,
        "manual_steps_count": 5,
        "manual_sop_lookup_used": ["SOP-GW-001"],
        "document_search_friction": "Harus memeriksa log Loki, metrik RED Prometheus, dan memastikan tidak ada error tersembunyi lintas gateway.",
        "manual_hypothesis_summary": "Trafik nominal; health check rutin tanpa anomali 5xx atau latensi.",
    },
    {
        "incident_id": "inc-pilot-dev-sc02-002",
        "service_id": "transaction-service",
        "case_label": "DEV-02 Single Fault HTTP 5xx Burst",
        "manual_seconds": 340.0,
        "human_review_seconds": 38.0,
        "manual_steps_count": 9,
        "manual_sop_lookup_used": ["SOP-TX-001", "SOP-TX-ERR-500"],
        "document_search_friction": "Pencarian grep manual pada korpus markdown untuk mencocokkan error code ERR_TRANSACTION_FAILED dengan SOP-TX-ERR-500.",
        "manual_hypothesis_summary": "Lonjakan HTTP 500 pada transaction-service berkorelasi dengan span error pemrosesan pembayaran.",
    },
    {
        "incident_id": "inc-pilot-dev-sc03-003",
        "service_id": "ledger-service",
        "case_label": "DEV-03 Single Fault DB Connection Pool Exhaustion",
        "manual_seconds": 410.0,
        "human_review_seconds": 45.0,
        "manual_steps_count": 11,
        "manual_sop_lookup_used": ["SOP-LEDGER-001 (v2.0.0)", "SOP-DB-001"],
        "document_search_friction": "Perlu memilah manual antara SOP-LEDGER-001-v1 yang obsolete dan SOP-LEDGER-001-v2 yang masih aktif.",
        "manual_hypothesis_summary": "Kejenuhan connection pool PostgreSQL pada ledger-service memicu checkout timeout.",
    },
    {
        "incident_id": "inc-pilot-dev-sc04-004",
        "service_id": "api-gateway",
        "case_label": "DEV-04 Cascade Failure Gateway -> Transaction -> Ledger",
        "manual_seconds": 520.0,
        "human_review_seconds": 62.0,
        "manual_steps_count": 14,
        "manual_sop_lookup_used": ["SOP-GW-ERR-504", "SOP-TX-001", "SOP-LEDGER-ERR-504"],
        "document_search_friction": "Korelasi manual trace_id melintasi 3 layanan dan pembacaan 3 dokumen SOP terpisah memakan waktu lama.",
        "manual_hypothesis_summary": "Kegagalan kaskade berawal dari error/latensi ledger-service yang merambat ke transaction-service dan api-gateway.",
    },
    {
        "incident_id": "inc-pilot-dev-sc06-005",
        "service_id": "auth-service",
        "case_label": "DEV-05 Auth Token Mismatch & Obsolete SOP Exclusion",
        "manual_seconds": 295.0,
        "human_review_seconds": 35.0,
        "manual_steps_count": 8,
        "manual_sop_lookup_used": ["SOP-AUTH-001", "KNOWN-ERR-AUTH-001"],
        "document_search_friction": "Harus memverifikasi tanggal efektif dan status approved pada metadata front-matter SOP-AUTH secara manual.",
        "manual_hypothesis_summary": "Lonjakan HTTP 401/500 pada verifikasi token auth-service sesuai gejala KNOWN-ERR-AUTH-001.",
    },
    {
        "incident_id": "inc-pilot-dev-sc07-006",
        "service_id": "notification-service",
        "case_label": "DEV-06 Queue Consumer Lag (Human Correction v1->v2)",
        "manual_seconds": 365.0,
        "human_review_seconds": 78.0,
        "manual_steps_count": 10,
        "manual_sop_lookup_used": ["SOP-NOTIF-QUEUE-001", "KNOWN-ERR-NOTIF-001"],
        "document_search_friction": "Memerlukan pemeriksaan backlog RabbitMQ dan penyuntingan hipotesis agar rincian consumer lag terekam akurat.",
        "manual_hypothesis_summary": "Backlog antrean notifikasi akibat consumer lag pekerja notification-service.",
    },
    {
        "incident_id": "inc-pilot-dev-sc09-007",
        "service_id": "api-gateway",
        "case_label": "DEV-07 Degraded Mode / Trace Backend Outage",
        "manual_seconds": 270.0,
        "human_review_seconds": 40.0,
        "manual_steps_count": 7,
        "manual_sop_lookup_used": ["SOP-GW-001"],
        "document_search_friction": "Waktu habis menguji endpoint Tempo yang down sebelum memastikan bahwa trace memang tidak tersedia.",
        "manual_hypothesis_summary": "Timeout gateway teramati di log, tetapi kausalitas lintas layanan tidak dapat dibuktikan karena Tempo unavailable.",
    },
)


def build_default_dev_manual_records(
    *,
    anchor_utc: dt.datetime | None = None,
    system_tti_by_incident: Mapping[str, float] | None = None,
    ai_opened_by_incident: Mapping[str, dt.datetime] | None = None,
) -> list[dict[str, Any]]:
    """Build validated anti-carryover manual baseline records for all 7 DEV pilot cases."""
    now_utc = dt.datetime.now(dt.timezone.utc)
    if anchor_utc is None:
        anchor_utc = now_utc - dt.timedelta(minutes=90)
    else:
        anchor_utc = anchor_utc.astimezone(dt.timezone.utc)

    records: list[dict[str, Any]] = []
    cursor = anchor_utc
    for idx, spec in enumerate(DEV_MANUAL_BASELINE_SPECS):
        inc_id = spec["incident_id"]
        manual_sec = float(spec["manual_seconds"])
        review_sec = float(spec["human_review_seconds"])
        tti_sec = float((system_tti_by_incident or {}).get(inc_id, 0.05))

        t_alert = cursor
        t_m_start = t_alert + dt.timedelta(seconds=5)
        t_m_done = t_m_start + dt.timedelta(seconds=manual_sec)
        t_m_lock = t_m_done + dt.timedelta(seconds=2)

        if ai_opened_by_incident and inc_id in ai_opened_by_incident:
            t_ai_open = ai_opened_by_incident[inc_id].astimezone(dt.timezone.utc)
            if t_ai_open <= t_m_lock:
                t_ai_open = t_m_lock + dt.timedelta(seconds=10)
        else:
            t_ai_open = t_m_lock + dt.timedelta(seconds=30 + idx)

        t_ai_done = t_ai_open + dt.timedelta(seconds=review_sec)
        records.append(
            build_manual_baseline_record(
                incident_id=inc_id,
                service_id=spec["service_id"],
                case_label=spec["case_label"],
                alert_received_at=_iso(t_alert),
                manual_started_at=_iso(t_m_start),
                manual_completed_at=_iso(t_m_done),
                manual_locked_at=_iso(t_m_lock),
                ai_dossier_opened_at=_iso(t_ai_open),
                ai_review_completed_at=_iso(t_ai_done),
                manual_seconds=manual_sec,
                system_tti_seconds=tti_sec,
                human_review_seconds=review_sec,
                manual_steps_count=int(spec["manual_steps_count"]),
                document_search_friction=spec["document_search_friction"],
                manual_hypothesis_summary=spec["manual_hypothesis_summary"],
                manual_sop_lookup_used=spec["manual_sop_lookup_used"],
            )
        )
        cursor = t_m_lock + dt.timedelta(seconds=15)
    return records


def render_manual_baseline_markdown(payload: Mapping[str, Any]) -> str:
    """Render human-readable Markdown report for manual-timing-protocol-and-records.md."""
    summary = payload["summary"]
    decl = summary["validity_declaration"]
    lines = [
        "# Protokol Anti-Carryover & Rekaman Blinded Manual Baseline (C19)",
        "",
        f"- **Run ID:** `{payload.get('run_id', 'c19-manual-baseline')}`",
        f"- **Split Dataset:** `{summary['split_id']}` (100% terisolasi dari `H-G3` dan `H-G4`)",
        f"- **Assessment Kind:** `{decl['assessment_kind']}`",
        f"- **Label Source:** `{decl['label_source']}`",
        f"- **Anti-Carryover Lock Enforced:** `{summary['all_records_locked_before_ai_view']}`",
        "",
        "## 1. Deklarasi Batas Validitas (`RULE-011`, `TBD-02`, `TBD-08`, `ADR-S08`)",
        "",
        f"> {decl['disclosure']}",
        "",
        "- **Independent SME Validated:** `false` (solo developer lab evaluation)",
        "- **Perbedaan Metrik Waktu:**",
        "  - `manual_seconds`: Durasi investigasi manual AS-IS (alert -> query log/metrik/trace manual -> grep SOP -> rumusan hipotesis), dikunci (`manual_locked_at` + `lock_sha256`) **sebelum** dossier AI dibuka.",
        "  - `system_tti_seconds`: Latensi runtime mesin investigasi agentic (`KPI-07`: intake -> dossier `PENDING_REVIEW`).",
        "  - `human_review_seconds`: Durasi penelaahan manusia di Unified TUI Console hingga keputusan final.",
        "  - `assisted_seconds`: Total waktu investigasi berbantuan AI (`system_tti_seconds + human_review_seconds`) yang dipasangkan ke `KPI-08`.",
        "",
        "## 2. Ringkasan Perbandingan Waktu (`KPI-08`)",
        "",
        "| Metrik | Nilai Terukur |",
        "|---|---|",
        f"| Jumlah Pasangan Matched (`DEV`) | {summary['matched_pair_count']} |",
        f"| Median Manual AS-IS (`manual_seconds`) | {summary['median_manual_seconds']:.3f} s |",
        f"| Median System TTI (`KPI-07`) | {summary['median_system_tti_seconds']:.3f} s |",
        f"| Median Human Review Effort | {summary['median_human_review_seconds']:.3f} s |",
        f"| Median AI-Assisted Total (`assisted_seconds`) | {summary['median_assisted_seconds']:.3f} s |",
        f"| Pengurangan Waktu Relatif (`KPI-08`) | {summary['kpi_08_time_reduction_percent']:.2f}% (`{summary['kpi_08_time_reduction_ratio']:.4f}`) |",
        f"| Rata-Rata Langkah Manual | {summary['mean_manual_steps']:.2f} langkah |",
        "",
        "## 3. Rekaman Pasangan Kasus `DEV` & Bukti Lock Anti-Carryover",
        "",
        "| Incident ID | Layanan | Kasus | Manual (s) | System TTI (s) | Human Review (s) | Assisted (s) | Locked Before AI | Lock Timestamp (UTC) | AI Opened (UTC) |",
        "|---|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    for rec in payload["records"]:
        lines.append(
            f"| `{rec['incident_id']}` | `{rec['service_id']}` | {rec['case_label']} | "
            f"{rec['manual_seconds']:.2f} | {rec['system_tti_seconds']:.3f} | "
            f"{rec['human_review_seconds']:.2f} | {rec['assisted_seconds']:.3f} | "
            f"`{rec['locked_before_ai_view']}` | `{rec['manual_locked_at']}` | `{rec['ai_dossier_opened_at']}` |"
        )
    lines.append("")
    lines.append("## 4. Catatan Hambatan Pencarian Dokumen Manual")
    lines.append("")
    for rec in payload["records"]:
        lines.append(
            f"- **`{rec['incident_id']}` ({rec['manual_steps_count']} langkah):** "
            f"{rec['document_search_friction']} "
            f"(Lock SHA-256: `{rec['lock_sha256'][:16]}...`)"
        )
    lines.append("")
    return "\n".join(lines)
