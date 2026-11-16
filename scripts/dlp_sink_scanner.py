#!/usr/bin/env python3
"""Automated Multi-Sink DLP Scanner (SEC-03, SEC-01, AT-008, NFR-012, C15).

Verifies that security audit logs, AI observability traces, prompt logs, and dossiers
contain ZERO raw synthetic PII/secrets, ZERO restricted/obsolete documents, ZERO ground-truth labels,
and ZERO hidden chain-of-thought (<think> tags).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from typing import Any, Dict, List, Tuple

# Detection patterns for unredacted raw secrets and PII (SEC-03)
# Note: tokens matching [REDACTED:SEC-03:...] are already properly sanitized and ignored.
_UNREDACTED_PATTERNS = [
    ("SEC-03:JWT", re.compile(r"(?<!\[REDACTED:)(?<!\[REDACTED:SEC-03:)\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("SEC-03:API_KEY", re.compile(r"(?i)\b(?:bearer\s+[A-Za-z0-9_\-\.]{16,}|api[_-]?key\s*[:=]\s*[A-Za-z0-9_\-]{16,})\b")),
    ("SEC-03:CREDENTIAL", re.compile(r"(?i)\b(?:password|secret|pwd)\s*[:=]\s*['\"]?(?!\[REDACTED)[^\s,'\"]{6,}['\"]?")),
    ("SEC-03:CARD_PAN", re.compile(r"(?<!\[REDACTED:SEC-03:)\b(?:\d{4}[ -]?){3}\d{4}\b")),
]

# Detection patterns for restricted cross-service knowledge or obsolete SOPs (SEC-01, RAG-01)
_RESTRICTED_DOC_PATTERNS = [
    ("SEC-01:RESTRICTED_DOC", re.compile(r"(?i)\b(?:classification\s*[:=]\s*['\"]?restricted['\"]?|sop-restricted-[a-z0-9-]+)\b")),
    ("SEC-01:OBSOLETE_SOP", re.compile(r"(?i)\b(?:status\s*[:=]\s*['\"]?obsolete['\"]?|sop-obsolete-[a-z0-9-]+)\b")),
]

# Detection patterns for Ground Truth leakage (AT-008, RULE-002)
_GROUND_TRUTH_PATTERNS = [
    ("AT-008:GROUND_TRUTH_LEAK", re.compile(r"(?i)\b(?:gt_registry|ground[_ -]?truth[_ -]?label|fault_injection_seed|target_root_cause_secret)\b")),
]

# Detection patterns for Hidden Chain-of-Thought (NFR-012, AGENTS.md §6.3, RULE-004)
_COT_PATTERNS = [
    ("NFR-012:RAW_THINK_TAG", re.compile(r"(?is)<\s*think\b[^>]*>.*?<\s*/\s*think\s*>")),
    ("NFR-012:RAW_ANALYSIS_TAG", re.compile(r"(?is)<\s*analysis\b[^>]*>.*?<\s*/\s*analysis\s*>")),
    ("NFR-012:UNCLOSED_THINK_TAG", re.compile(r"(?i)<\s*/?\s*think\b")),
]


class DLPSinkScanner:
    """Scans structured files (JSON/JSONL) or in-memory objects across all sinks for leakage."""

    def __init__(self) -> None:
        self.findings: List[Dict[str, Any]] = []
        self.scanned_files: List[str] = []

    def scan_text(self, text: str, source_label: str = "text") -> List[Dict[str, Any]]:
        local_findings: List[Dict[str, Any]] = []

        # 1. Check raw secrets/PII
        for category, pattern in _UNREDACTED_PATTERNS:
            for match in pattern.finditer(text):
                matched_str = match.group(0)
                # Ensure it's not part of a redacted placeholder
                if "[REDACTED:" not in matched_str:
                    local_findings.append({
                        "category": category,
                        "source": source_label,
                        "match_preview": matched_str[:24] + "...",
                        "start_pos": match.start(),
                    })

        # 2. Check restricted docs
        for category, pattern in _RESTRICTED_DOC_PATTERNS:
            for match in pattern.finditer(text):
                local_findings.append({
                    "category": category,
                    "source": source_label,
                    "match_preview": match.group(0)[:32],
                    "start_pos": match.start(),
                })

        # 3. Check ground truth leakage
        for category, pattern in _GROUND_TRUTH_PATTERNS:
            for match in pattern.finditer(text):
                local_findings.append({
                    "category": category,
                    "source": source_label,
                    "match_preview": match.group(0)[:32],
                    "start_pos": match.start(),
                })

        # 4. Check hidden CoT tags
        for category, pattern in _COT_PATTERNS:
            for match in pattern.finditer(text):
                matched_str = match.group(0)
                if "[REDACTED:COT]" not in matched_str:
                    local_findings.append({
                        "category": category,
                        "source": source_label,
                        "match_preview": matched_str[:24] + "...",
                        "start_pos": match.start(),
                    })

        self.findings.extend(local_findings)
        return local_findings

    def scan_file(self, file_path: pathlib.Path | str) -> List[Dict[str, Any]]:
        path = pathlib.Path(file_path)
        if not path.exists():
            return []

        self.scanned_files.append(str(path))
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            err_finding = {
                "category": "SCAN_ERROR",
                "source": str(path),
                "match_preview": str(exc),
                "start_pos": 0,
            }
            self.findings.append(err_finding)
            return [err_finding]

        return self.scan_text(content, source_label=str(path))

    def scan_directory(self, dir_path: pathlib.Path | str, extensions: Tuple[str, ...] = (".json", ".jsonl", ".txt", ".md")) -> List[Dict[str, Any]]:
        root = pathlib.Path(dir_path)
        if not root.exists():
            return []

        all_findings: List[Dict[str, Any]] = []
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in extensions:
                all_findings.extend(self.scan_file(p))
        return all_findings

    def generate_report(self) -> Dict[str, Any]:
        categories: Dict[str, int] = {}
        for f in self.findings:
            cat = f["category"]
            categories[cat] = categories.get(cat, 0) + 1

        is_clean = len(self.findings) == 0
        return {
            "clean": is_clean,
            "total_violations": len(self.findings),
            "violations_by_category": categories,
            "scanned_files_count": len(self.scanned_files),
            "scanned_files": self.scanned_files,
            "findings": self.findings,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-Sink DLP Scanner for C15")
    parser.add_argument("paths", nargs="+", help="Files or directories to scan")
    parser.add_argument("--output", "-o", help="Optional path to write JSON report")
    args = parser.parse_args()

    scanner = DLPSinkScanner()
    for target in args.paths:
        p = pathlib.Path(target)
        if p.is_dir():
            scanner.scan_directory(p)
        elif p.is_file():
            scanner.scan_file(p)
        else:
            print(f"Warning: Target {target} not found, skipping.", file=sys.stderr)

    report = scanner.generate_report()
    report_json = json.dumps(report, indent=2)

    if args.output:
        out_p = pathlib.Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(report_json, encoding="utf-8")
        print(f"DLP report written to {out_p}")
    else:
        print(report_json)

    if not report["clean"]:
        print(f"\n[FAIL] DLP scan detected {report['total_violations']} violations!", file=sys.stderr)
        return 1

    print(f"\n[PASS] DLP scan clean across {report['scanned_files_count']} scanned target(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
