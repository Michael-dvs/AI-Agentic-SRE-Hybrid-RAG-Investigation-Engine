# Penilaian Rubrik Reviewer 5 Dimensi — Lab Shadow Pilot (C19)

- **Run ID:** `c19-20261120T083752Z`
- **Assessment Kind:** `self_review_lab_owner`
- **Label Source:** `SELF_EVALUATED_DEVELOPER_LABELS`
- **Reviewed Dossiers:** 7
- **KPI-06 (Accepted Without Substantial Rework):** 6/7 (`85.71%`)
- **Zero Auto-Remediation (`HUM-01`, `RULE-008`):** `auto_action_triggered_count == 0`
- **Median System TTI (`KPI-07`):** 0.032 s
- **Median Human Review Effort:** 40.000 s

> Skor rubrik 5 dimensi dan KPI-06 dinilai oleh pengembang tunggal lab (SELF_EVALUATED_DEVELOPER_LABELS / self_review_lab_owner) per ADR-S08.

## 1. Rata-Rata Skor per Dimensi (Skala 1–5)

| Dimensi Rubrik (`BRD §15.4`) | Skor Rata-Rata |
|---|---:|
| Correctness | 4.43 / 5.00 |
| Evidence Sufficiency | 4.43 / 5.00 |
| Actionability | 4.14 / 5.00 |
| Clarity | 4.57 / 5.00 |
| Uncertainty Handling | 4.29 / 5.00 |
| **Overall Mean** | **4.37 / 5.00** |

## 2. Rincian Penilaian per Dossier Pilot (`DEV`)

| Incident ID | Layanan | Decision | No Substantial Rework | Corr | Evid | Act | Clar | Unc | Mean | System TTI (s) | Human Review (s) | Auto Action |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `inc-pilot-dev-sc01-001` | `api-gateway` | `APPROVED` | `True` | 5 | 4 | 4 | 5 | 5 | 4.60 | 0.042 | 22.00 | `False` |
| `inc-pilot-dev-sc02-002` | `transaction-service` | `APPROVED` | `True` | 5 | 5 | 4 | 5 | 4 | 4.60 | 0.032 | 38.00 | `False` |
| `inc-pilot-dev-sc03-003` | `ledger-service` | `APPROVED` | `True` | 5 | 5 | 5 | 4 | 4 | 4.60 | 0.029 | 45.00 | `False` |
| `inc-pilot-dev-sc04-004` | `api-gateway` | `APPROVED` | `True` | 5 | 4 | 4 | 4 | 4 | 4.20 | 0.034 | 62.00 | `False` |
| `inc-pilot-dev-sc06-005` | `auth-service` | `APPROVED` | `True` | 4 | 5 | 4 | 5 | 4 | 4.40 | 0.023 | 35.00 | `False` |
| `inc-pilot-dev-sc07-006` | `notification-service` | `APPROVED_WITH_MINOR_EDIT` | `False` | 3 | 4 | 4 | 4 | 4 | 3.80 | 0.029 | 78.00 | `False` |
| `inc-pilot-dev-sc09-007` | `api-gateway` | `APPROVED` | `True` | 4 | 4 | 4 | 5 | 5 | 4.40 | 0.032 | 40.00 | `False` |

## 3. Catatan Penelaahan per Insiden

- **`inc-pilot-dev-sc01-001`** (`APPROVE`, v1, state=`CLOSED`): Kontrol sehat tidak memicu hipotesis fault palsu; status INCONCLUSIVE aman dengan 0 error log.
- **`inc-pilot-dev-sc02-002`** (`APPROVE`, v1, state=`CLOSED`): Korelasi log ERR_TRANSACTION_FAILED, metrik RED, dan sitasi SOP-TX aktif tersaji jelas di TUI.
- **`inc-pilot-dev-sc03-003`** (`APPROVE`, v1, state=`CLOSED`): Retrieval hanya mengutip SOP-LEDGER-001 v2.0.0 yang approved dan mengecualikan v1.0.0 obsolete.
- **`inc-pilot-dev-sc04-004`** (`APPROVE`, v1, state=`CLOSED`): Korelasi graf dependensi mengidentifikasi asal kaskade dari ledger-service ke api-gateway.
- **`inc-pilot-dev-sc06-005`** (`APPROVE`, v1, state=`CLOSED`): Dokumen SOP-AUTH-001 aktif terambil dengan pembatasan layanan dan lingkungan yang tepat.
- **`inc-pilot-dev-sc07-006`** (`CORRECT -> APPROVE`, v2, state=`CLOSED`): Hipotesis awal terlalu umum sehingga dikoreksi melalui aksi TUI CORRECT (v1->v2) sebelum APPROVE; ditemukan cacat C19-DEF-004 pada preservasi bukti di v2.
- **`inc-pilot-dev-sc09-007`** (`APPROVE`, v1, state=`CLOSED`): Outage get_trace_summary dicatat jujur pada missing_sources dan menurunkan hipotesis ke INCONCLUSIVE (EV-02) tanpa fabrikasi span.
