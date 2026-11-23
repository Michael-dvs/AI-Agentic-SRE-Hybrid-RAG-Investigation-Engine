#!/usr/bin/env python3
"""Standalone Live Alert Watcher & Agentic SRE Investigation Worker.

Polls Prometheus `/api/v1/alerts`, intercepts firing alerts, runs the
9-state Agentic SRE investigation workflow, and stores dossiers in
`orchestrator_state.db` for review in `scripts/sre_dashboard.py`.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from rich.console import Console
from rich.markup import escape

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from orchestrator.live_watcher import LiveAlertWatcher

console = Console()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Alert Watcher & Agentic SRE Investigator")
    parser.add_argument("--state-db", default=os.getenv("SRE_STATE_DB", "orchestrator_state.db"))
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:19090")
    parser.add_argument("--loki-url", default="http://127.0.0.1:13100")
    parser.add_argument("--tempo-url", default="http://127.0.0.1:13200")
    parser.add_argument("--poll-interval", type=float, default=4.0, help="Polling interval in seconds")
    parser.add_argument("--cooldown", type=float, default=60.0, help="Deduplication cooldown per alert type")
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    args = parser.parse_args()

    watcher = LiveAlertWatcher(
        state_db=args.state_db,
        prometheus_url=args.prometheus_url,
        loki_url=args.loki_url,
        tempo_url=args.tempo_url,
        cooldown_sec=args.cooldown,
        on_incident=lambda item: console.print(
            f"[bold green][AI INVESTIGATED][/bold green] "
            f"incident=[cyan]{escape(str(item['incident_id']))}[/cyan] "
            f"service=[yellow]{escape(str(item['service_id']))}[/yellow] "
            f"alert=[magenta]{escape(str(item['alert_type']))}[/magenta] "
            f"state=[bold]{escape(str(item['state']))}[/bold]"
        ),
    )

    running = True

    def _stop(_sig: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    console.rule("[bold cyan]Live Alert Watcher & Agentic SRE Investigator[/bold cyan]")
    console.print(f"[bold]Prometheus :[/bold] {escape(args.prometheus_url)}")
    console.print(f"[bold]State DB   :[/bold] {escape(args.state_db)}")
    console.print("[dim]Waiting for firing alerts... (Press Ctrl+C to stop)[/dim]\n")

    while running:
        watcher.poll_once()
        if args.once:
            break
        time.sleep(max(1.0, args.poll_interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
