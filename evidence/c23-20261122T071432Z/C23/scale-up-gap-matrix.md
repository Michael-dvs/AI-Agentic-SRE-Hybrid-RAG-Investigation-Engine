# Enterprise Scale-Up Gap Matrix — 5 Pillars (`E23`): `c23-20261122T071432Z`

- **Generated At (UTC):** `2026-11-22T07:14:32.283502Z`
- **Boundary Declaration:** `CONCEPTUAL_GAP_ANALYSIS_ONLY` — simulates mechanistic PoC boundaries vs banking enterprise requirements (`BRD §23`).

| Pilar | Kondisi Terbukti di Lab (`C01`–`C22`) | Target Skala Perbankan Enterprise |
|---:|---|---|
| **1. Skala & Volume Telemetri** | 5 synthetic services, ~100 burst EPS, local Loki/Prom/Tempo facades, 20 KB docs / 71 chunks | 10,000-100,000 EPS, distributed OpenSearch/ClickHouse/Mimir, dynamic tail-based trace sampling, 10k-1M chunks |
| **2. Enterprise IAM, CMDB & ITSM** | Static scoped tokens (ADR-S03), static service-catalog.json, local DummyTicketManager stub (AT-017) | Active Directory/LDAP, OAuth2/OIDC + mTLS, dynamic ServiceNow CMDB sync, bidirectional ServiceNow/Jira ITSM (CAP-05) |
| **3. HA/DR & Resiliensi Operasional** | Single-instance Docker Compose, local SQLite orchestrator_state.db, best-effort SLA (NFR-009) | Multi-zone Kubernetes, stateless workers, replicated PostgreSQL/etcd/Kafka HA, conceptual targets RTO < 15 min & RPO < 1 min |
| **4. Kepatuhan Regulasi, Privasi & Kedaulatan Data** | 100% synthetic data/accounts/logs, optional synthetic-only OpenRouter Free-Tier ($0.00) | UU PDP No. 27/2022 & POJK/PBI compliance, strict bank data residency, DPIA, on-premise/air-gapped LLM, KMS/HSM encryption |
| **5. Postur Keamanan Enterprise** | Internal PolicyGateway, FAIL_CLOSED sanitizer, 19 red-team tests (E18) & DLP scanner | Independent third-party VAPT/pentest, formal STRIDE threat model, SIEM/SOC integration, ISO/IEC 27001 & PCI-DSS audit |
