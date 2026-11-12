# E11 — Kesiapan dan Bukti Empiris Chapter 11 (C11): Durable Investigation Workflow

- **Run ID:** `c11-20261112T072000Z`; lab simulasi sintetis lokal; reviewer: `TBD`.
- **Status implementasi:** `IMPLEMENTED`; **`VERIFIED` belum dapat dinyatakan** karena gate review formal G2 masih terbuka. G2 belum dievaluasi.
- **Versi komponen:** `workflow_version="1.0.0"`, `policy_version="1.0.0"`, `kb_version="kb-idx-20261111-v1"`, `tool_schema_version="1.0"`, `coordinator_ref="CMP-INV-01"`.
- **Arsitektur:** Mengacu pada pengesahan Gate G1 (`ADR-TBD05` Opsi C: Deterministic Python State Machine Coordinator + SQLite Persistent Store).

---

## 1. Hasil Pengujian Aktual

Rangkaian pengujian unit dan integrasi C11 dijalankan melalui `pytest tests/test_c11_investigation_workflow.py` dengan hasil **16 passed, 0 failed, 0 errors** (dan seluruh suite repository mencapai **120 passed** tanpa regresi).

| Requirement / Test ID | Status | Hasil Aktual & Lokasi Bukti Empiris |
|---|---|---|
| `AT-004` (Sequential 9 States) | `PASS` (lingkup lab) | Seluruh 9 state wajib (`RECEIVED` $\rightarrow$ `CORRELATED` $\rightarrow$ `TRIAGED` $\rightarrow$ `EVIDENCE_COLLECTED` $\rightarrow$ `RETRIEVED` $\rightarrow$ `HYPOTHESES` $\rightarrow$ `VALIDATED` $\rightarrow$ `DRAFTED` $\rightarrow$ `HUMAN_REVIEW`) tereksekusi berurutan tanpa lompatan ilegal. Bukti terekam di [state-transitions.json](state-transitions.json) dengan timestamp ISO 8601 UTC berakhiran 'Z' dan validasi skema kanonikal `workflow-event.v1.schema.json`. |
| `FR-AGT-001` (Strict Transition Check) | `PASS` | Transisi ilegal langsung (misal dari `RECEIVED` ke `HYPOTHESES`) ditolak tegas dengan exception `InvalidStateTransitionError` (`code="INVALID_STATE_TRANSITION"`). |
| `FR-AGT-008` (Version Manifest) | `PASS` | Manifest versi dicatat pada setiap eksekusi dan disematkan ke dalam berkas dossier draft. Bukti: [workflow-manifest.json](workflow-manifest.json). |
| `ADR-TBD05` (SQLite Persistence) | `PASS` | Database SQLite `workflow_evidence.db` memverifikasi ketahanan data pada tabel `incidents`, `state_transitions`, dan `checkpoints` melintasi siklus disconnect/reconnect. |
| `ADR-S05` (Bounded Scope) | `PASS` | Penyelidikan dibatasi secara deterministik pada layanan primer dan tetangga graf dampak (`upstream_callers` + `downstream_dependencies`, kedalaman maksimal 2, total maksimal 5 layanan). |
| `FR-AGT-004` / `OPS-01` (Tool Budget) | `PASS` | Saat pemanggilan tool melebihi kuota (misal plafon 3 atau 30 panggilan), alur berhenti dengan aman (`FAILED_SAFE`), reason_code `BUDGET_EXHAUSTED`, dan kejadian tercatat di DLQ. Bukti: [budget-circuit-dlq-events.json](budget-circuit-dlq-events.json). |
| `FR-AGT-006` / `ADR-S05` (Global Deadline) | `PASS` | Melebihi batas waktu global investigasi (default 120s) memicu abort aman ke `FAILED_SAFE`, reason_code `DEADLINE_EXCEEDED`, dan dicatat di DLQ. |
| `NFR-014` (Circuit Breaker) | `PASS` | Tiga kegagalan berturut-turut pada backend telemetri memicu status `OPEN` pada circuit breaker; kueri berikutnya segera menghasilkan `SOURCE_UNAVAILABLE` tanpa membebani backend; masa pendinginan (cooldown 10s) mengaktifkan `HALF_OPEN`. Bukti: [budget-circuit-dlq-events.json](budget-circuit-dlq-events.json). |
| `FR-AGT-009` (Kill Switch) | `PASS` | Pengaktifan kill switch secara darurat menghentikan alur seketika, mencatat status terminal `CANCELLED` dan `terminal_outcome="TERMINATED_CANCELLED"` pada audit SQLite. Bukti: [cancel-retry-restart-proof.json](cancel-retry-restart-proof.json). |
| `FR-AGT-009` / `AT-012` (Crash Recovery & Resume) | `PASS` (jalur non-LLM) | Simulasi worker terhenti di status `TRIAGED` berhasil dipulihkan melalui `CheckpointManager.recover_in_flight_incidents()` dan dilanjutkan (`resume_investigation`) hingga mencapai `HUMAN_REVIEW` tanpa mengeksekusi ulang tahap sebelumnya. Bukti: [cancel-retry-restart-proof.json](cancel-retry-restart-proof.json). |
| `SC-09` / `EV-02` / `RULE-006` (Trace Outage Uncertainty) | `PASS` | Saat backend tracing mati (`SOURCE_UNAVAILABLE`), validator secara jujur menurunkan status hipotesis menjadi `INCONCLUSIVE` dan mencatat ketiadaan span pada `unknowns`. |
| `EV-01` / `RULE-006` (Conflicting Evidence) | `PASS` | Ketidaksesuaian sinyal (misalnya log galat aktif namun metrik tanpa anomali) menurunkan status menjadi `PARTIAL` dan dicatat eksplisit pada `contradictions`. |
| `FR-RAG-009` (No Applicable Runbook) | `PASS` | Ketika korpus SOP tidak memuat dokumen relevan untuk kode galat/layanan yang diselidiki, sistem menandai `no_applicable_runbook: true` tanpa mengarang sitasi fiktif. |
| `MCP-01` / `KPI-09 = 0` (Zero Mutation) | `PASS` | Seluruh pemanggilan mutatif (`restart_service`, `deploy_service`, `scale_deployment`, `execute_shell`, `run_sql`, `remediate_incident`) ditolak tegas oleh Policy Gateway dengan kode `TOOL_NOT_ALLOWED`. |
| `KPI-10 = 0` / `RULE-002` (Zero GT Leak) | `PASS` | Modul investigator tidak mengimpor atau membaca berkas di direktori `restricted/`, tidak mengekstrak `scenario_id`, dan murni mengandalkan sinyal telemetri aktual. |
| `OPS-01` (Idempotent Replay) | `PASS` | Replay investigasi dengan insiden atau checkpoint yang sama menghasilkan status konsisten tanpa duplikasi atau korupsi riwayat. |

---

## 2. Keterbatasan dan Catatan Integritas

1. **Fase 2 Tanpa LLM Bebas (Zero Free-Form LLM Reasoning):**
   Sesuai `AGENTS.md §6.3` dan Master Roadmap §2.2, tahap penyusunan hipotesis dan validasi pada C11 murni menggunakan **baseline rule engine deterministik**. Penilaian ini membuktikan keandalan plumbing dan state machine; penalaran probabilistik dengan LLM terkontrol baru diaktifkan pada Fase 3 (C13).
2. **Keterbatasan Evaluasi Trace dan Metrik:**
   Uji coba dilakukan di atas backend telemetri simulasi lab (`TestClient` FastAPI C05/C09). Dalam lingkungan produksi, latensi jaringan riil dapat memengaruhi durasi eksekusi kueri telemetri.
3. **Penyimpanan SQLite:**
   Implementasi menggunakan SQLite file-based / in-memory yang memenuhi kebutuhan ketahanan lab (`ADR-TBD05`). Untuk deployment berskala besar dengan multi-worker terdistribusi, migrasi ke storage engine terdistribusi dapat dipertimbangkan di masa mendatang.

---

## 3. Pembersihan & Kesiapan Handover

- Seluruh artefak uji dan transaksi sementara telah terisolasi dalam direktori bukti `evidence/c11-20261112T072000Z/C11/`.
- Tidak ada modifikasi state destruktif pada mock database lab.
- Output modul `orchestrator/` siap digunakan oleh **Chapter 12 (C12: Baseline Dossier and End-to-End G2)** untuk perenderan berkas dossier final (JSON dan Markdown) menuju evaluasi kelulusan **Gate G2**.

