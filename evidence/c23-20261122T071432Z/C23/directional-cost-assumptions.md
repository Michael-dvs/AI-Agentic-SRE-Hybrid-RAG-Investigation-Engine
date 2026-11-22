# Directional Enterprise Cost & TCO Assumptions (`E23`): `c23-20261122T071432Z`

- **Generated At (UTC):** `2026-11-22T07:14:32.283502Z`
- **Status:** `DIRECTIONAL_ESTIMATE_NOT_PROCUREMENT_QUOTE` *(bukan penawaran vendor atau anggaran pengadaan mengikat per `BRD §20.3`)*

## 1. Basis Biaya Empiris Terukur (`E20` & `E21`)
- **Actual Lab Cash Spend (`TBD-09`):** `$0.00 USD`
- **Blended Shadow Cost (90 completed runs `E20`+`E21`):** `$0.000097 USD / completed run`
- **Agentic LLM Slice (`E20`):** `$0.002634 USD / completed LLM run` (rata-rata `10481.5` token/run)
- **Tarif Referensi (`observability/cost_tracker.py`):** prompt `$0.00015/1k`, completion `$0.0006/1k`, embedding `$2e-05/1k`, tool call `$5e-05`

## 2. Ekstrapolasi Terarah Skala Enterprise (`1.000`–`10.000` Insiden/Bulan)

| Volume Insiden/Bulan | Rentang Token/Bulan (`10.5k`–`30k`) | Est. Shadow Cost Tier Ringan | Est. API Privat Kelas Enterprise (5x–15x) | Kebutuhan Infrastruktur & GPU Konseptual |
|---:|---|---|---|---|
| **1,000** | `10,500,000` – `30,000,000` | `$2.63` – `$7.54`/bln | `$13.15` – `$113.10`/bln | 1x small cluster + 1x shared inference GPU (L40S/A100) + HA Postgres/Qdrant |
| **5,000** | `52,500,000` – `150,000,000` | `$13.17` – `$37.69`/bln | `$65.85` – `$565.35`/bln | 3-node K8s + 2x HA inference GPU + observability cluster |
| **10,000** | `105,000,000` – `300,000,000` | `$26.34` – `$75.39`/bln | `$131.70` – `$1130.85`/bln | Multi-zone K8s + 2-4x dedicated inference GPUs + enterprise log/trace storage |

## 3. Penggerak Biaya Dominan & Larangan Klaim ROI
- On-premise / air-gapped GPU & NVMe storage infrastructure required by UU PDP / POJK data residency
- Human-in-the-Loop L1/L2 SRE dossier review time, KB SOP curation, and Model/Prompt Ops (BR-016, HUM-01)
- One-time engineering for AD/OIDC IAM, dynamic ServiceNow CMDB, bidirectional ITSM (CAP-05), and independent VAPT

> [!IMPORTANT] **Larangan Klaim ROI (`RULE-011` / `C19-DEF-005`):** C19 KPI-08 (-88.23%) relies on SELF_EVALUATED_DEVELOPER_LABELS and H-G4 KPI-08 is UNAVAILABLE; independent L1/L2 SRE study required in Phase 5B (CAP-04).
