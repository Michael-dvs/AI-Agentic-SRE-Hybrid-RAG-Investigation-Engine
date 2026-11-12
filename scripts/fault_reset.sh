#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:18080}"
echo "[fault_reset] Executing emergency fault reset across all 5 synthetic services..."
python3 -m fault_harness.runner --gateway-url "${GATEWAY_URL}" --emergency-stop

