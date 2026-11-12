# E10 — Verifikasi lanjutan C10

- **Run ID:** `c10-verify-20261112T053639Z`; waktu mulai dan hash file: metadata JSON setiap hasil.
- **Mode:** verifikasi lab sintetis; tidak ada perubahan kode. Reviewer: `TBD`.
- **Status implementasi:** `IN_PROGRESS`; **tidak memenuhi `VERIFIED`**. `G2` tidak dievaluasi.
- **Versi:** hash SHA-256 kode dan tes dicatat pada JSON; commit tidak tersedia karena direktori ini bukan repository Git. Workflow/model/prompt/KB tidak dipakai; seed untuk replay cascade `20261112`.

## Hasil

| Pemeriksaan | Hasil | Bukti dan batas |
|---|---|---|
| Regresi C08, C09, C10 | `PASS` | [pytest-output.txt](pytest-output.txt): 53 passed (10 C08, 21 C09, 22 C10), dua deprecation warnings; [perintah dan exit code](pytest-result.json). |
| `AT-003` | `PASS` **lingkup replay C10** | [Replay](cascade-replay.json) memuat fault sintetis aktual, log, span, metrik, alert dan incident; [join](cross-signal-links.json) mengaitkan ketiga layanan berdasarkan service, correlation/trace ID dan waktu. Metrik RED bersifat agregat, tidak memiliki trace ID, dan referensi URL alert tidak didereferensi; korelasi bukan bukti kausalitas. UAT lintas chapter tetap perlu diulang. |
| `AT-016` | `PASS` **lingkup korelasi C10** | [Replay](cascade-replay.json) dan [pemeriksaan graf](cascade-graph-check.json): jalur gateway → transaksi → ledger, kandidat ledger, status `INCONCLUSIVE` dan edge `stale` tercatat. Ini bukan klaim root cause terbukti; validasi C14 dan acceptance lanjutan tetap diperlukan. |
| `OPS-01` | `PARTIAL` | [Burst konkuren](concurrent-burst.json): 100 POST, 10 thread, 0,291 detik; satu incident, 99 merge, satu item antrean. [Kapasitas](queue-capacity.json): 500 fingerprint diterima; ke-501 ditolak, duplikat tetap merge. RSS puncak proses uji macOS 82.395.136 byte, bukan total Docker; plafon CPU/RAM C10 disahkan belum ditemukan. Uji end-to-end dan review resource masih diperlukan. |
| Failure atomicity intake | `FAIL` | [failure-atomicity.json](failure-atomicity.json): kegagalan `correlate_incidents` menghasilkan HTTP `503` tetapi incident tetap berada dalam antrean. Kegagalan audit sink yang diuji menolak tanpa item antrean. Ini tes in-process dengan fault dependency terkontrol. |
| `SC-08` | `FAIL` pada replay lab terdahulu; tes komponen `PASS` | [Replay terdahulu](../../c10-concurrent-20261112T051109Z/C10/concurrent-live-replay.json) tidak menghasilkan alert notification; tes komponen split lulus dalam pytest. Tidak mengulang replay gagal tanpa perubahan kode. |
| `AT-005`, `AT-008` | `PARTIAL` | Tes komponen menolak field terlarang dan memantau socket/path; tidak membuktikan zero-write atau isolasi GT end-to-end. |

## Defect dan blocker

1. **C10-VERIFY-001 — failure atomicity:** `services/alert_intake/intake.py` memanggil `deduplicator.process` sebelum `correlate_incidents`; pengecualian korelasi diterjemahkan ke `503` setelah incident sudah masuk antrean. Pemanggil dapat menganggap request gagal sementara worker tetap menerima incident. Perbaiki admission secara atomik dan tambah regression test consumer-visible sebelum verifikasi ulang.
2. **C10-VERIFY-002 — SC-08 telemetry:** worker notification berhenti mengambil pesan selama lag aktif; aturan alert lag bergantung pada log yang dihasilkan saat `process_event`. Korelasi dua alert independen belum terbukti pada replay nyata. Analisis ini kandidat penyebab, bukan bukti kausal eksklusif. Selesaikan jalur sinyal lab dan ulangi replay dengan cleanup terbatas.
3. **Resource/audit:** plafond CPU/RAM burst yang disahkan dan review sink audit belum tercatat. RSS pada run ini hanya high-water proses host, bukan pengukuran isolasi container atau total lab. TTL 60 detik dikonfirmasi G1; correlation window 60 detik merupakan pilihan lab pengguna, bukan parameter ADR-S05 yang telah dibekukan.

## Keamanan replay dan langkah berikut

Fault cascade menyasar `ledger-service` sintetis dan di-reset memakai **fault ID milik run saja**; respons cleanup `200`, `removed_faults=1`. Tidak memanggil reset menyeluruh dan tidak membaca registry ground truth. Perbaiki dua defect, ukur resource sesuai plafon yang disetujui, jalankan ulang pemeriksaan gagal dan minta reviewer menilai bukti sebelum status `VERIFIED` atau handover C11.
