# Bukti Uji Canary/Publish, Rollback Deterministik & Local Backup/Restore (C20)

- **Run ID:** `c20-20261120T093645Z`
- **Generated At (UTC):** `2026-11-20T09:36:45.787388Z`
- **Result:** **4/4 PASS** (`all_passed=True`)
- **Zero Auto-Remediation (`RULE-008`, `HUM-01`):** `auto_remediation_triggered=False`

| Komponen | Requirement | Status | Ringkasan Verifikasi |
|---|---|---|---|
| `workflow_and_tool_schema` | `NFR-014` | **PASS** | Hash kembali identik (`True`); canary 2400s ditolak (`WINDOW_EXCEEDED`), post-rollback OK, 3601s ditolak (`WINDOW_EXCEEDED`) |
| `model_and_prompt_template` | `NFR-014` | **PASS** | Canary `manual_fallback` -> rollback `replay-stable-v1` (`agentic_llm`); state insiden lama utuh (`True`) |
| `kb_index_alias_and_cache` | `FR-RAG-008` | **PASS** | Alias `kb_active_alias` rollback ke `kb-idx-20261111-v1`; hash identik (`True`); v1 obsolete dikecualikan (`True`); cache dibersihkan |
| `local_state_and_audit_chain` | `NFR-014` | **PASS** | Korupsi SQLite & audit terdeteksi; restore `PRAGMA integrity_check=ok`; audit chain valid pasca-restore & pasca-append (`4` events) |
