# Keputusan pemilik: protokol evaluasi C17

- **Otoritas:** Pemilik Proyek, instruksi C17 tanggal 19 November 2026.
- **Status:** `CONFIRMED` untuk aturan yang dinyatakan; tidak mengubah keputusan gate.
- **Cakupan:** kualifikasi evaluator dan regresi `DEV`; bukan persetujuan membuka holdout atau kelulusan G3.

## Taksonomi dan penghitungan

- Nomor `KPI-01`–`KPI-14` mengikuti BRD §15.2. `KPI-05` melaporkan hit-rate@5 dan classical recall@5 secara terpisah; `KPI-09`–`KPI-11` memakai jumlah pelanggaran absolut, target nol.
- `KPI-13` adalah reproducibility clean replay; atribusi origin cascade dilaporkan terpisah untuk `AT-016`. `KPI-14` melaporkan token dan shadow cost per completed incident, termasuk biaya run gagal dalam total; RAM ≤8 GiB dilaporkan terpisah.
- Run gagal atau timeout masuk denominator `KPI-01` dan dihitung gagal pada `KPI-02`; biaya dan token tetap dicatat. Healthy control dikecualikan dari `KPI-02` dan dilaporkan pada false-alarm rate.
- Abstain jujur dengan nol klaim kausal akibat telemetri hilang diberi status `VALID_ABSTAIN` untuk `KPI-03` dan `KPI-04`, bukan diperlakukan sebagai unsupported claim atau skor sempurna.
- Multi-fault `SC-08` lulus `KPI-02` jika setidaknya dua komponen fault teridentifikasi di top-3; laporkan juga primary-cause dan all-causes secara terpisah sesuai ADR-S08.

## Isolasi dan batas bukti

- Evaluasi C17 hanya menggunakan `DEV`. Join GT dilakukan setelah `CLOSED` dan hash dossier cocok dengan event penutupan dalam rantai audit C15 yang terverifikasi. Evaluator dan hasilnya terisolasi dari runtime investigator.
- Pemilik meminta verifikasi checksum dan timestamp holdout serta bukti nol pembacaan. Menghitung checksum memerlukan pembacaan konten, bertentangan dengan larangan membuka holdout selama C17; checksum dan timestamp akses saja juga tidak membuktikan nol pembacaan. Sampai ada audit akses independen yang mencakup interval pengujian dan bukti segel yang dapat diverifikasi tanpa membaca holdout, hasil ini harus dilaporkan `NOT_VERIFIED`, bukan `PASS`.
- C10 dan C11 tetap `IMPLEMENTED`; regresi DEV C17 tidak otomatis mengesahkan chapter atau gate.
