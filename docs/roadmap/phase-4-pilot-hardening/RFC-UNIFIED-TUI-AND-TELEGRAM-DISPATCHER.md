# RFC: Unified SRE TUI Console & Emergency Telegram Dispatcher

- **Document ID:** `RFC-F4-USABILITY-01`
- **Target Phase:** Phase 4 — Pilot & Hardening (`C19`, `C22`)
- **Status:** `PROPOSED / UNDER_REVIEW` (Belum Final — Memerlukan Review dan Persetujuan Project Authority)
- **Author/Proposer:** SRE Team & Project Initiator
- **Related Requirements:** `BR-005`, `FR-OUT-004`, `RULE-008`, `HUM-01`, `AT-010`, `TBD-11`

---

## 1. Latar Belakang & Masalah (*Problem Statement*)

Selama masa pengembangan Phase 1 hingga Phase 3, antarmuka penelaahan manusia (*human review interface*) dijalankan melalui eksekusi perintah terminal berparameter spesifik:
```bash
python3 scripts/review_console.py --dossier-path artifacts/demo_run/dossiers-json-and-report/sc03-db-pool-exhaustion.json
```
Pendekatan ini sangat berguna untuk pengujian unit dan otomatisasi regresi, namun memiliki sejumlah friksi operasional yang nyata bagi insinyur SRE:
1. **Terfragmentasi:** SRE harus mencari tahu nama file JSON secara manual sebelum bisa melakukan review.
2. **Kurang Real-Time:** Tidak ada satu pintu masuk (*single pane of glass*) untuk melihat kotak masuk (*inbox*) insiden yang baru saja terjadi saat SRE mulai bertugas.
3. **Ketiadaan Saluran Darurat Portabel:** SRE yang sedang piket (*on-call*) di luar jam kerja tidak memiliki saluran notifikasi cepat (seperti Telegram atau Slack) yang mengabarkan bahwa AI telah selesai menyusun berkas investigasi darurat.

---

## 2. Usulan Solusi (*Proposed Design*)

Mengadopsi pola antarmuka alat pengembang modern (seperti OMP, K9s, LazyGit, atau htop), diusulkan penyederhanaan antarmuka SRE menjadi dua modul terpadu:

### 2.1. Unified Terminal User Interface (TUI Dashboard)
* **Single Entrypoint:** Dijalankan dengan satu perintah tunggal:
  ```bash
  python3 -m console
  # atau
  python3 scripts/sre_dashboard.py
  ```
* **Teknologi:** Menggunakan library Python `rich` (yang sudah terpasang di lingkungan proyek) untuk merender layout terminal dua panel yang interaktif dan responsif.
* **Komponen Layout:**
  * **Sidebar Kiri (Navigasi):**
    - `[1] 📥 Active Incidents`: Menampilkan daftar insiden berjalan yang membutuhkan review (status `PENDING_REVIEW`).
    - `[2] 📑 Archive Dossiers`: Riwayat insiden terdahulu yang sudah berstatus `CLOSED`, `REJECTED`, atau `ESCALATED`.
    - `[3] 🏥 Service Health`: Status ketersediaan 5 kontainer microservices sintetis dan sensor OTel di Docker.
    - `[4] 🤖 AI Model Config`: Informasi model yang aktif (OpenRouter Free-Tier / Replay), pemakaian token, dan biaya.
    - `[5] 📲 Telegram Alerts`: Status integrasi webhook notifikasi darurat.
    - `[Q] 🚪 Keluar`: Menutup console.
  * **Main Panel (Konten & Penelaahan):**
    - Menampilkan tabel ringkasan insiden dengan label tingkat keparahan (`[CRITICAL]`, `[HIGH]`, `[MEDIUM]`).
    - Ketika suatu insiden dipilih, layar langsung menyajikan rincian lengkap:
      * Gejala telemetri (*observed symptoms*).
      * Peringkat hipotesis akar masalah hasil analisis AI beserta tingkat keyakinan (*confidence level*).
      * Rujukan SOP resmi dari indeks Qdrant RAG.
      * Bukti telemetri terverifikasi (*evidence IDs*).
  * **Bilah Aksi Peninjau (*Review Action Bar*):**
    - `[A] APPROVE`: Menyetujui hasil analisis AI, mengunci status menjadi `CLOSED`, dan menerbitkan paket serah terima.
    - `[R] REJECT`: Menolak temuan AI dan menandai alasan penolakan.
    - `[C] CORRECT`: Mengoreksi hipotesis akar masalah dan otomatis melahirkan revisi append-only $v(N+1)$.
    - `[E] ESCALATE`: Meneruskan insiden ke Incident Commander tim manual.
    - `[B] BACK`: Kembali ke daftar insiden.

---

### 2.2. Emergency Telegram Alert Dispatcher
* **Fungsi:** Mengirimkan ringkasan darurat ke grup Telegram tim SRE segera setelah agen AI selesai menyusun berkas investigasi (*Dossier*).
* **Payload Pesan Telegram:**
  ```text
  🚨 SRE INCIDENT ALERT [CRITICAL]
  • Incident ID : inc-20261119-01
  • Affected    : ledger-service (db-dummy)
  • Symptom     : Database connection pool exhausted (Error 5xx > 18%)
  • AI Diagnosis: PostgreSQL connection checkout timeout (Conf: 92%)
  • Runbook SOP : SOP-DB-001 (Rev 2.0) Section 4.2
  ──────────────────────────────────────
  👉 Tinjau & Ambil Tindakan di Console:
     python3 -m console
  ```
* **Karakteristik:** Bersifat pasif (*read-only notification*), tidak membuka celah eksekusi perintah sembarangan dari chat Telegram ke server.

---

## 3. Batasan Keamanan & Kepatuhan Tata Kelola (*Governance & Safety*)

Usulan ini dirancang dengan kepatuhan mutlak pada aturan keselamatan proyek:
1. **Zero Auto-Remediation (`RULE-008`, `HUM-01`):**  
   Dashboard ini hanya memfasilitasi penelaahan (*review*) oleh manusia. Menyetujui laporan **tidak akan pernah** mengeksekusi script restart server atau mutasi database secara otomatis.
2. **Isolasi Ground Truth (`RULE-002`, `AT-008`):**  
   Dashboard hanya menampilkan data telemetri yang diobservasi oleh agen; kunci jawaban *ground truth* tetap terisolasi dan tidak ditampilkan di layar penelaah.
3. **Audit Trail Persisten (`C15`, `C16`):**  
   Setiap tombol aksi yang ditekan oleh SRE di dashboard akan dicatat dengan stempel waktu, ID penelaah, dan rantai hash SHA-256 yang tidak dapat diubah (*tamper-evident*).

---

## 4. Status Keputusan & Rencana Uji Coba

* **Status:** `PROPOSED / UNDER_REVIEW` (Belum berstatus `APPROVED` atau bagian dari kontrak final).
* **Uji Coba Rencana:**
  - Prototype usulan ini direncanakan untuk diuji coba kebergunaannya pada pelaksanaan **Chapter 19 (Lab Shadow Pilot)** guna mengukur kemudahan operasional SRE.
  - Jika hasil review pada Chapter 19 memuaskan dan disetujui oleh Project Authority, arsitektur ini akan disahkan sebagai antarmuka resmi untuk demonstrasi pemangku kepentingan pada **Chapter 22 (Reproducibility, Operations, and Demo)**.

