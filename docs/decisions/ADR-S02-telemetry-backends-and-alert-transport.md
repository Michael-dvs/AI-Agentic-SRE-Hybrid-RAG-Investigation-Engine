# ADR-S02: Pipeline Observability (OTel + Prometheus + Loki + Tempo + Grafana) dan Transport Alert Intake

- **ID Keputusan:** `ADR-S02`
- **Status:** `ACCEPTED` (Arsitektur & Kontrak untuk C05/C10; Validasi Kapasitas Runtime pada C05/C08)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C05`, `C08`, `C09`, `C10`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/architecture.md` §6.2, `evidence/c02-20261109T070500Z/C02/service-api-design.md`

---

## 1. Konteks & Permasalahan

Sistem membutuhkan pengumpulan structured logs (`FR-OBS-001`), metrik RED (`FR-OBS-002`), distributed traces (`FR-OBS-003`), serta pengiriman alert terautentikasi (`FR-OBS-004`) yang dapat dikueri secara terbatas (bounded read-only) oleh MCP Gateway tanpa melampaui anggaran memori 8 GiB Docker Lab.

---

## 2. Opsi yang Dipertimbangkan

1. **Opsi 1 (Terpilih): OpenTelemetry Collector + Prometheus (Metrics) + Loki (Logs) + Tempo (Traces) + Grafana (Visualisasi saja).**
2. **Opsi 2: Elastic Stack (Elasticsearch + Logstash + Kibana + Jaeger).** Ditolak karena heap JVM Elasticsearch membutuhkan >2–4 GiB RAM tersendiri.
3. **Opsi 3: File JSON Statis tanpa Backend Telemetri.** Ditolak untuk arsitektur utama karena tidak menguji kegagalan backend nyata (`EV-02`) dan adapter kueri terparameterisasi (`MCP-02`).

---

## 3. Keputusan

1. **Stack Observability (`SELECTED`):** Gunakan **OpenTelemetry Collector**, **Prometheus**, **Loki**, **Tempo**, dan **Grafana** pada jaringan `net_obs` (`TB-02`) dengan alokasi memori gabungan `<= 2.0 GiB` (Prometheus ~512 MiB, Loki ~512 MiB, Tempo ~384 MiB, OTel Collector ~192 MiB, Grafana ~256 MiB).
2. **Grafana Bukan System of Record:** Seluruh tool MCP (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`) wajib membaca langsung dari API Prometheus, Loki, Tempo, dan Service Catalog melalui adapter terparameterisasi—tidak pernah mengandalkan scraping panel UI Grafana.
3. **Transport Alert Intake (`alert-event.v1.schema.json`):** Alert dikirim melalui HTTP POST webhook ke `CMP-INV-01` dengan autentikasi `X-Webhook-Token` / `X-Alert-Signature` (`principal_intake`). Fallback tanpa tanda tangan (*unsigned alert*) dilarang.
4. **Perilaku Backend Hilang (`EV-02`):** Jika Tempo/Loki/Prometheus tidak merespons, adapter wajib mengembalikan `tool-result.v1` dengan `status: "unavailable"`, `data_quality: "unavailable"`, `records: []`, dan `error_code: "SOURCE_UNAVAILABLE"`.

---

## 4. Konsekuensi

- **Positif:** Stack open-source nol biaya (`$0.00`), kompatibel penuh dengan standar OTel, dan muat di dalam profil memori `P2_phase1_g1_foundation`.
- **Tindak Lanjut Wajib:** C05 dan C08 wajib memverifikasi RSS aktual kontainer Prometheus/Loki/Tempo dan mengatur retensi lokal singkat agar pemakaian disk tetap `< 15 GiB`.

