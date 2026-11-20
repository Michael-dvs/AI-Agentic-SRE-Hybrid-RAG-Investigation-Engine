# C20 Tahap 2A: Outage and Kill Switch

- Generated: `2026-11-20T09:09:12.832572Z`
- Scope: `C20_STAGE_2A_DEV_ONLY`
- Safe terminal rate: `100.00%`
- Audit chain valid: `True` (50 events)
- Incidents without audit: `0`
- Auto-remediation triggered: `False`

| Drill | Status | Terminal state | Incident |
|---|---|---|---|
| `llm_outage_timeout` | `PASS` | `HUMAN_REVIEW` | `inc-c20-llm-outage` |
| `telemetry_adapter_outage` | `PASS` | `HUMAN_REVIEW` | `inc-c20-telemetry-outage` |
| `knowledge_base_outage` | `PASS` | `HUMAN_REVIEW` | `inc-c20-kb-outage` |
| `ai_tracer_sink_outage` | `PASS` | `HUMAN_REVIEW` | `inc-c20-tracer-outage` |
| `queue_saturation_backpressure` | `PASS` | `REJECTED_BACKPRESSURE` | `inc-c20-queue-saturation` |
| `emergency_kill_switch` | `PASS` | `CANCELLED` | `inc-c20-rejected-after-kill` |
