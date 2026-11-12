# C03 — Lab Services and Synthetic Traffic

## 1. Chapter Information
- **Phase:** F1 — Foundation
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** NOT_STARTED
- **Dependencies:** [C01 — Scope, Keputusan, dan G0](01-SCOPE-DECISIONS-AND-G0.md) (`G0 PASS`), [C02 — Architecture, Contracts, and Evaluation Design](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), penutupan `ADR-S01` (pilihan bahasa/runtime layanan simulasi)
- **Next chapter:** [C04 — Fault Harness and Ground Truth Isolation](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)
- **Related requirements:** `BR-001`, `BR-010`, `FR-SIM-001`, `FR-SIM-002`, `FR-SIM-003`, `FR-OBS-001` (propagasi ID aplikasi), `FR-OBS-003` (propagasi trace context), `RULE-001`, `RULE-009`, `NFR-001`, `NFR-002`, `NFR-014`, `NFR-015`, `NFR-017`, `DEP-01`, `RISK-06`, `RISK-07`, `SC-01`, `UC-01`
- **Related acceptance tests:** `AT-001` (build owner bagian topologi layanan dan rantai request; verifikasi penuh bersama trace backend di C05), `AT-013` (build owner bagian *reproducible startup/shutdown*; verifikasi final dua *clean replay* di C22)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun ekosistem mikroservis sintetis yang berjalan mandiri di atas Docker Compose lokal (`macOS arm64`) beserta generator trafik ber-*seed* yang dapat diulang (*reproducible*). Mengacu pada baseline [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) dan keputusan `TBD-07` pada Gate G0, maket mencakup 5 layanan ringan yang saling terhubung (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, dan `db-dummy`) sehingga satu permintaan *end-to-end* melintasi minimal 2 ketergantungan (*dependencies*) sesuai `FR-SIM-001`.

Setelah chapter ini diimplementasikan, operator lab memiliki lingkungan layanan yang dapat dinyalakan atau dimatikan dengan satu perintah terdokumentasi (`NFR-002`), menghasilkan respons sehat pada baseline normal (`SC-01`/`UC-01`), mempublikasikan atribut identitas standar (`service.name`, `environment`, `service.version`, `trace_id`, `correlation_id`) sesuai kontrak [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), serta menjaga konsumsi CPU, RAM, dan disk di bawah plafon alokasi lab (`TBD-03`: maks 4–6 CPU, 8 GiB RAM, 15 GiB Disk).

## 3. Scope & Boundaries
### In Scope
- Pembuatan *containerized dummy microservices* (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) di jaringan Docker lokal terisolasi tanpa koneksi ke sistem eksternal/bank (`NFR-001`).
- Implementasi rantai komunikasi sinkron/asinkron antarlokasi layanan dengan propagasi konteks `trace_id` dan `correlation_id` yang dibangkitkan aplikasi (`FR-SIM-001`, `FR-OBS-001`).
- Penyediaan *synthetic traffic generator* yang mendukung profil beban normal dan *spike* berbasis parameter `seed` deterministik (`FR-SIM-003`).
- Penyusunan manifes Docker Compose, pemeriksaan `/healthz` dan `/readyz`, pembatasan *resource limits* per kontainer, serta skrip *start/stop/cleanup* lokal (`NFR-002`, `NFR-015`).

### Out of Scope
- Mekanisme injeksi gangguan (*fault injection*) dan registri *ground truth* (dibangun di [C04](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)).
- Kolektor dan backend penyimpanan *metrics*, *logs*, serta *distributed traces* (dibangun di [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md)).
- Penyimpanan kredensial nyata, PII asli, atau berkas `.env` berisiko di dalam repositori/folder sinkronisasi cloud (`NFR-017`, `TBD-13`).
- Klaim bahwa `AT-001` telah lulus penuh sebelum *trace backend* diverifikasi pada [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md).

## 4. Prerequisites
- Gate G0 berstatus `PASS` dengan alokasi kapasitas lab (`TBD-03`) dan topologi 5 layanan ringan (`TBD-07`) yang telah disahkan.
- Kontrak skema layanan, konvensi identitas (`service.name`, `environment`, `build_version`), serta format propagasi *trace/correlation ID* dari [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) tersedia.
- Keputusan `ADR-S01` mengenai bahasa pemrograman dan *framework* layanan ringan (mis. Python FastAPI atau Go/Node berlisensi *open-source* sesuai `TBD-12`) telah ditutup sebelum penulisan kode dimulai; jika belum, berstatus `TBD — Decision Required`.
- Docker Engine / Docker Compose tersedia pada mesin pengembangan `macOS arm64` lokal.

## 5. Implementation Roadmap
1. **Penyiapan Struktur Direktori Layanan dan Manifes Docker Compose Terisolasi**
   - *Apa yang harus dilakukan:* Buat struktur direktori layanan simulasi, definisikan jaringan internal Docker Compose tanpa *port exposure* yang tidak perlu, tetapkan *memory/CPU limit* per kontainer agar total stack di bawah 8 GiB RAM, dan sediakan `.env.example` berisi konfigurasi sintetis non-rahasia.
   - *Mengapa diperlukan:* Mencegah *resource exhaustion* pada host 16 GiB RAM (`RISK-07`) dan menjamin isolasi jaringan lab (`NFR-001`, `RULE-009`).
   - *Expected output:* Berkas manifes deployment lab dan `.env.example` berversi dengan *pinned image tags*.
   - *Cara memverifikasi:* Validasi sintaks konfigurasi Compose dan pastikan tidak ada rahasia atau endpoint eksternal di seluruh manifes.
2. **Implementasi Layanan Inti dan Rantai Ketergantungan (`FR-SIM-001`)**
   - *Apa yang harus dilakukan:* Bangun 5 layanan dummy (`api-gateway` $\rightarrow$ `auth-service` & `transaction-service` $\rightarrow$ `db-dummy` & `notification-service`) dengan *endpoint* bisnis sintetis serta *endpoint* kesiapan `/healthz` dan `/readyz`.
   - *Mengapa diperlukan:* Membuktikan rantai panggilan melewati $\ge 2$ ketergantungan nyata untuk mendukung skenario propagasi kegagalan hulu-hilir.
   - *Expected output:* Kode layanan simulasi dan dokumentasi kontrak API lokal yang sesuai spesifikasi [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md).
   - *Cara memverifikasi:* Eksekusi permintaan uji melalui `api-gateway` dan pastikan respons berhasil merangkum interaksi lintas layanan.
3. **Instrumentasi Identitas Layanan dan Propagasi Trace/Correlation ID (`FR-SIM-002`)**
   - *Apa yang harus dilakukan:* Tambahkan *middleware* pada setiap layanan untuk menyematkan `service.name`, `environment`, `service.version`, `instance_id`, `trace_id` (W3C Trace Context), dan `correlation_id` pada setiap *structured log* (ke `stdout`) dan *header* keluar.
   - *Mengapa diperlukan:* Memastikan korelasi sinyal lintas layanan dibuat oleh aplikasi sejak awal, bukan dikarang oleh LLM (`BRD §13.3`).
   - *Expected output:* Output log JSON terstruktur dan *response header* yang memuat identitas korelasi konsisten di semua 5 layanan.
   - *Cara memverifikasi:* Periksa bahwa satu permintaan ke `api-gateway` menghasilkan `trace_id` dan `correlation_id` yang identik pada log kelima layanan.
4. **Pembuatan Synthetic Traffic Generator Berbasis Seed (`FR-SIM-003`)**
   - *Apa yang harus dilakukan:* Bangun modul/kontainer generator trafik yang menerima parameter `seed`, `profile` (`normal` atau `spike`), `rate`, dan `duration`, serta mencatat manifes eksekusi.
   - *Mengapa diperlukan:* Menjamin beban kerja dapat direproduksi secara deterministik (`NFR-002`) untuk pengujian baseline dan *replay* insiden.
   - *Expected output:* Skrip/kontainer traffic generator beserta profil konfigurasi `normal` dan `spike`.
   - *Cara memverifikasi:* Jalankan dua sesi singkat dengan `seed` yang sama dan pastikan distribusi tipe permintaan yang dibangkitkan konsisten.
5. **Penyusunan Prosedur Start/Stop Satu Perintah dan Eksekusi Smoke Baseline (`SC-01`)**
   - *Apa yang harus dilakukan:* Buat skrip otomasi *startup*, pemeriksaan kesiapan seluruh kontainer, eksekusi beban sehat (`SC-01`), pengukuran pemakaian CPU/RAM kontainer, serta *clean shutdown*.
   - *Mengapa diperlukan:* Memenuhi syarat reproduktifitas `NFR-002` dan membuktikan bahwa trafik sehat tidak memicu *false error* (`UC-01`).
   - *Expected output:* Skrip operasional start/stop dan paket bukti `E03` (`stack-manifest`, `service-contracts`, `healthy-request`, `traffic-seed-and-profile`, `resource-profile`).
   - *Cara memverifikasi:* Jalankan siklus *start $\rightarrow$ health check $\rightarrow$ normal traffic $\rightarrow$ stop* dan pastikan lingkungan bersih kembali setelah dihentikan.

## 6. Expected Deliverables
- Manifes Docker Compose lokal dengan batas sumber daya (*resource limits*) dan `.env.example` non-rahasia.
- Implementasi 5 layanan simulasi (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) beserta kontrak API-nya.
- Generator trafik sintetis mendukung mode `normal` dan `spike` dengan `seed` tercatat.
- Paket bukti tersanitasi `E03` pada `evidence/<run_id>/C03/`: `stack-manifest`, `service-contracts`, `healthy-request`, `traffic-seed-and-profile`, dan `resource-profile`.

## 7. Validation & Exit Criteria
- Seluruh 5 layanan menyala dari kondisi bersih, melaporkan status sehat pada `/healthz` dan `/readyz`, serta berhasil memproses rantai permintaan melewati $\ge 2$ ketergantungan (`AT-001` bagian topologi/request; status `AT-001` keseluruhan tetap `PARTIAL / NOT_RUN` hingga *trace backend* selesai di [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md)).
- Setiap log dan respons layanan memuat `service.name`, `environment`, `service.version`, `trace_id`, dan `correlation_id` yang valid sesuai skema [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) (`FR-SIM-002`).
- Beban normal (`SC-01`, `UC-01`) berjalan stabil dengan *error rate* 0% dan pemakaian memori kontainer berada jauh di dalam anggaran 8 GiB RAM (`TBD-03`).
- Siklus *stop/cleanup* mengembalikan *state* kontainer ke kondisi bersih (`AT-013` prasyarat komponen).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Pemakaian memori gabungan kontainer melebihi anggaran apabila *runtime* atau *worker* dikonfigurasi terlalu besar (`RISK-07`); mitigasi dengan *single-worker container* dan *explicit memory limits*.
- **Open Decisions:** `ADR-S01` (pilihan bahasa/framework layanan simulasi dan *pinned base image*) harus berstatus `APPROVED` sebelum implementasi C03 dimulai (`TBD — Decision Required` hingga C02 disahkan).
- **Handover ke [C04](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md):** Topologi 5 layanan yang berjalan stabil, *endpoint* internal untuk pengaitan *fault hooks* (khusus identitas harness), profil trafik ber-*seed*, serta paket bukti `E03`.

