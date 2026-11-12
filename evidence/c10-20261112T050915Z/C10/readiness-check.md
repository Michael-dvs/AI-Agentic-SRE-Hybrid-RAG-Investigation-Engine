# C10 — Pemeriksaan Kesiapan

- **Run:** `c10-20261112T050915Z`; lingkungan: proses lokal, data sintetis; reviewer: `TBD`.
- **Status chapter:** `IN_PROGRESS`, **bukan `VERIFIED`**. G2 tidak dinilai.
- **Versi:** SHA-256 file tersedia pada metadata JSON; commit tidak tersedia karena direktori ini bukan repository Git. Workflow, model, prompt, dan KB tidak dipakai pada uji komponen ini.
- **Regresi:** `pytest tests/test_c08_secure_gateway.py tests/test_c09_telemetry_adapters.py tests/test_c10_alert_intake_correlation.py -v` → **53 passed**, dua peringatan deprecation. C08: 10; C09: 21 termasuk regresi metrik kosong; C10: 22.
- **Webhook:** signature salah `401`; payload cacat `400`; alert bertanda tangan diterima. Lihat `intake-validation.json`.
- **OPS-01 — PARTIAL:** 100 POST duplikat berurutan dalam 0,265 detik menghasilkan satu incident ID, `hit_count=100`, satu antrean. `burst-resource-series.json` berisi `tracemalloc` dan CPU proses, bukan RSS kontainer atau bukti batas sumber daya yang disahkan. Uji burst terintegrasi dan concurrency masih diperlukan.
- **AT-016 — PARTIAL:** tes in-process memakai alert dan trace ID sintetis serta graf katalog deklaratif; edge tanpa observasi ditandai stale dan hasil `INCONCLUSIVE`. Replay latency nyata di bawah belum membuktikan graf dampak atau skenario dependency-unavailable secara menyeluruh.
- **AT-003 — PARTIAL:** [replay lab terarah](../../c10-live-20261112T050738Z/C10/targeted-live-replay.json), dijalankan sebelum perubahan terakhir normalisasi triase, menginjeksi latency ledger; tiga transaksi menghasilkan 30 log, 18 span dengan trace ID yang sama, 15 metrik agregat dan tiga alert yang diterima dengan incident ID. Bukti belum memuat join rinci setiap titik metrik dan source reference ke incident; acceptance penuh belum dinyatakan lulus.
- **AT-005 / AT-008 — PARTIAL:** uji komponen memblokir koneksi socket pada jalur request dan memantau pembukaan path restricted; bukan pembuktian isolasi atau zero-write end-to-end.
- **SC-08 — FAIL pada replay lab:** input sintetis in-process terpisah, tetapi dua replay fault konkuren tidak menghasilkan alert notification yang dapat dikorelasikan. Pada [replay enam detik](../../c10-concurrent-20261112T051109Z/C10/concurrent-live-replay.json), alert terpilih hanya `api-gateway`/`auth-service`; kedua fault dibersihkan berdasarkan ID milik run. Kasus acceptance dua alert independen belum lulus.
  - Temuan sumber: `services/notification_service/app.py:359–369` menghentikan pengambilan pesan saat lag aktif; log `WARN_QUEUE_CONSUMER_LAG` baru dipancarkan oleh `process_event` pada baris 110–126. Aturan `observability/alerts.py` menggunakan log tersebut untuk alert lag. Ini menjelaskan jalur observasi yang perlu diperbaiki/dibuktikan; penyebab runtime belum dibuktikan secara eksklusif.

## Blocker dan langkah berikut

Runner `fault_harness.run_scenario_workflow` memanggil `emergency_stop_all` pada seluruh layanan di blok `finally`; replay alternatif memakai fault ID unik dan mereset hanya fault tersebut (`removed_faults=1`). Diperlukan replay instrumented dengan join detail, observasi notification pada skenario fault konkuren, dan pengukuran RSS/CPU terhadap plafon yang disahkan. Review implementasi dan audit sink sebelum menetapkan `VERIFIED`. Parameter correlation window 60 detik dipilih pengguna untuk lab; bukan klaim angka ADR-S05 yang telah dibekukan.
