"""Unit & Integration tests for Multi-Sink DLP Scanner (C15, SEC-03, SEC-01, AT-008, NFR-012)."""

from __future__ import annotations

import json
import subprocess
import sys
import pytest

from scripts.dlp_sink_scanner import DLPSinkScanner


def test_dlp_scanner_detects_synthetic_secrets_and_pii():
    scanner = DLPSinkScanner()

    dirty_payload = (
        "User logged in with bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c "
        "and credit card 4111-2222-3333-4444 with password: 'SuperSecretPassword123!'."
    )

    findings = scanner.scan_text(dirty_payload, source_label="memory-payload")
    categories = [f["category"] for f in findings]

    assert "SEC-03:JWT" in categories
    assert "SEC-03:CARD_PAN" in categories
    assert "SEC-03:CREDENTIAL" in categories

    report = scanner.generate_report()
    assert report["clean"] is False
    assert report["total_violations"] >= 3


def test_dlp_scanner_detects_restricted_docs_ground_truth_and_cot():
    scanner = DLPSinkScanner()

    leak_payload = (
        "Found internal doc classification: restricted for payment-service. "
        "Also reading gt_registry to get ground_truth_label for test. "
        "<think>Internal model scratchpad</think>"
    )

    findings = scanner.scan_text(leak_payload, source_label="leak-source")
    categories = [f["category"] for f in findings]

    assert "SEC-01:RESTRICTED_DOC" in categories
    assert "AT-008:GROUND_TRUTH_LEAK" in categories
    assert any("NFR-012" in c for c in categories)

    report = scanner.generate_report()
    assert report["clean"] is False


def test_dlp_scanner_clean_on_properly_sanitized_artifacts(tmp_path):
    clean_data = {
        "event_id": "aud-1234567890abcdef",
        "action": "TOOL_INVOCATION",
        "target": "search_error_logs",
        "result": "ALLOW",
        "payload": {
            "token": "[REDACTED:SEC-03:JWT]",
            "auth": "[REDACTED:SEC-03:API_KEY]",
            "card": "[REDACTED:SEC-03:CARD_PAN]",
            "notes": "[REDACTED:COT] Final summarized diagnosis only.",
        },
        "sanitized": True,
    }

    clean_file = tmp_path / "clean_trace.json"
    clean_file.write_text(json.dumps(clean_data), encoding="utf-8")

    scanner = DLPSinkScanner()
    scanner.scan_file(clean_file)
    report = scanner.generate_report()

    assert report["clean"] is True
    assert report["total_violations"] == 0


def test_dlp_scanner_cli_exit_codes(tmp_path):
    # 1. Clean file -> exit code 0
    clean_file = tmp_path / "clean.json"
    clean_file.write_text(json.dumps({"status": "ok", "sanitized": True}), encoding="utf-8")

    res_clean = subprocess.run(
        [sys.executable, "scripts/dlp_sink_scanner.py", str(clean_file)],
        capture_output=True,
        text=True,
    )
    assert res_clean.returncode == 0
    assert "[PASS]" in res_clean.stdout

    # 2. Dirty file -> exit code 1
    dirty_file = tmp_path / "dirty.json"
    dirty_file.write_text(
        json.dumps({"token": "bearer secret-api-key-value-1234567890"}), encoding="utf-8"
    )

    res_dirty = subprocess.run(
        [sys.executable, "scripts/dlp_sink_scanner.py", str(dirty_file)],
        capture_output=True,
        text=True,
    )
    assert res_dirty.returncode == 1
    assert "[FAIL]" in res_dirty.stderr
