#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[lab_up] Building and starting sre-agentic-sim stack..."
docker compose up -d --build --wait
echo "[lab_up] All C03 synthetic services and supporting stores are healthy."
docker compose ps

