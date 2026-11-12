# E10 — Remediasi C10-VERIFY-001 dan C10-VERIFY-002

- **Run ID:** `c10-final-20261112T063556Z`; lab sintetis lokal; reviewer: `TBD`.
- **Status implementasi:** `IMPLEMENTED`; **`VERIFIED` belum dapat dinyatakan** karena exit criteria resource dan review masih terbuka. G2 tidak dievaluasi.
- **Versi:** SHA-256 kode dan tes dicatat dalam metadata JSON. Commit tidak tersedia karena direktori kerja bukan repository Git. Workflow/model/prompt/KB tidak digunakan.

## Hasil aktual

| Pemeriksaan | Status | Bukti |
|---|---|---|
| C10-VERIFY-001 — atomicity | `RESOLVED` untuk pengecualian korelasi yang diuji | [failure-atomicity.json](failure-atomicity.json): HTTP 503, FIFO dan registry kosong. Tes tambahan memeriksa create, merge, split, audit sink gagal dan dequeue/admission konkuren. Admission memakai lock dan korelasi sebelum commit. |
| C10-VERIFY-002 — lag signal | `RESOLVED` untuk replay terisolasi yang diuji | [sc08-live-replay.json](sc08-live-replay.json): fault auth dan notification aktif pada dua container lab milik run, pesan RabbitMQ sintetis tertahan, log `WARN_QUEUE_CONSUMER_LAG` muncul di Loki tanpa trace rekaan, dan dua alert menghasilkan dua incident terpisah. Evaluasi alert dan C10 dijalankan in-process, bukan webhook Prometheus otomatis. |
| SC-08 | `PASS` lingkup replay di atas | Dua alert aktual diterima; tidak digabung; fault milik run di-reset, pesan terkuras, dua antrean dan container milik run dibersihkan. Kegagalan run sebelumnya dipertahankan di [E10 terdahulu](../../c10-verify-20261112T053639Z/C10/readiness-check.md). |
| Regresi C08/C09/C10 | `PASS` | [pytest-output.txt](pytest-output.txt): 63 passed, 2 deprecation warnings. C08 10, C09 21, C10 30, lag 1 dan test notification C03 1. [Perintah dan exit code](pytest-result.json). |
| `OPS-01` | `PARTIAL` | [burst-resource-series.json](burst-resource-series.json): 100 POST bertanda tangan, 10 thread, 0,328 detik, satu incident, hit count 100, satu antrean. [queue-capacity.json](queue-capacity.json): 500 item, ke-501 ditolak, duplikat tetap merge. Pada [burst kedua](burst-compose-snapshot.json), satu snapshot Docker untuk 12 container menunjukkan [795,01 MiB](compose-resource-summary.json), di bawah 8 GiB lab; waktu tepat snapshot dan peak tidak tersedia. RSS high-water proses host 81.543.168 byte bukan RSS container. Plafon CPU/RAM C10 yang disahkan, uji end-to-end dan review resource masih diperlukan. |
| `AT-003` / `AT-016` | `PASS` lingkup C10 pada run sebelumnya | [Join](../../c10-verify-20261112T053639Z/C10/cross-signal-links.json) dan [graf](../../c10-verify-20261112T053639Z/C10/cascade-graph-check.json) berasal dari versi sebelum remediasi; regresi graf baru lulus, tetapi replay cascade end-to-end tidak diulang pada run ini. Metrik agregat ditautkan melalui waktu/service, bukan trace ID; kausalitas belum dibuktikan. |
| `AT-005` / `AT-008` | `PARTIAL` | Tes komponen lulus; zero-write dan isolasi ground truth end-to-end belum dibuktikan. |

## Keterbatasan dan keputusan terbuka

- `ADR-S05` belum mendokumentasikan plafon CPU/RAM burst C10 yang disahkan atau pembekuan correlation window; 8 GiB adalah batas Docker lab, bukan ukuran RSS proses host. Reviewer dan penerimaan hasil masih `TBD`.
- Audit dedup dieksekusi sebelum commit dan kegagalannya menahan admission; audit korelasi dapat terlanjur tercatat sebelum kegagalan lanjutan pada sink lain. Sink eksternal lintas komponen belum transaksional; korelasi berjalan di bawah lock dan callback tidak boleh memanggil kembali deduplicator.
- Korelasi tidak membuktikan sebab, dan nilai `VERIFIED` / handover C11 memerlukan penyelesaian exit criteria serta review berwenang. `IMPLEMENTED` tidak berarti G2 lulus.

## Pembersihan

Kedua fault SC-08 dihapus hanya berdasarkan ID milik run (`removed_faults=1` masing-masing). Antrean khusus terkuras, kedua antrean khusus dan kedua container milik run dihapus tanpa mereset layanan/volume lab yang sudah ada. Tidak ada pembacaan ground truth oleh investigator.
