# Gate G3: catatan preflight, belum ada keputusan resmi

- **Status:** `BLOCKED`; bukan `PASSED`, `FAILED`, atau persetujuan memasuki Fase 4.
- **Run ID:** `c18-20261119T035016Z-preflight`
- **Kandidat saat preflight:** `e1ae7f7d100d50f88ce8244ac5a78c12e922723d`
- **Waktu UTC:** 2026-11-19 03:50:16; versi model/prompt dan otoritas reviewer: `TBD`.
- **Otorisasi/tanda tangan:** belum ada; dokumen ini bukan keputusan reviewer yang berwenang.

## Temuan pemblokir

1. Runner C17 `evaluator/runner.py` hanya menyediakan `join_dev` dan menolak split selain `dev`. Kontrak join juga memerlukan event audit penutupan yang terikat dossier final; docstring menyatakan produser C16 belum menerbitkannya. Ini bertentangan dengan pernyataan siap H-G3 dalam `evidence/c17-20261119T032931Z-6ad5ea8e/C17/readiness-check.md`.
2. `evidence/c17-20261119T032931Z-6ad5ea8e/C17/dev-uat-ledger.md` menandai seluruh 12 test Lampiran A dan AT-001–AT-017 `BLOCKED` untuk acceptance DEV penuh. Prasyarat regresi DEV C18 belum terbukti, meskipun beberapa pemeriksaan pendukung berhasil.
3. H-G3 dan H-G4 berada dalam berkas campuran. Hash utuh tidak membuktikan riwayat nol akses; diperlukan mekanisme pemisahan yang dapat diaudit dan tidak mengekspos isi H-G4, serta bukti bahwa H-G3 tidak dipakai untuk tuning. Membaca semua record untuk memfilter H-G3 tidak memenuhi larangan membaca H-G4.

## Hasil C18

- Red-team terintegrasi 12 ID: `NOT_RUN`; ketiadaan pelanggaran belum terbukti.
- Blind H-G3 dan seluruh KPI-01–KPI-14: `NOT_RUN`; tidak ada dossier atau angka hasil.
- Kedua checksum berkas campuran cocok dengan G1: lihat `preflight-integrity-check.json`. Hash membaca byte seluruh berkas; isi H-G4 tidak diparse atau diuji dalam preflight ini. Riwayat akses dan integritas segel per-split secara independen belum terbukti.
- Tidak ada keputusan resmi atau pengecualian risiko yang ditandatangani. Belum ada bukti hard-stop aktual; `BLOCKED` bukan klaim bahwa pengujian keselamatan lulus.

## Tindak lanjut sebelum pembukaan H-G3

Pemilik dan reviewer berwenang perlu merekonsiliasi status C17 dengan ledger, menetapkan dan menguji jalur evaluator H-G3 beserta audit closure post-`CLOSED`, membuktikan regresi DEV penuh dan kesiapan model/konfigurasi, dan menyetujui prosedur isolasi serta bukti riwayat akses kedua split. Bekukan kembali kandidat dan protokol sebelum satu-satunya evaluasi blind H-G3. H-G4 tetap di luar cakupan C18.
