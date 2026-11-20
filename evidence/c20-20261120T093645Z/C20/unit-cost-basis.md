# Rekonsiliasi Basis Biaya Unit (`AT-015`, `KPI-14`) & Konsumsi Sumber Daya (C20)

- **Run ID:** `c20-20261120T093645Z`
- **Actual Cash Spend Lab (`TBD-09`):** `$0.00 USD` (Plafon: `$0.00`, compliant=`True`)
- **Peak Process RSS:** `266.920 MiB` (Batas lab: `8192.0 MiB`, compliant=`True`)
- **Docker Container Metrics:** `UNAVAILABLE`

> Biaya tunai aktual lab adalah $0.00 (TBD-09). Shadow unit cost USD dihitung dari tarif referensi observability/cost_tracker.py dan memisahkan run berhasil vs gagal/timeout serta membedakan run deterministic_baseline (0 token LLM) dari run agentic_llm.

## 1. Pemisahan Biaya: Successful Runs vs Failed/Timed-Out Runs

| Kategori Eksekusi | Jumlah Run | Prompt Tokens | Completion Tokens | Embedding Tokens | Total Tokens | Tool Calls | Shadow Cost (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Successful Runs** (C15 + C19 + C20 Cap/Fallback + C20 Probe) | 89 | 4300 | 720 | 768 | 5788 | 72 | `$0.004693` |
| **Failed / Timed-Out Runs** (C20 Aborted Drills + C20 Timeout Probe) | 3 | 11847 | 3072 | 256 | 15175 | 3 | `$0.003775` |
| **Gabungan Seluruh Percobaan** | 92 | 16147 | 3792 | 1024 | 20963 | 75 | `$0.008468` |

## 2. Kalkulasi `KPI-14` (Termasuk Beban Failed Runs)

- **Rumus (`Roadmap §8.5` & `evaluator/scorer.py`):** `(successful_shadow_cost_usd + failed_shadow_cost_usd) / completed_count`
- **KPI-14 (Seluruh Run Teramati / 89 Completed):** `$0.000095 USD / completed incident`
- **KPI-14 Slice `agentic_llm` (2 completed + 1 failed timeout):** `$0.002634 USD / completed LLM incident` (rata-rata `10481.50` token/completed LLM run)
