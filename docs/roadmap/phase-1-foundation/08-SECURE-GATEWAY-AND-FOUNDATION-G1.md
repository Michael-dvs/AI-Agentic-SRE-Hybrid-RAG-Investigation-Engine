# C08 — Secure Gateway and Foundation G1

## 1. Chapter Information
- **Phase:** F1 — Foundation (Gate `G1`)
- **Status:** APPROVED (Diimplementasikan & diuji di evidence/c08-20261112T000000Z/C08/; Gate G1 PASSED)
- **Documentation status:** APPROVED
- **Implementation status:** VERIFIED (10/10 pytest PASS, 17/17 Boundary Tests PASS, Gate G1 PASSED)
- **Dependencies:** [C02 — Architecture, Contracts, and Evaluation Design](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), [C05 — Telemetry and Service Catalog](05-TELEMETRY-AND-SERVICE-CATALOG.md), [C07 — Hybrid Retrieval and Baselines](07-HYBRID-RETRIEVAL-AND-BASELINES.md), `G0 PASS` ([C01](01-SCOPE-DECISIONS-AND-G0.md)), penutupan `ADR-S03` (transport MCP/identitas gateway)
- **Next chapter:** [C09 — Read-Only Telemetry Adapters](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md)
- **Related requirements:** `BR-007`, `BR-009`, `BR-016`, `FR-AGT-002`, `FR-AGT-003`, `FR-AGT-004`, `RULE-001`, `RULE-002`, `RULE-003`, `RULE-004`, `RULE-012`, `NFR-001`, `NFR-003`, `NFR-005`, `NFR-012`, `NFR-017`, `NFR-019`, `KPI-09`, `KPI-10`, `KPI-11`, `OBJ-05`, `DEP-05`, `RISK-02`, `RISK-05`, `RISK-06`, `RISK-12`
- **Related acceptance tests:** `SEC-01` (build & test owner tahap *gateway boundary*), `SEC-02` (build owner pemisahan policy dari prompt), `SEC-03` (build & test owner tahap *pre-sink sanitizer*), `MCP-01` (build & test owner tahap *allowlist/gateway boundary*), `MCP-02` (build & test owner tahap penolakan *window* berlebih di gateway), `RAG-02` (build & test owner otorisasi scope lintas layanan), `AT-005` (build & test owner tahap *gateway boundary*), `AT-006` & `AT-007` (review bukti baseline untuk Gate G1), `AT-008` (build & test owner blokade path GT di gateway), `AT-014` (pengesahan ukuran sampel, split `H-G3`/`H-G4`, dan definisi KPI final di Gate G1)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *Authenticated Policy & Tool Gateway* yang menegakkan kontrol akses *read-only*, validasi skema input, pembatasan jendela waktu/kuota, redaksi data sensitif (`SEC-03`), dan pencatatan *append-only security audit* sebelum permintaan diteruskan ke backend mana pun, sekaligus mengeksekusi *capability spike* orkestrasi (`TBD-05`) dan menyelenggarakan **Review Gate G1 (Foundation Gate)**. Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) §2.2, Gate G1 tidak boleh diluluskan hanya dengan dokumen kontrak tertulis; penolakan atas kueri ilegal, *write request*, dan pelanggaran ACL harus dibuktikan secara nyata pada lapisan gateway di C08.

Setelah chapter ini selesai, sistem memiliki lapisan penegakan kebijakan deterministik di luar kendali prompt LLM, bukti eksperimental pemilihan *workflow coordinator* (`TBD-05`), penutupan seluruh keputusan wajib Gate G1 (`TBD-05`, `TBD-06`, `TBD-08`, `TBD-10`, `TBD-11`, `ADR-S04` s/d `ADR-S08`), serta rekaman keputusan **Gate G1 (`PASS` / `FAIL` / `BLOCKED`)** yang menjadi syarat mutlak sebelum memasuki Fase 2 ([C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md)).

## 3. Scope & Boundaries
### In Scope
- Implementasi *Authenticated Policy Gateway* dengan pemisahan identitas pemanggil (`investigator`, `reviewer`, `fault-harness`, `offline-evaluator`), *tool allowlist* ketat, validasi JSON Schema, batas `query_window`/`max_points`/`max_hits`/kuota, serta pemblokiran total atas *write/restart/deploy/shell/SQL/raw query* (`FR-AGT-002`–`004`, `MCP-01`, `MCP-02`).
- Implementasi *deterministic sanitizer/redactor* (`SEC-03`) dengan kebijakan `FAIL_CLOSED` dan *independent append-only security audit log* (`NFR-003`, `NFR-005`).
- Pengujian negatif tingkat *gateway boundary* untuk `SEC-01`, `SEC-03`, `MCP-01`, `MCP-02`, `RAG-02`, `AT-005`, dan `AT-008` (tanpa mengklaim integrasi adapter backend penuh yang baru dibangun di [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md)).
- Eksekusi *capability spike* kandidat mesin orkestrasi (`TBD-05`: uji *state persistence*, *restart/replay*, *cancellation*, *idempotency*, dan jejak memori terhadap plafon 8 GiB RAM).
- Penyelenggaraan evaluasi dan penandatanganan **Gate G1** atas bukti `E03`–`E08` serta pembekuan protokol evaluasi formal (`RULE-012`, `AT-014`).

### Out of Scope
- Adapter kueri penuh ke seluruh backend telemetri (dibangun di [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md)).
- Implementasi *state machine* investigasi insiden *end-to-end* (dibangun di [C11](../phase-2-controlled-integration/11-DURABLE-INVESTIGATION-WORKFLOW.md) setelah pilihan engine disahkan di C08).
- Melanjutkan ke [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md) apabila Gate G1 berstatus `FAIL` atau `BLOCKED`.

## 4. Prerequisites
- Bukti pelaksanaan fondasi dari [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) (`E02`), [C03](03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md) (`E03`), [C04](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md) (`E04`), [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md) (`E05`), [C06](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md) (`E06`), dan [C07](07-HYBRID-RETRIEVAL-AND-BASELINES.md) (`E07`) tersedia dan konsisten.
- Keputusan `ADR-S03` (transport MCP/HTTP, skema identitas kredensial terpisah, dan aturan isolasi jaringan lab) telah ditutup.
- Kriteria lulus *capability spike* orkestrasi dari rencana [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) tersedia.

## 5. Implementation Roadmap
1. **Pembangunan Authenticated Gateway, Allowlist, dan Schema/Policy Enforcement (`FR-AGT-002`–`004`)**
   - *Apa yang harus dilakukan:* Bangun layanan gateway yang memverifikasi identitas pemanggil dari *trusted context* (bukan dari *payload* model), hanya mengizinkan nama *tool* observasi yang terdaftar di *allowlist*, memvalidasi input terhadap JSON Schema [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), dan menolak (*reject*, bukan *silently clamp*) `query_window` atau jumlah item yang melebihi batas maksimum (`MCP-02`).
   - *Mengapa diperlukan:* Memastikan kebijakan keamanan dikendalikan oleh kode deterministik di luar jangkauan manipulasi prompt LLM (`RULE-003`, `RULE-004`).
   - *Expected output:* Layanan gateway berjalan dengan *policy enforcement* dan pencatatan *independent append-only audit log*.
   - *Cara memverifikasi:* Kirim permintaan valid dan invalid; pastikan permintaan yang melanggar batas ditolak dengan kode error bertipe (`WINDOW_EXCEEDED`, `FORBIDDEN_SCOPE`, `TOOL_NOT_ALLOWED`) sebelum menyentuh backend.
2. **Implementasi Sanitizer `SEC-03` (`FAIL_CLOSED`) dan Blokade Path Ground Truth (`AT-008`)**
   - *Apa yang harus dilakukan:* Pasang modul *redaction* wajib pada jalur keluar gateway menuju konteks model/log yang menyamarkan pola *synthetic PII/secret fixtures* dan memblokir seluruh *payload* jika sanitizer mengalami kegagalan, serta tambahkan aturan blokade eksplisit terhadap segala URI/path/tabel *ground truth* atau *fault harness*.
   - *Mengapa diperlukan:* Mencegah kebocoran rahasia sintetis (`NFR-003`, `NFR-012`) dan menjamin isolasi *ground truth* (`KPI-10`).
   - *Expected output:* Modul *pre-sink sanitizer* dan laporan uji `sanitizer-report`.
   - *Cara memverifikasi:* Umpankan *payload* berisi *synthetic secret/token/PII* dan simulasikan error pada sanitizer; pastikan 0 *fixture* mentah lolos dan kegagalan sanitizer menghentikan pengiriman data.
3. **Eksekusi Pengujian Negatif Boundary (`SEC-01`, `MCP-01`, `MCP-02`, `RAG-02`, `AT-005`)**
   - *Apa yang harus dilakukan:* Jalankan rangkaian uji negatif terotomasi terhadap gateway: kredensial tidak sah, permintaan lintas `service.name`/`environment`/`allowed_groups` (`SEC-01`, `RAG-02`), percobaan pemanggilan *tool* `restart`/`deploy`/`write`/`shell`/`SQL` (`MCP-01`), dan rentang waktu di atas batas maksimum (`MCP-02`).
   - *Mengapa diperlukan:* Membuktikan secara nyata kriteria keamanan Gate G1 sebelum adapter backend penuh dipasang di Fase 2.
   - *Expected output:* Berkas bukti `auth-policy-tests` dan `gateway-audit`.
   - *Cara memverifikasi:* Pastikan 100% permintaan negatif ditolak sebelum *dispatch*, tidak ada perubahan *state* layanan, dan setiap penolakan tercatat lengkap di *audit log*.
4. **Eksekusi Capability Spike Orkestrasi dan Penutupan ADR G1 (`TBD-05`, `ADR-S05`–`S08`)**
   - *Apa yang harus dilakukan:* Jalankan eksperimen kemampuan kandidat orkestrator (`TBD-05`: Dify self-hosted vs Custom Python coordinator / LangGraph) untuk menguji *durable state persistence*, *restart recovery*, *cancellation*, *idempotency*, dan pemakaian RAM di dalam batas 8 GiB, lalu dokumentasikan keputusan `TBD-05`, `TBD-06`, `TBD-08`, `TBD-10`, `TBD-11`, serta `ADR-S04` s/d `ADR-S08`.
   - *Mengapa diperlukan:* Mencegah pemilihan platform orkestrasi yang gagal melakukan *cancel/replay* atau menghabiskan memori lab pada Fase 2 (`RISK-06`, `RISK-07`).
   - *Expected output:* Laporan `orchestrator-capability-report` dan pembaruan status keputusan G1 di `docs/decisions/`.
   - *Cara memverifikasi:* Periksa bahwa pilihan orkestrator dan arsitektur RAG didukung bukti eksperimen nyata dan muat di dalam anggaran memori lab.
5. **Penyelenggaraan Review Gate G1 dan Pembekuan Protokol Evaluasi (`RULE-012`)**
   - *Apa yang harus dilakukan:* Audit kelengkapan bukti `E03` s/d `E08`, sahkan ukuran sampel eksak korpus kueri/insiden, stratifikasi `DEV`/`H-G3`/`H-G4` (dan kunci hash split `H-G3`/`H-G4`), denominator KPI, serta rekam keputusan Gate G1 pada `g1-record.md` (dan `docs/gates/`).
   - *Mengapa diperlukan:* Memenuhi tata kelola Gate G1 (`Proposal Bab 12`, `BRD §17.1`) sebelum integrasi Fase 2 dimulai.
   - *Expected output:* Paket bukti `E08` dan rekaman keputusan `g1-record.md`.
   - *Cara memverifikasi:* Pastikan seluruh daftar periksa Gate G1 terpenuhi tanpa *critical blocker* terbuka.

## 6. Expected Deliverables
- Layanan *Authenticated Policy Gateway* yang aktif dengan *allowlist*, validasi skema, batas kuota/jendela waktu, redaktor `SEC-03`, dan *independent append-only security audit*.
- Laporan hasil eksperimen *capability spike* orkestrator (`orchestrator-capability-report`) dan ADR yang disahkan untuk Gate G1.
- Protokol evaluasi final yang telah dibekukan (ukuran sampel, pembagian `DEV`/`H-G3`/`H-G4`, rumus denominator KPI).
- Paket bukti tersanitasi `E08` pada `evidence/<run_id>/C08/`: `auth-policy-tests`, `gateway-audit`, `sanitizer-report`, `orchestrator-capability-report`, dan `g1-record`.

## 7. Validation & Exit Criteria (Termasuk Spesifikasi Gate G1)
- **Exit Criteria Gate G1 (Foundation Gate):**
  1. Minimal 3 layanan terhubung (5 layanan sesuai `TBD-07`) berjalan dengan trafik ber-*seed* (`E03`) dan *telemetry capture* (*logs, RED metrics, distributed traces*, *service catalog*) terverifikasi (`AT-001`, `E05`).
  2. *Fault harness* dapat memicu dan mereset gangguan secara bersih sementara *ground truth* terisolasi penuh dari runtime investigator (`AT-002`, `AT-008` tahap fondasi, `E04`).
  3. Korpus KB sintetis memiliki dokumen `current`, `obsolete`, dan `restricted` dengan siklus hidup *ingestion* yang teruji serta baseline *Hybrid Retrieval* pada split `DEV` dapat direproduksi (`AT-006`, `AT-007`, `RAG-01`, `RAG-02`, `E06`, `E07`).
  4. *Authenticated gateway* aktif dan lulus uji penolakan *boundary* untuk `SEC-01`, `SEC-03` (*pre-sink*), `MCP-01`, `MCP-02`, dan `AT-005` (`E08`).
  5. Seluruh keputusan wajib Gate G1 (`TBD-05`, `TBD-06`, `TBD-08`, `TBD-10`, `TBD-11`, `ADR-S04` s/d `ADR-S08`) telah ditutup dan protokol evaluasi/KPI final telah dibekukan (`RULE-012`, `AT-014`).
- **Blocking Failures (Otomatis Menahan Gate G1 = `FAIL` / `BLOCKED`):**
  - Investigator memiliki jalur baca ke *ground truth* atau berhasil memanggil fungsi *write/restart/deploy/shell*.
  - *Synthetic PII/secret fixture* lolos dari *sanitizer* tanpa redaksi, atau kegagalan *sanitizer* bersifat *fail-open*.
  - Kueri di luar batas `query_window` diterima atau hanya dipotong diam-diam (*silently clamped*) alih-alih ditolak (`MCP-02`).
  - Ukuran sampel/ambang KPI atau pembagian `H-G3`/`H-G4` belum dibekukan.
- **Assessment Dependencies:** Kelulusan `SEC-01`, `MCP-01`, `MCP-02`, dan `AT-005` pada C08 merupakan pembuktian tingkat *gateway boundary*; pengujian terintegrasi dengan adapter backend nyata wajib diulang pada [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md), [C18](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md), dan [C21](../phase-4-pilot-hardening/21-FINAL-HOLDOUT-AND-BENCHMARK.md).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Memaksakan platform orkestrasi yang terlalu berat demi mengikuti nama vendor proposal meskipun melampaui plafon 8 GiB RAM (`RISK-06`, `RISK-07`); mitigasi dengan mematuhi hasil objektif `orchestrator-capability-report`.
- **Open Decisions:** Seluruh item `TBD-05`, `TBD-06`, `TBD-08`, `TBD-10`, `TBD-11`, dan `ADR-S04` s/d `ADR-S08` berstatus `TBD — Decision Required` hingga ditutup secara resmi pada rekaman `g1-record.md` di akhir chapter ini.
- **Handover ke [C09 — Read-Only Telemetry Adapters](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md) (Fase 2):** Gate G1 berstatus `PASS`, *Secure Gateway* yang siap dipasangi adapter telemetri nyata, kuota/batas waktu yang telah disahkan (`ADR-S05`), serta paket bukti `E08`.

