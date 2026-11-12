#!/usr/bin/env bash
set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:18080}"

echo "[lab_smoke] Checking Gateway readiness at ${GATEWAY_URL}/health/ready ..."
curl -fsS "${GATEWAY_URL}/health/ready" | python3 -m json.tool

echo "[lab_smoke] Running deterministic normal traffic profile (seed=20261109, count=6)..."
python3 -m traffic.generator --target-url "${GATEWAY_URL}" --profile normal --seed 20261109 --count 6

