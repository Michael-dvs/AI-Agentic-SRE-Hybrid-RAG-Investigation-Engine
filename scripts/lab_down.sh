#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REMOVE_VOLUMES="${1:-}"
if [[ "$REMOVE_VOLUMES" == "--volumes" || "$REMOVE_VOLUMES" == "-v" ]]; then
  echo "[lab_down] Stopping stack and removing volumes..."
  docker compose down -v --remove-orphans
else
  echo "[lab_down] Stopping stack (preserving PostgreSQL volume)..."
  docker compose down --remove-orphans
fi

