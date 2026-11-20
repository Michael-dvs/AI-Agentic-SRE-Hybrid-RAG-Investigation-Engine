# Registri Cacat & Friksi Operasional Lab Shadow Pilot (C19 -> C20)

- **Run ID:** `c19-20261120T083752Z`
- **Total Temuan:** 6

| Defect ID | Kategori | Keparahan | Komponen | Judul | Status |
|---|---|---|---|---|---|
| `C19-DEF-001` | `USABILITY` | `P2-HIGH` | `orchestrator/usability_console.py (SREDashboard.run)` | Reflow layout terminal TUI tertunda saat resize mendadak | `OPEN_FOR_C20` |
| `C19-DEF-002` | `USABILITY` | `P2-HIGH` | `orchestrator/usability_console.py (SREDashboard._dossier_detail)` | Pratinjau isi bukti telemetri dan kutipan teks SOP belum tersedia langsung di TUI | `OPEN_FOR_C20` |
| `C19-DEF-003` | `PERFORMANCE` | `P3-MEDIUM` | `orchestrator/usability_console.py & observability/audit_chain.py` | Pembacaan ulang penuh audit JSONL saat inisialisasi ReviewActionController | `OPEN_FOR_C20` |
| `C19-DEF-004` | `RAG_NAVIGATION` | `P2-HIGH` | `orchestrator/review.py & orchestrator/dossier.py (DossierSerializer.serialize)` | Revisi append-only CORRECT v(N)->v(N+1) tidak mewariskan field evidence/sop_citations dossier terserialisasi | `OPEN_FOR_C20` |
| `C19-DEF-005` | `BASELINE_BIAS` | `P3-MEDIUM` | `evaluator/manual_baseline.py & evaluator/pilot_rubric.py` | Keterbatasan validasi solo-developer dan potensi carryover familiarity | `DOCUMENTED_LIMITATION` |
| `C19-DEF-006` | `RAG_NAVIGATION` | `P2-HIGH` | `orchestrator/investigator.py & knowledge_base/retrieval/prefilter.py` | Ketidakselarasan kontrak index_version_policy ('active_only' vs 'kb_active_alias') dan formulasi query_text | `OPEN_FOR_C20` |

## Detail Temuan & Rencana Perbaikan Chapter 20

### C19-DEF-001: Reflow layout terminal TUI tertunda saat resize mendadak
- **Kategori / Keparahan:** `USABILITY` / `P2-HIGH`
- **Komponen:** `orchestrator/usability_console.py (SREDashboard.run)`
- **Deskripsi:** Loop input Prompt.ask dengan console.clear() per perintah tidak memicu reflow otomatis ketika ukuran terminal berubah antara <100 kolom dan >=100 kolom sebelum pengguna menekan Enter.
- **Konteks Observasi:** Uji navigasi TUI dua panel pada layar lebar (120 cols) dan sempit (72 cols).
- **Rencana Perbaikan (C20):** Tambahkan dukungan refresh viewport eksplisit dan manajemen ukuran panel responsif serta pengujian regresi layout pada berbagai lebar terminal di C20.
- **Status:** `OPEN_FOR_C20`

### C19-DEF-002: Pratinjau isi bukti telemetri dan kutipan teks SOP belum tersedia langsung di TUI
- **Kategori / Keparahan:** `USABILITY` / `P2-HIGH`
- **Komponen:** `orchestrator/usability_console.py (SREDashboard._dossier_detail)`
- **Deskripsi:** Panel detail insiden hanya menampilkan baris ringkas doc_id | section_path dan evidence_id | tool_name tanpa cuplikan isi log/metrik atau excerpt SOP, sehingga penelaah masih perlu membuka berkas handover untuk verifikasi detail saat koreksi.
- **Konteks Observasi:** Penelaahan skenario DEV-03 (SOP-LEDGER-001 v2) dan DEV-06 (aksi CORRECT v1->v2).
- **Rencana Perbaikan (C20):** Tambahkan tampilan ringkasan terikat-panjang (bounded excerpt) yang aman dan ter-sanitasi untuk evidence summary dan metadata versi SOP di panel detail TUI pada C20.
- **Status:** `OPEN_FOR_C20`

### C19-DEF-003: Pembacaan ulang penuh audit JSONL saat inisialisasi ReviewActionController
- **Kategori / Keparahan:** `PERFORMANCE` / `P3-MEDIUM`
- **Komponen:** `orchestrator/usability_console.py & observability/audit_chain.py`
- **Deskripsi:** Setiap instansiasi AuditHashChain/ReviewActionController membaca seluruh log audit append-only secara sinkron; berpotensi menambah latensi I/O ketika jumlah insiden meningkat pada uji burst 100 alert dan konkurensi C20.
- **Konteks Observasi:** Simulasi multi-skenario berurutan dengan pencatatan audit rantai SHA-256.
- **Rencana Perbaikan (C20):** Profilkan I/O audit append dan evaluasi tail/incremental verification pada skenario OPS-01 burst 100 alert serta gelombang konkurensi 5/20/50 di C20.
- **Status:** `OPEN_FOR_C20`

### C19-DEF-004: Revisi append-only CORRECT v(N)->v(N+1) tidak mewariskan field evidence/sop_citations dossier terserialisasi
- **Kategori / Keparahan:** `RAG_NAVIGATION` / `P2-HIGH`
- **Komponen:** `orchestrator/review.py & orchestrator/dossier.py (DossierSerializer.serialize)`
- **Deskripsi:** Ketika AuthorizedReviewManager.submit_review(decision='edit') memanggil DossierSerializer.serialize(edit_ctx, revision=new_rev), edit_ctx memakai kunci dossier terserialisasi ('evidence', 'sop_citations', 'alert_received_at') sementara DossierSerializer membaca kunci konteks investigasi ('evidence_items', 'runbook_citations', 'event_time'). Akibatnya revisi v2 kehilangan daftar bukti dan sitasi SOP dari v1 dan menurunkan status hipotesis koreksi.
- **Konteks Observasi:** Eksekusi skenario DEV-06 (inc-pilot-dev-sc07-006) saat menjalankan aksi TUI CORRECT -> APPROVE.
- **Rencana Perbaikan (C20):** Normalisasi pemetaan field dossier terserialisasi di AuthorizedReviewManager/DossierSerializer pada C20 agar revisi v(N+1) mempertahankan evidence, sop_citations, dan alert_received_at v(N).
- **Status:** `OPEN_FOR_C20`

### C19-DEF-005: Keterbatasan validasi solo-developer dan potensi carryover familiarity
- **Kategori / Keparahan:** `BASELINE_BIAS` / `P3-MEDIUM`
- **Komponen:** `evaluator/manual_baseline.py & evaluator/pilot_rubric.py`
- **Deskripsi:** Pengukuran manual baseline dan penilaian rubrik 5 dimensi dilakukan oleh pemilik proyek tunggal (SELF_EVALUATED_DEVELOPER_LABELS / TBD-02 / TBD-08) tanpa reviewer SME bank eksternal independen.
- **Konteks Observasi:** Penyusunan manual-timing-protocol-and-records dan review-rubric C19.
- **Rencana Perbaikan (C20):** Pertahankan label caveat eksplisit pada laporan KPI-06/KPI-08 di C21 dan dokumentasikan kebutuhan validasi panel SME independen pada analisis kesenjangan enterprise C23.
- **Status:** `DOCUMENTED_LIMITATION`

### C19-DEF-006: Ketidakselarasan kontrak index_version_policy ('active_only' vs 'kb_active_alias') dan formulasi query_text
- **Kategori / Keparahan:** `RAG_NAVIGATION` / `P2-HIGH`
- **Komponen:** `orchestrator/investigator.py & knowledge_base/retrieval/prefilter.py`
- **Deskripsi:** DeterministicInvestigator._step_retrieved mengirim index_version_policy='active_only', sedangkan StrictPreFilter.is_chunk_applicable hanya menerima 'latest', 'kb_active_alias', atau ID versi indeks aktual (mis. 'kb-idx-20261111-v1'), sehingga retrieval mengembalikan status no_match (NO_APPLICABLE_RUNBOOK) kecuali dinormalisasi.
- **Konteks Observasi:** Eksekusi awal lab shadow pilot DEV dengan ToolDispatcher default.
- **Rencana Perbaikan (C20):** Selaraskan index_version_policy menjadi 'kb_active_alias' pada DeterministicInvestigator (atau dukung alias 'active_only' di StrictPreFilter) serta perkaya formulasi query_text dari ringkasan error log aktual pada C20 sebelum pembekuan rilis final.
- **Status:** `OPEN_FOR_C20`
