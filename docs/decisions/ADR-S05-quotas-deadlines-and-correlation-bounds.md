# ADR-S05: Kuota Tool, Batas Jendela Waktu, Deadline Workflow, Retry/Backoff, dan Batas Korelasi Alert

- **ID Keputusan:** `ADR-S05`
- **Status:** `PROPOSED` (Mekanisme Penegakan Kontrak Disetujui; Angka Batas Runtime Dikalibrasi & Dikunci pada C08/C10 sebelum Gate G1/G2)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C08`, `C09`, `C10`, `C11`, `C20`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/tool-policy-design.md`, `evidence/c02-20261109T070500Z/C02/workflow-contract.md`

---

## 1. Konteks & Permasalahan

Tanpa batas numerik yang tegas pada jendela waktu kueri, jumlah titik data, kedalaman graf dependensi, jumlah pemanggilan tool per insiden, dan deduplikasi alert storm, sistem berisiko mengalami kehabisan memori (OOM di bawah batas 8 GiB) atau loop pemanggilan LLM/tool tanpa henti (`MCP-02`, `OPS-01`). Namun, menyamakan angka fixture pengujian kontrak (`TEST-ONLY`) dengan konfigurasi runtime sebelum mengukur latensi aktual di lab dapat menyebabkan *false timeout*.

---

## 2. Keputusan Mekanisme (`ACCEPTED`) vs Parameter Kandidat (`PROPOSED`)

1. **Mekanisme Penegakan Deterministik (`ACCEPTED`):**
   - MCP Gateway (`CMP-INV-04`) wajib membaca batas kebijakan yang terikat pada `policy_version` saat startup; jika konfigurasi batas tidak tersedia, gateway gagal *readiness check* (*fail-closed*).
   - Pelanggaran batas durasi (`end - start > max_window_seconds`) atau urutan waktu (`start >= end`) **wajib ditolak** dengan `WINDOW_EXCEEDED` / `INVALID_TIME_RANGE`—dilarang memotong jendela secara diam-diam (*no silent clamping*, `MCP-02`).
   - Pelanggaran batas jumlah item/poin/hop **wajib ditolak** dengan `LIMIT_EXCEEDED`.
   - Retry hanya diizinkan untuk error transien (`SOURCE_UNAVAILABLE`, `BACKEND_TIMEOUT`) menggunakan *exponential backoff + jitter* selama sisa anggaran (`remaining_tool_budget` & `remaining_workflow_deadline`) masih mencukupi. Error kebijakan/validasi (`FORBIDDEN_SCOPE`, `SCHEMA_INVALID`, `TOOL_NOT_ALLOWED`, `WINDOW_EXCEEDED`) **dilarang di-retry**.
2. **Pemisahan Fixture `TEST-ONLY` vs Kandidat Angka Runtime (`PROPOSED` untuk C08/C10):**

| Parameter Kebijakan | Nilai Fixture `TEST-ONLY` (C02 §7.4 / `POL-01`..`03`) | Kandidat Angka Runtime Lab (`PROPOSED` — Dikunci di C08/C10) |
|---|---|---|
| `max_window_seconds` (per kueri tool) | `900` detik (15 menit) | Kandidat `900`–`1800` detik |
| `max_points` (`get_service_metrics`) | `100` titik | Kandidat `60`–`120` titik |
| `max_hits` (`search_error_logs`) | `50` baris | Kandidat `25`–`50` baris (`<= 32 KiB` payload) |
| `max_dependency_depth` | `2` hop | Kandidat `2`–`3` hop |
| `max_tool_calls_per_incident` | `3` (pada spike `SPK-C08-05`) | Kandidat `8`–`12` panggilan tool per insiden |
| `workflow_deadline_seconds` (Intake-to-Dossier) | `10` detik (pada spike `SPK-C08-05`) | Kandidat `90`–`120` detik (selaras target P95 `<= 120s`) |
| `alert_dedup_window_ttl_seconds` (`OPS-01`) | `300` detik | Kandidat `300` detik (5 menit) per fingerprint `(service_id, environment, error_code, alert_type, bucket)` |

---

## 3. Konsekuensi

- **Positif:** Memisahkan logika pengujian batas (`POL-01`..`POL-03`) dari tuning operasional lab, sambil memastikan tidak ada request tak terbatas yang lolos ke Prometheus/Loki/Tempo.
- **Tindak Lanjut Wajib:** Chapter C08 dan C10 wajib menetapkan dan membekukan tabel parameter `policy_version: "pol-v1.0.0"` berdasarkan pengukuran beban aktual.

