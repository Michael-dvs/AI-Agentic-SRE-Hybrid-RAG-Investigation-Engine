# C11 — Durable Investigation Workflow

## 1. Chapter Information
- **Phase:** F2 — Controlled Integration
- **Status:** IMPLEMENTED
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** IMPLEMENTED
- **Dependencies:** [C07 — Hybrid Retrieval and Baselines](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md), [C08 — Secure Gateway and Foundation G1](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) (`G1 PASS`, penutupan `TBD-05` & `ADR-S05`), [C09 — Read-Only Telemetry Adapters](09-READ-ONLY-TELEMETRY-ADAPTERS.md), [C10 — Alert Intake and Dependency Correlation](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md)
- **Next chapter:** [C12 — Baseline Dossier and End-to-End G2](12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)
- **Related requirements:** `BR-004`, `BR-007`, `FR-OBS-005`, `FR-OBS-007`, `FR-RAG-009`, `FR-AGT-001`, `FR-AGT-003`, `FR-AGT-004`, `FR-AGT-006` (pemeriksaan dasar skema/provenansi), `FR-AGT-007`, `FR-AGT-008`, `FR-AGT-009`, `RULE-003`, `RULE-004`, `NFR-005`, `NFR-006`, `NFR-007` (fondasi *deadline*), `NFR-014`, `RISK-08`
- **Related acceptance tests:** `AT-004` (build & test owner urutan *state transitions*; diulang di C12/C18/C21), `AT-012` (build & test owner jalur *tool/RAG outage & worker restart*; jalur *LLM outage* diselesaikan di C13), `MCP-01` & `MCP-02` (regresi tingkat *workflow*), `EV-01` & `EV-02` (build owner penanganan baseline deterministik), `OPS-01` (build owner kuota & idempotensi eksekusi workflow), `OPS-02` (build owner kerangka *fallback*; belum diklaim lulus penuh sebelum model nyata di C13)
- **Evidence bundle:** `evidence/c11-20261112T072000Z/C11/` (`state-transitions.json`, `workflow-manifest.json`, `cancel-retry-restart-proof.json`, `budget-circuit-dlq-events.json`, `readiness-check.md`)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *Durable Deterministic Investigation Workflow* yang mengatur siklus hidup investigasi secara eksplisit melalui kode dan kebijakan deterministik, bukan melalui kebebasan prompt LLM (`AGENTS.md §6.3`). Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) §2.2, pada Fase 2 (`C11`–`C12`), tahap penyusunan hipotesis dan validasi menggunakan **baseline aturan deterministik fungsional** yang membaca bukti aktual dari adapter [C09](09-READ-ONLY-TELEMETRY-ADAPTERS.md) dan *Hybrid RAG* [C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md)—bukan *mock LLM*, bukan teks *hardcoded* per skenario, dan wajib memilih *abstain* (`INCONCLUSIVE`) apabila bukti tidak memadai.

Setelah chapter ini selesai, setiap insiden dari [C10](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md) bergerak secara terlacak melewati urutan *state* wajib (`RECEIVED` $\rightarrow$ `CORRELATED` $\rightarrow$ `TRIAGED` $\rightarrow$ `EVIDENCE_COLLECTED` $\rightarrow$ `RETRIEVED` $\rightarrow$ `HYPOTHESES` $\rightarrow$ `VALIDATED` $\rightarrow$ `DRAFTED` $\rightarrow$ `HUMAN_REVIEW` $\rightarrow$ `CLOSED`/`LEARNED`), dilengkapi penyimpanan *state* persisten, batas *global deadline* dan kuota panggilan (`ADR-S05`), *retry* terbatas dengan *exponential backoff + jitter*, *circuit breaker*, *kill switch/cancellation*, serta pemulihan idempoten saat *worker* direstart di tengah eksekusi (`FR-AGT-001`, `FR-AGT-009`).

## 3. Scope & Boundaries
### In Scope
- Implementasi *state machine* persisten dengan urutan transisi wajib `FR-AGT-001` serta status terminal kegagalan/pembatalan yang terekspos di log audit (`FAILED_SAFE_FALLBACK`, `CANCELLED`).
- Orkestrasi pemanggilan terbatas (*bounded calls*) ke adapter telemetri [C09](09-READ-ONLY-TELEMETRY-ADAPTERS.md) dan *Hybrid RAG* [C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md) sesuai *service scope* dan *dependency impact graph* [C10](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md).
- Implementasi **baseline evaluator/investigator deterministik berbasis aturan** untuk menghasilkan kandidat hipotesis dari sinyal aktual, memeriksa provenansi dasar, dan menetapkan status `SUPPORTED`, `PARTIAL`, atau `INCONCLUSIVE` sebelum LLM diaktifkan di [C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md).
- Penegakan *global deadline*, *tool-call/token budget readiness*, *capped retries* dengan *backoff + jitter*, *circuit breaker*, *Dead Letter Queue* (DLQ), *cancellation*, dan *kill switch* (`FR-AGT-004`, `FR-AGT-009`, `ADR-S05`).
- Pencatatan *version identifier* (`workflow_version`, `tool_schema_version`, `kb_version`, `policy_version`) pada setiap eksekusi (`FR-AGT-008`).

### Out of Scope
- Pemanggilan LLM eksternal/lokal untuk penalaran bebas (dibangun di [C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md); jangan mengklaim `OPS-02` telah lulus penuh pada C11).
- Pembuatan antarmuka review manusia dan perenderan akhir berkas dossier JSON/Markdown (diselesaikan di [C12](12-BASELINE-DOSSIER-AND-END-TO-END-G2.md) dan [C16](../phase-3-reasoning-observability/16-HUMAN-REVIEW-AND-HANDOVER.md)).
- Pembacaan label `scenario_id` atau pembuatan jawaban *canned/hardcoded* per nama skenario (`RULE-002`).

## 4. Prerequisites
- Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)) berstatus `PASS`, serta keputusan pemilihan *workflow coordinator/state store* (`TBD-05`, `ADR-S01`) dan kuota/batas waktu (`ADR-S05`) telah disahkan.
- Layanan *Hybrid Retrieval* ([C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md)), *Secure Gateway* ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)), *Read-Only Telemetry Adapters* ([C09](09-READ-ONLY-TELEMETRY-ADAPTERS.md)), dan *Alert Intake & Correlation* ([C10](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md)) telah berfungsi.
- Kontrak transisi *workflow state* dan *idempotency key* dari [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) tersedia.

## 5. Implementation Roadmap
1. **Implementasi State Machine Persisten dan Version Manifest (`FR-AGT-001`, `FR-AGT-008`)**
   - *Apa yang harus dilakukan:* Bangun mesin *workflow* menggunakan platform/koordinator terpilih (`TBD-05`) dengan penyimpanan *state* *durable* yang mencatat setiap transisi (`RECEIVED` $\rightarrow$ `CORRELATED` $\rightarrow$ `TRIAGED` $\rightarrow$ `EVIDENCE_COLLECTED` $\rightarrow$ `RETRIEVED` $\rightarrow$ `HYPOTHESES` $\rightarrow$ `VALIDATED` $\rightarrow$ `DRAFTED` $\rightarrow$ `HUMAN_REVIEW` $\rightarrow$ `CLOSED`/`LEARNED`), lengkap dengan *timestamp* UTC, *input/output hash*, dan *version manifest*.
   - *Mengapa diperlukan:* Menjamin setiap langkah investigasi dapat diaudit dan dilanjutkan kembali tanpa kehilangan jejak (`NFR-005`).
   - *Expected output:* Mesin *stateful workflow* dan penulis `state-transitions` serta `workflow-manifest`.
   - *Cara memverifikasi:* Jalankan satu insiden uji dan periksa bahwa seluruh transisi *state* terekam secara berurutan tanpa ada *state* wajib yang dilompati (`AT-004`).
2. **Integrasi Pengumpulan Bukti Terbatas dan Retrieval Berizin (`EVIDENCE_COLLECTED` & `RETRIEVED`)**
   - *Apa yang harus dilakukan:* Pada tahap `TRIAGED` $\rightarrow$ `EVIDENCE_COLLECTED`, panggil adapter [C09](09-READ-ONLY-TELEMETRY-ADAPTERS.md) melalui gateway [C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) hanya untuk layanan di dalam *incident scope* dan *dependency impact graph* [C10](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md); pada tahap `RETRIEVED`, ambil konteks SOP aktif melalui [C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md) menggunakan gejala dan kode error yang ditemukan.
   - *Mengapa diperlukan:* Membatasi ruang lingkup kueri secara deterministik dan memastikan kegagalan sumber (`SOURCE_UNAVAILABLE` atau `no_applicable_runbook`) diteruskan sebagai fakta ke tahap berikutnya (`FR-OBS-007`, `FR-RAG-009`).
   - *Expected output:* Pengumpul bukti otomatis yang menghasilkan *sanitized evidence bundle* per insiden.
   - *Cara memverifikasi:* Periksa log gateway untuk memastikan seluruh panggilan *tool* mematuhi *service allowlist* insiden dan kuota maksimum per insiden (`ADR-S05`).
3. **Implementasi Baseline Hipotesis dan Validasi Deterministik (`HYPOTHESES` & `VALIDATED`)**
   - *Apa yang harus dilakukan:* Bangun logika berbasis aturan deterministik yang mengevaluasi *evidence bundle* aktual (lonjakan 5xx, latensi span hulu-hilir, antrean lag, atau konflik metrik vs log) untuk menyusun hipotesis berperingkat beserta bukti pendukung/penyangkal, memvalidasi keterikatan `evidence_id` dan waktu, serta menurunkan status ke `PARTIAL` atau `INCONCLUSIVE` saat bukti hilang/bertentangan (`EV-01`, `EV-02`).
   - *Mengapa diperlukan:* Membuktikan *plumbing* investigasi *end-to-end* untuk Gate G2 secara jujur tanpa *placeholder* kosong atau jawaban *hardcoded*, sekaligus menjadi *fallback engine* nyata ketika LLM mengalami *outage* di Fase 3 (`FR-AGT-007`).
   - *Expected output:* Modul *deterministic rule-based investigator & provenance checker*.
   - *Cara memverifikasi:* Uji dengan bukti sehat (`SC-01`), bukti gangguan (`SC-02`, `SC-03`), dan bukti kehilangan trace (`SC-09`); pastikan output hipotesis berubah murni berdasarkan bukti observasi aktual.
4. **Penegakan Global Deadline, Budget, Circuit Breaker, Cancellation, dan Kill Switch (`FR-AGT-004`, `FR-AGT-009`)**
   - *Apa yang harus dilakukan:* Terapkan batas waktu total per insiden (*global deadline*), penghitung kuota panggilan *tool* (dan *hook* kuota token untuk [C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md)), *retry* terbatas dengan *backoff + jitter* hanya untuk error transien, *circuit breaker* saat backend gagal beruntun, DLQ untuk insiden yang tidak dapat diproses, serta mekanisme *cancel/kill switch* yang segera menghentikan kueri baru.
   - *Mengapa diperlukan:* Mencegah *runaway loop* dan menjamin perilaku gagal yang aman (`NFR-006`, `RISK-08`).
   - *Expected output:* Komponen pengawas kuota/waktu dan rekaman `budget-circuit-dlq-events`.
   - *Cara memverifikasi:* Paksa satu adapter mengalami *timeout* berulang dan kirim sinyal `cancel` di tengah eksekusi; pastikan *circuit breaker* terbuka, tidak ada panggilan *tool* baru setelah `cancel`, dan status akhir tercatat di audit.
5. **Pengujian Restart Worker, Idempotent Replay, dan Outage Backend (`AT-004`, `AT-012`)**
   - *Apa yang harus dilakukan:* Hentikan/restart kontainer *worker* saat insiden berada di tengah tahap `EVIDENCE_COLLECTED`, kirim ulang *event* dengan *idempotency key* yang sama, serta uji pemutusan koneksi ke backend *tool* dan RAG; simpan seluruh bukti ke `E11`.
   - *Mengapa diperlukan:* Membuktikan ketahanan *durable state* dan ketiadaan duplikasi investigasi (`FR-AGT-009`, `AT-012` jalur non-LLM).
   - *Expected output:* Paket bukti `E11` (`state-transitions`, `workflow-manifest`, `cancel-retry-restart-proof`, `budget-circuit-dlq-events`).
   - *Cara memverifikasi:* Pastikan pasca-restart, *workflow* melanjutkan dari *checkpoint* terakhir tanpa menggandakan hasil dan menghasilkan satu jejak status yang konsisten.

## 6. Expected Deliverables
- Mesin *Durable Deterministic Investigation Workflow* yang mengeksekusi seluruh *state* wajib `FR-AGT-001` dengan *version manifest* (`FR-AGT-008`).
- Modul *deterministic baseline investigator* dan *provenance checker* yang bekerja di atas bukti aktual (sekaligus berfungsi sebagai *fallback* saat LLM *outage* nanti).
- Pengendali *global deadline*, kuota panggilan, *capped retry/backoff*, *circuit breaker*, DLQ, dan *cancellation/kill switch*.
- Paket bukti tersanitasi `E11` pada `evidence/<run_id>/C11/`: `state-transitions`, `workflow-manifest`, `cancel-retry-restart-proof`, dan `budget-circuit-dlq-events`.

## 7. Validation & Exit Criteria
- `AT-004`: Seluruh *state* wajib (`RECEIVED` s/d `HUMAN_REVIEW`) terekam secara berurutan dengan *timestamp* valid untuk setiap insiden yang diproses.
- `AT-012` (jalur *tool/RAG outage* & *worker restart*) & `FR-AGT-009`: Pemutusan backend *tool*/RAG atau *restart worker* di tengah eksekusi menghasilkan *safe fallback* / pemulihan *checkpoint* yang tercatat di audit tanpa *crash* gelap atau duplikasi eksekusi.
- `MCP-01` & `MCP-02` (regresi *workflow*): Orkestrator hanya memanggil *tool* melalui gateway [C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) dan mematuhi batas kuota per insiden.
- Tidak ada *state* yang berisi *stub* kosong atau membaca label `scenario_id` dari *ground truth*.

## 8. Risks, Open Decisions & Handover
- **Risiko:** *Retry* otomatis pada saat backend mengalami *degradation* dapat memperparah antrean jika tidak dibatasi oleh *global deadline* dan *circuit breaker*; mitigasi dengan membatasi jumlah *retry* maksimum (mis. maks 2 kali untuk error transien) sesuai `ADR-S05`.
- **Open Decisions:** Konfigurasi mesin *workflow* (`TBD-05`) dan batas kuota/timeout (`ADR-S05`) menggunakan keputusan yang telah disahkan pada Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)).
- **Handover ke [C12](12-BASELINE-DOSSIER-AND-END-TO-END-G2.md):** Output *state* `VALIDATED`/`DRAFTED` yang berisi bukti terkumpul, sitasi SOP, hipotesis baseline deterministik, penanda *unknowns*, serta paket bukti `E11` untuk dirakit menjadi dossier dan diuji pada **Gate G2**.

