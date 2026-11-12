# ADR-S07: Disposisi Fitur Opsional Mock APM (`get_apm_health`) dan Dummy ITSM Ticket Handover (`AT-017`)

- **ID Keputusan:** `ADR-S07`
- **Status:** `PROPOSED` (Kontrak Ekstensi Bersyarat Didefinisikan; Disposisi Akhir Ditetapkan pada C08/G1 dan C16/G3)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C08`, `C09`, `C16`, `C21`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/tool-policy-design.md`, `evidence/c02-20261109T070500Z/C02/workflow-contract.md`

---

## 1. Konteks & Permasalahan

Proposal dan BRD menyebut dua kapabilitas opsional/kondisional:
1. Tool ke-5 `get_apm_health` ("hanya jika sumber APM simulasi tersedia", `AGENTS.md` §6.3).
2. Integrasi handover ke sistem tiket ITSM dummy setelah persetujuan reviewer manusia (`FR-OUT-007`, `AT-017`).

---

## 2. Keputusan

1. **`get_apm_health` Bersifat Conditional (`DEFERRED TO C08`):**
   - Pada baseline awal C02–C07, hanya 4 tool read-only wajib (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`) yang diaktifkan di MCP Gateway (`tool-result.v1.schema.json`).
   - `get_apm_health` **tidak** boleh dipublikasikan ke model kecuali sumber mock APM benar-benar dibangun dan disahkan melalui pembaruan ADR ini di C08. Dilarang membuat adapter yang mengembalikan data APM rekaan.
2. **Dummy ITSM Ticket Handover (`FR-OUT-007`, `AT-017` — `CONDITIONAL FOR C16`):**
   - Jika diaktifkan pada C16, pembuatan tiket dummy lokal hanya boleh dipicu **setelah** `review-event.v1` berstatus `decision: "approve"` untuk `target_dossier_hash` yang valid, dengan `auto_action_triggered: false` (hanya mencatat payload serah terima tiket lokal, tanpa koneksi ke ServiceNow/Jira eksternal dan tanpa aksi remediasi terhadap layanan).
   - Jika pemilik proyek memutuskan tidak menyertakan komponen tiket dummy pada C16, `AT-017` dicatat secara eksplisit sebagai `OPTIONAL_NOT_SELECTED` pada matriks evaluasi.

