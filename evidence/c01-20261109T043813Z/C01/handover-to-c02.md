# Handover to Chapter C02 (Architecture, Contracts, and Evaluation Design)

- **From Chapter / Gate:** `C01 — Scope, Keputusan, dan G0` (`Gate G0 = PASS`)
- **To Chapter:** `C02 — Architecture, Contracts, and Evaluation Design` (`docs/roadmap/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md`)
- **Run ID Reference:** `c01-20261109T043813Z`
- **Handover Timestamp (UTC):** `2026-11-09T05:01:30Z` (`2026-11-09T12:01:30+07:00` WIB)
- **Authorized By:** `project-initiator-michael`

## 1. Paket Input Baseline dari C01 untuk C02

Seluruh berkas berikut berada di `evidence/c01-20261109T043813Z/C01/` dan menjadi kontrak input yang mengikat bagi perancangan di Chapter C02:

| Berkas Input C01 | Cara Penggunaan pada Chapter C02 | Batasan Invariant yang Wajib Dipertahankan |
|---|---|---|
| `source-hashes.sha256` & `source-register.md` | Verifikasi integritas sumber acuan sebelum menyusun skema C02 | Jangan mengubah BRD v1.0, Proposal v2.0, atau Master Roadmap secara diam-diam |
| `scope-baseline.md`, `requirements.csv`, `scenario-scope.csv` | Menurunkan kontrak API untuk 5 layanan simulasi (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) dan spesifikasi fixture `SC-01` s/d `SC-14` | Seluruh 88 requirement ID (`Must` & `Should`) dan 14 skenario wajib terakomodasi dalam skema |
| `ownership.md` | Menetapkan pemilik enforcement pada setiap trust boundary dan kontrak skema | Deklarasi `project-initiator-michael` sebagai solo owner/reviewer tetap konsisten |
| `lab-readiness.md` | Menjadi batasan kapasitas keras saat memilih stack pada `ADR-S01`, `ADR-S02`, dan `ADR-S03` | Seluruh layanan + backend telemetri + RAG + agent wajib dirancang agar muat di dalam **alokasi maks 4–6 CPU, 8 GiB RAM, dan 15 GiB Disk** di Docker Compose macOS arm64 |
| `data-handling.md` | Merancang pemisahan jaringan/volume/identitas antara Agent Runtime, Fault Harness, dan Offline Evaluator, serta skema redactor `SEC-03` | Ground Truth dan split holdout (`H-G3`/`H-G4`) tidak boleh memiliki jalur baca dari agent/tools/RAG; tidak boleh ada `.env`/secret di dalam folder sinkronisasi Google Drive |
| `model-and-license-review.md` & `budget-and-schedule.md` | Merancang abstraksi provider model Hybrid (Free-Tier Cloud API + lokal `FastEmbed` / `Ollama <=3B`) dan pencatatan token/biaya | Wajib mematuhi plafon biaya tunai **`$0.00 USD`** dan lisensi open-source/community free |
| `measurement-plan.md` | Merancang skema manifest evaluasi (`run_id`, `scenario_id`, split registry `DEV`/`H-G3`/`H-G4`, dan aturan join GT pasca-`CLOSED`) | Definisi KPI kandidat dan aturan `no_posthoc_change_rule` tidak boleh dilanggar |
| `decision-log.md` & `conflict-log.md` | Menjadi dasar penutupan `ADR-S01`, `ADR-S02`, dan `ADR-S03` di C02 serta persiapan spike `TBD-05`/`TBD-06` menuju G1 | Rekomendasi yang masih berstatus `OPEN` tidak boleh dianggap telah disetujui tanpa analisis ADR |
| `g0-record.md` & `validation-results.csv` | Bukti sah bahwa prasyarat G0 telah `PASS` sebelum C02 dimulai | Jangan mengklaim acceptance test aplikasi (`AT-*` / Lampiran A) telah lulus |

## 2. Daftar Tugas Utama yang Harus Diselesaikan di Chapter C02

Sesuai `00-IMPLEMENTATION-MASTER-ROADMAP.md` §6 (C02):
1. **Trust Boundary & Threat Model Awal:** Menggambar diagram batas identitas, jaringan Docker, dan penyimpanan data antara Investigator, Fault Harness, Offline Evaluator, Reviewer, KB Index, dan Audit Sink.
2. **Katalog Kontrak & Skema Berversi (`Schema Catalog`):**
   - Kontrak API dan korelasi trace antar 5 layanan simulasi (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`).
   - Skema envelope telemetri (`logs`, `metrics`, `traces`, `alerts`) dan *service catalog*.
   - Skema input/output *read-only tool adapters* (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`) beserta status `source_unavailable`, `truncated`, dan `sanitized`.
   - Skema metadata chunk Knowledge Base (`chunk_id`, `document_id`, `document_version`, `status`, `effective_from`, `effective_to`, `service.name`, `environment`, `classification`, `allowed_groups`, `content_hash`).
   - Skema state machine workflow (`RECEIVED` s/d `HUMAN_REVIEW` / `CLOSED`), skema *Incident Investigation Dossier* (JSON & Markdown), dan skema *append-only audit log*.
3. **Desain Evaluasi & Split Registry Terisolasi:** Merancang spesifikasi detail fixture `SC-01` s/d `SC-14`, skema registri split `DEV` / `H-G3` / `H-G4`, rubrik penilaian, dan mekanisme join Ground Truth pasca-penutupan investigasi.
4. **Penutupan ADR Fondasi (`ADR-S01`, `ADR-S02`, `ADR-S03`) & Rencana Spike C08 (`TBD-05`, `TBD-06`):** Menetapkan bahasa/runtime layanan, backend telemetri OTel yang ringan untuk RAM 8 GiB, serta kontrak transport/identitas gateway keamanan.

## 3. Blocker & Risiko Residual yang Harus Dipantau di C02

- **Blocker Aktif Saat Handover:** `Tidak ada` (Gate G0 = `PASS`).
- **Risiko Utama yang Harus Dimitigasi di C02 (`RISK-06` & `RISK-07`):** Pemilihan komponen observability dan vector store di C02 tidak boleh mengalami *overengineering* yang menyebabkan penggunaan memori Docker Compose melampaui plafon 8 GiB RAM pada host macOS 16 GiB.
