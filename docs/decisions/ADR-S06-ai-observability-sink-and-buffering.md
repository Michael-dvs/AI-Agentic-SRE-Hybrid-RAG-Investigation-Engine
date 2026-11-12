# ADR-S06: Sink Audit Keamanan Independen, Sanitasi AI Observability, dan Strategi Hybrid LLM Router

- **ID Keputusan:** `ADR-S06`
- **Status:** `PROPOSED` (Kebijakan Keamanan & Urutan Routing LLM Disetujui; Evaluasi Jejak Memori Sink AI Observability pada C08/C15)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C08`, `C13`, `C15`, `C18`, `C20`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/architecture.md` §6.5, `evidence/c02-20261109T070500Z/C02/trust-boundaries.md`, `evidence/c02-20261109T070500Z/C02/contracts/audit-event.v1.schema.json`

---

## 1. Konteks & Permasalahan

Sistem membutuhkan:
1. Strategi pemanggilan LLM dengan biaya **`$0.00`** yang tahan terhadap pemadaman/rate-limit penyedia eksternal (`OPS-02`, `SC-13`).
2. Pemisahan tegas antara **Independent Security Audit Sink** (`CMP-GOV-02`) dan **Sanitized AI Observability Sink** (`CMP-GOV-03`, kandidat Langfuse) sesuai `AGENTS.md` §6.3 dan `NFR-SEC-004`.
3. Pengendalian memori agar kombinasi sink observability AI dan model fallback lokal tidak melampaui plafon **8 GiB Docker Lab** pada Mac 16 GB Apple Silicon.

---

## 2. Keputusan

1. **Urutan Routing Hybrid LLM (`CONFIRMED POLICY`):**
   - **Tier 1 (Primary):** Remote Free-Tier LLM API (kandidat: Google AI Studio Gemini Flash Free Tier / Groq / OpenRouter free models — dievaluasi kuota & kebijakan privasinya di C08/C13) melalui antarmuka abstrak `LLMProviderAdapter`. Hanya menerima payload sintetis yang telah melewati DLP/redaction gate (`sanitized: true`).
   - **Tier 2 (Secondary Fallback):** Local LLM via Ollama native macOS / Metal (`<= 3B` quantized 4-bit, mis. `qwen2.5:1.5b` / `llama3.2:1b`, kebutuhan RAM ~1.2–1.8 GiB) jika Tier 1 mengalami rate-limit (`429`), timeout, atau unreachability.
   - **Tier 3 (Tertiary Safe Degradation — `OPS-02`):** Deterministic Evidence-Only Dossier Mode (`investigation_mode: "manual_fallback"`). Jika Tier 1 dan Tier 2 tidak tersedia, koordinator tetap merakit draft dossier valid dari bukti telemetri dan sitasi SOP yang telah terkumpul untuk direview manusia.
2. **Independent Security Audit Sink (`ACCEPTED`):**
   - Disimpan secara lokal dan append-only (SQLite WAL + JSONL berantai hash `prev_event_hash -> event_hash` sesuai `audit-event.v1.schema.json`).
   - **Fail-Closed:** Kegagalan menulis event audit keamanan membatalkan aksi tool/transisi terkait; kegagalan sink AI observability (Langfuse) **tidak** boleh menghapus atau menggantikan audit keamanan.
3. **Sanitized AI Observability Sink & Larangan CoT (`PROPOSED` — Dievaluasi di C08/C15):**
   - Semua prompt/respons ke AI observability sink wajib disanitasi terlebih dahulu (`SEC-03`) dan **dilarang menyimpan *hidden chain-of-thought*** (`AGENTS.md` §6.3).
   - Karena stack Langfuse v3 self-hosted penuh membutuhkan ClickHouse + Postgres + Redis (~2.0+ GiB RAM), C08/C15 akan mengevaluasi apakah menggunakan Langfuse Cloud Free Tier (khusus payload sintetis tersanitasi), Langfuse v2 lightweight, atau OpenTelemetry JSONL AI Trace Collector lokal agar total RAM Docker Lab tetap `<= 8 GiB`.

---

## 3. Konsekuensi

- **Positif:** Menjamin kelangsungan investigasi dan jejak audit meskipun internet/API remote mati (`OPS-02`), menjaga biaya tetap `$0.00`, dan melindungi anggaran RAM 16 GB.
- **Tindak Lanjut Wajib:** C13 dan C15 wajib menguji skenario pemutusan jaringan LLM (`SC-13`) dan sanitasi PII/rahasia (`SEC-03`).

