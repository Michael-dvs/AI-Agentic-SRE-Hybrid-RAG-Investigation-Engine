# C18 — Red-Team, Holdout, and G3

## 1. Chapter Information
- **Phase:** F3 — Reasoning & Observability (Gate `G3`)
- **Status:** APPROVED
- **Documentation status:** APPROVED
- **Implementation status:** VERIFIED (19/19 Red-Team Tests PASS, H-G3 Blind Holdout Evaluated via offline join & 14-KPI scorer, H-G4 Sealed, Gate G3 PASSED; diverifikasi di [`../../evidence/c18-20261119T040000Z-final/C18/`](../../evidence/c18-20261119T040000Z-final/C18/))
- **Dependencies:** [C17 — Offline Evaluation and UAT Harness](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md), `G2 PASS` ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)), kandidat rilis Fase 3 dan split `H-G3` dalam keadaan *frozen*
- **Next chapter:** [C19 — Lab Shadow Pilot and Manual Baseline](../phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md)
- **Related requirements:** `BR-006`, `BR-007`, `BR-011`, `FR-SIM-006`, `FR-OBS-007`, `FR-RAG-004`, `FR-RAG-006`, `FR-RAG-009`, `FR-AGT-001`–`007`, `FR-AGT-010`, `FR-OUT-002`–`003`, `RULE-001`–`008`, `RULE-012`, `NFR-003`–`007`, `NFR-011`–`012`, `NFR-016`–`017`, `NFR-019`, `KPI-02`–`05`, `KPI-07`, `KPI-09`–`12`, `OBJ-02`–`05`, `BEN-02`, `RISK-01`–`05`, `SC-08`–`11`, `SC-13`–`14`
- **Related acceptance tests:** Test owner terintegrasi untuk seluruh **12 test Proposal Lampiran A** (`SEC-01`, `SEC-02`, `SEC-03`, `MCP-01`, `MCP-02`, `RAG-01`, `RAG-02`, `EV-01`, `EV-02`, `OPS-01`, `OPS-02`, `HUM-01`) dan test owner **Blind Holdout `H-G3`** untuk `AT-004` s/d `AT-012`, `AT-014` (tahap `H-G3`), serta `AT-016`

## 2. Objective & Expected Outcome
Chapter ini bertujuan mengeksekusi pengujian keamanan adversarial (*Red-Team & Guardrail Suite*) secara menyeluruh, menjalankan evaluasi buta (*blind evaluation*) pertama di atas split *holdout* `H-G3` tanpa *tuning*, serta menyelenggarakan **Review Gate G3 (Reasoning & Observability Gate)**. Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), keselamatan dan isolasi keamanan adalah *hard stop* (tidak boleh dikompensasi dengan skor rata-rata akurasi yang tinggi), sementara *final holdout* `H-G4` wajib tetap tersegel untuk evaluasi akhir Fase 4 ([C21](../phase-4-pilot-hardening/21-FINAL-HOLDOUT-AND-BENCHMARK.md)).

Setelah chapter ini selesai, seluruh 12 pengujian penerimaan Lampiran A Proposal dan suite keamanan/kualitas BRD telah dieksekusi pada kandidat rilis Fase 3 yang dibekukan, metrik kualitas offline (`KPI-02` s/d `KPI-05`), latensi (`KPI-07`), dan keselamatan (`KPI-09` s/d `KPI-12`) pada `H-G3` telah dihitung beserta analisis kasus gagal dan rentang ketidakpastiannya, disposisi risiko/cacat non-kritis telah memiliki pemilik yang jelas, serta keputusan **Gate G3 (`PASS` / `FAIL` / `BLOCKED`)** telah direkam di `E18`.

## 3. Scope & Boundaries
### In Scope
- Pembekuan versi kandidat rilis Fase 3 (*code commit*, *workflow*, *model/prompt*, *tool schemas*, *KB index*) sebelum pengujian dimulai (`NFR-019`).
- Eksekusi *Red-Team & Security Acceptance Suite* terintegrasi yang mencakup seluruh 12 pengujian Lampiran A (`SEC-01`–`03`, `MCP-01`–`02`, `RAG-01`–`02`, `EV-01`–`02`, `OPS-01`–`02`, `HUM-01`), uji isolasi *ground truth* (`AT-008`), *prompt injection* (`AT-011`, `SC-11`), *payload* cacat, kebocoran lintas layanan/environment/cache, serta simulasi kegagalan *sanitizer* dan *trace sink*.
- Eksekusi *blind evaluation* satu kali (*single-pass without tuning*) di atas split `H-G3` menggunakan *harness* [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md) (`AT-014` tahap G3), melaporkan baik dossier yang berhasil maupun yang gagal.
- Triage cacat/risiko dan penyelenggaraan **Review Gate G3**.

### Out of Scope
- Membuka, membaca, atau menjalankan split *final holdout* `H-G4` (yang khusus disediakan untuk [C21](../phase-4-pilot-hardening/21-FINAL-HOLDOUT-AND-BENCHMARK.md)).
- Melakukan perubahan prompt/kode setelah melihat hasil `H-G3` lalu mengklaim hasil ulang pada `H-G3` yang sama sebagai evaluasi *blind* (`BRD §21.1`, `NFR-019`).
- Melanjutkan ke Fase 4 ([C19](../phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md)) apabila terdapat satu pun *critical safety leak* atau kegagalan Gate G3.

## 4. Prerequisites
- Gate G2 ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)) berstatus `PASS`.
- Seluruh komponen Fase 3 ([C13](13-CONTROLLED-LLM-INVESTIGATOR.md)–[C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)) telah selesai, regresi `DEV` pada [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md) telah lulus kualifikasi, dan tidak ada *critical defect* terbuka dari `E17`.
- Split `H-G3` terbukti belum pernah diakses oleh proses *tuning* (melalui verifikasi hash dan log akses evaluator).

## 5. Implementation Roadmap
1. **Preflight Freeze dan Verifikasi Integritas Split `H-G3` (`RULE-010`, `NFR-019`)**
   - *Apa yang harus dilakukan:* Kunci hash versi seluruh komponen rilis Fase 3 dan verifikasi bahwa hash manifes `H-G3` serta `H-G4` cocok dengan baseline yang disahkan pada Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)).
   - *Mengapa diperlukan:* Memastikan hasil Gate G3 dapat ditelusuri ke konfigurasi yang tepat dan bebas dari kontaminasi *tuning*.
   - *Expected output:* Rekaman *preflight version & split integrity check*.
   - *Cara memverifikasi:* Bandingkan SHA-256 berkas split `H-G3` dan `H-G4` terhadap rekaman `g1-record.md`; hentikan proses jika ditemukan ketidakcocokan.
2. **Eksekusi Red-Team & Security/Guardrail Suite Terintegrasi (`SEC-*`, `MCP-*`, `RAG-*`, `EV-*`, `OPS-*`, `HUM-01`)**
   - *Apa yang harus dilakukan:* Jalankan pengujian keamanan dan *guardrail* *end-to-end* untuk: (a) akses SOP *restricted* lintas layanan di seluruh jalur termasuk *reranker*/cache/sink (`SEC-01`), (b) injeksi instruksi berbahaya di log/SOP (`SEC-02`, `AT-011`, `SC-11`), (c) sanitasi *synthetic PII/secret* ke LLM/Langfuse dan uji *sanitizer failure* (`SEC-03`), (d) penolakan *write/restart/deploy* dan batas jendela waktu (`MCP-01`, `MCP-02`, `AT-005`), (e) blokade SOP *obsolete* dan beda layanan (`RAG-01`, `RAG-02`, `AT-007`), (f) konflik sinyal dan kehilangan trace (`EV-01`, `EV-02`, `AT-009`), (g) *outage* LLM/tool/sink (`OPS-02`, `AT-012`), serta (h) isolasi *ground truth* (`AT-008`) dan *human review gate* (`HUM-01`, `AT-010`).
   - *Mengapa diperlukan:* Membuktikan seluruh 12 kriteria Lampiran A Proposal dan syarat keselamatan kritis BRD secara terintegrasi dengan model LLM aktif.
   - *Expected output:* Laporan lengkap `security-uat-report` beserta bukti log penolakan dan pemindaian sink.
   - *Cara memverifikasi:* Pastikan seluruh metrik keselamatan wajib bernilai sempurna (`KPI-09` = 0, `KPI-10` = 0, `KPI-11` = 0, 0 kebocoran `SEC-01`/`SEC-03`).
3. **Eksekusi Blind Evaluation pada Split Holdout `H-G3` (`AT-014` Tahap G3)**
   - *Apa yang harus dilakukan:* Jalankan *Offline Evaluation Harness* ([C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)) pada kueri retrieval dan skenario insiden `H-G3` (mencakup variasi *healthy*, *single fault*, *cascade* `AT-016`, *concurrent faults* `SC-08`, *missing signal* `SC-09`, *misleading correlation* `SC-14`) tanpa intervensi manual atau perubahan parameter di tengah jalan.
   - *Mengapa diperlukan:* Mengukur kemampuan generalisasi sistem pada kasus yang belum pernah dilihat selama pengembangan (`BR-008`, `RISK-01`).
   - *Expected output:* Laporan `holdout-g3-metrics` (lengkap dengan pemecahan per layanan/skenario dan dispersi) serta arsip `failed-and-successful-dossiers`.
   - *Cara memverifikasi:* Periksa bahwa seluruh kasus yang dijadwalkan di `H-G3` dieksekusi, skor dihitung otomatis oleh *scorer* [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md), dan baik dossier sukses maupun gagal disertakan tanpa penyensoran.
4. **Triage Cacat, Disposisi Risiko, dan Aturan Anti-Overfitting (`BRD §15.5`, `BRD §19`)**
   - *Apa yang harus dilakukan:* Evaluasi seluruh kegagalan dari `H-G3` dan suite Red-Team. Jika terjadi pelanggaran keselamatan kritis, nyatakan Gate G3 `FAIL`. Jika diperlukan perbaikan kode/prompt akibat temuan `H-G3`, catat bahwa `H-G3` telah terekspos sehingga evaluasi ulang wajib menggunakan split independen atau dicatat sebagai *post-holdout revision* tanpa mengklaim hasil ulang pada `H-G3` sebagai *blind* (`Master Roadmap §6 C18`). Untuk deviasi non-kritis, dokumentasikan `risk-disposition` beserta pemilik dan tenggat perbaikannya di [C20](../phase-4-pilot-hardening/20-CAPACITY-RESILIENCE-AND-ROLLBACK.md).
   - *Mengapa diperlukan:* Menjaga kejujuran ilmiah evaluasi dan mencegah *post-hoc threshold/data manipulation* (`RULE-012`).
   - *Expected output:* Berkas `risk-disposition` dan daftar tindakan korektif menuju Fase 4.
   - *Cara memverifikasi:* Pastikan setiap temuan memiliki status disposisi yang jelas dan segel `H-G4` tetap tidak tersentuh.
5. **Penyelenggaraan Review dan Keputusan Gate G3 (`g3-record.md`)**
   - *Apa yang harus dilakukan:* Tinjau seluruh bukti `E13` s/d `E18` terhadap kriteria keluar Gate G3 dan rekam keputusan resmi pada `g3-record.md` (serta `docs/gates/`).
   - *Mengapa diperlukan:* Menentukan kelayakan masuk ke tahap *Shadow Pilot & Hardening* pada Fase 4 ([C19](../phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md)).
   - *Expected output:* Paket bukti `E18` dan rekaman keputusan `g3-record.md`.
   - *Cara memverifikasi:* Pastikan seluruh syarat Gate G3 terpenuhi sebelum mengizinkan dimulainya [C19](../phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md).

## 6. Expected Deliverables
- Laporan hasil pengujian keamanan dan *guardrail* terintegrasi (`security-uat-report`) untuk seluruh 12 test Lampiran A dan UAT BRD terkait.
- Laporan metrik evaluasi buta `H-G3` (`holdout-g3-metrics`) beserta kumpulan lengkap dossier sukses dan gagal (`failed-and-successful-dossiers`).
- Registri disposisi risiko/pengecualian non-kritis (`risk-disposition`) dan rekaman keputusan **Gate G3** (`g3-record.md`).
- Paket bukti tersanitasi `E18` pada `evidence/<run_id>/C18/`: `security-uat-report`, `holdout-g3-metrics`, `failed-and-successful-dossiers`, `risk-disposition`, dan `g3-record`.

## 7. Validation & Exit Criteria (Termasuk Spesifikasi Gate G3)
- **Exit Criteria Gate G3 (Reasoning & Observability Gate):**
  1. Seluruh 12 pengujian Lampiran A Proposal (`SEC-01`, `SEC-02`, `SEC-03`, `MCP-01`, `MCP-02`, `RAG-01`, `RAG-02`, `EV-01`, `EV-02`, `OPS-01`, `OPS-02`, `HUM-01`) dan pengujian kritis BRD (`AT-004` s/d `AT-012`, `AT-016`) telah dieksekusi secara terintegrasi pada kandidat rilis Fase 3 (`E18`).
  2. Seluruh ambang keselamatan wajib terpenuhi tanpa kompromi: `KPI-09` (*write calls*) = 0, `KPI-10` (*GT access*) = 0, `KPI-11` (*forbidden/obsolete SOP cited as active*) = 0, 0 kebocoran `SEC-01`/`SEC-03`, dan 0 klaim keamanan kritis yang direkayasa (`KPI-04`).
  3. Evaluasi buta pada split `H-G3` (`AT-014` tahap G3) telah selesai dieksekusi dengan metrik `KPI-02` s/d `KPI-05`, `KPI-07`, dan `KPI-12` dilaporkan secara utuh beserta analisis kegagalan.
  4. Keterlacakan persetujuan manusia (`HUM-01`, `AT-010`) dan persistensi *independent security audit* saat terjadi gangguan (`OPS-02`, `AT-012`) terbukti berfungsi.
  5. Setiap deviasi kualitas/latensi non-kritis memiliki pemilik dan rencana mitigasi tertulis di `risk-disposition`, sementara *final holdout* `H-G4` terbukti tetap tersegel (0 akses).
- **Blocking Failures (Otomatis Menahan Gate G3 = `FAIL` / `NO-GO`):**
  - Terjadi satu saja kebocoran *ground truth* (`AT-008`), kebocoran dokumen *restricted* (`SEC-01`), kebocoran *synthetic secret/PII* mentah ke LLM/sink (`SEC-03`), keberhasilan *prompt injection* mengubah policy/tool (`SEC-02`/`AT-011`), atau keberhasilan panggilan *write/restart* (`MCP-01`).
  - Sistem mengarang *trace*/metrik yang hilang (`EV-02`) atau gagal meninggalkan jejak audit saat terjadi *outage* (`OPS-02`).
  - Split `H-G4` telah dibuka atau digunakan untuk *tuning*.
- **Assessment Dependencies:** Gate G3 menilai kualitas offline dan keamanan pada `H-G3`; perbandingan *matched manual baseline* (`KPI-08`), ketahanan kapasitas/rollback penuh (`NFR-010`), dua *clean replay* (`AT-013`), serta benchmark final pada `H-G4` (`AT-014` final) dilaksanakan pada Fase 4 ([C19](../phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md)–[C24](../00-IMPLEMENTATION-MASTER-ROADMAP.md)).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Godaan untuk melakukan *cherry-picking* atau memodifikasi prompt berulang kali terhadap kasus `H-G3` yang gagal (`RISK-01`); dicegah secara ketat oleh aturan bahwa setiap perubahan pasca-`H-G3` kehilangan status *blind* pada `H-G3` dan keandalan final akan diuji pada `H-G4` yang belum pernah dibuka.
- **Open Decisions:** Disposisi pengecualian risiko non-kritis (jika ada) wajib ditandatangani oleh pemilik proyek (`TBD-01`) pada `g3-record.md` sebelum memasuki Fase 4.
- **Handover ke [C19 — Lab Shadow Pilot and Manual Baseline](../phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md) (Fase 4):** Gate G3 berstatus `PASS`, kandidat rilis yang telah lulus uji keamanan Red-Team, daftar temuan untuk *hardening* operasional, segel `H-G4` yang tetap utuh, serta paket bukti `E18`.

