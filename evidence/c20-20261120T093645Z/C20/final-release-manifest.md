# Final Release Manifest (`E20` — Immutable Freeze untuk Chapter 21)

- **Release Freeze ID:** `c20-20261120T093645Z`
- **Frozen At (UTC):** `2026-11-20T09:36:46.251088Z`
- **Status:** `FROZEN_FOR_C21_HOLDOUT_EVALUATION`
- **Git Base Commit:** `2e5559ed8f9bf3f8d232fb3d986a0576c8ea1601`
- **Manifest Self SHA-256:** `bc17ccad777b2eae440028557749b201a6c37725a8ca8083ba9af04d42bb7f20`
- **H-G4 Seal Status:** `VERIFIED_SEALED`

## 1. Versi & Hash Komponen Terbeku

| Aset / Komponen | Versi / Jumlah | SHA-256 |
|---|---|---|
| Source Tree (`161` files) | 9 direktori kode | `10c3235882ab75e1286f18cc1204792009d053b5ee1677c4a202fd3bcc74f665` |
| Prompt Template (`HYPOTHESIS_SCHEMA`) | C13/C14 frozen | `71975c945f0347f3f97f44705e7cc049e726649083c3a4c037bb41548fb8f4a5` |
| Contract Schemas (`C02`) | 20 skema JSON | `ef40fc00d64bad87d7f8f45ffe0af366095d9faec338815287726778c609d663` |
| Knowledge Base (`kb_active_alias`) | `kb-idx-20261111-v1` (20 docs, 71 chunks) | `c9ee96dac3bb07b43a5230b1a881e63131250c8de77ca791ea002c8a810f5129` |
| Workflow / Policy / Tool Schema | `v1.0.0` / `v1.0.0` / `v1.0` | terikat pada `source_tree_sha256` |

## 2. Ringkasan Hash per Direktori Kode Sumber

| Direktori | Status | Jumlah Berkas | Directory SHA-256 |
|---|---|---:|---|
| `console/` | `NOT_PRESENT` | 0 | N/A (Unified TUI console resides in orchestrator/usability_console.py and scripts/sre_dashboard.py.) |
| `evaluator/` | `INCLUDED` | 5 | `a5c78e1ae6e8145d27df425c268c9121280328a5eb7ad13de345db4136c952ea` |
| `fault_harness/` | `INCLUDED` | 4 | `05ccfa8df702911fc01f6df9f69e4861736cc48ba22947764c7855b7f554e02b` |
| `gateway/` | `INCLUDED` | 14 | `ffd74ba790e02a018b1b6993a38d2a7f99920fad3a940513da896de38417e268` |
| `knowledge_base/` | `INCLUDED` | 63 | `0cbe530ba607d5258b1a00fa170747f436a078276dd34a5d08136953ca8a7d67` |
| `observability/` | `INCLUDED` | 16 | `3cf93f87faf1b35b27d31f234669d979e1ff30f879c495c00b93e2e25008adba` |
| `orchestrator/` | `INCLUDED` | 17 | `a23680582037ed80b7bda987d509f8b61064a078a64a9b3e8ca26b02ee334a4d` |
| `scripts/` | `INCLUDED` | 19 | `f434100ffc6f89ad43f1e19e436bd54198039ae8b49bac247639feba2bbfa86f` |
| `services/` | `INCLUDED` | 21 | `7c2b9166c51cf14be65a7aa86d4e217b30a04b7b4f076a1111051b86ace673f8` |
| `traffic/` | `INCLUDED` | 2 | `91d031af06bb87a79ebfb3418eab1eb0a609ca2c1e79921f5a507370218eaedd` |
