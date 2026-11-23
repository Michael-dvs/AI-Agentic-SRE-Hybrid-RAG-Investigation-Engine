#!/usr/bin/env python3
"""CLI Runner for Realistic Continuous Banking Traffic & Dynamic Anomaly Simulator.

Simulates mixed high-volume banking traffic (Transfer, QRIS, Notifications,
Transaction Lookup, Health Checks) with time-varying operational regimes and
periodic signed C04 chaos fault injections.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time

import httpx
from rich.console import Console
from rich.markup import escape
from rich.table import Table

# Add repo root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from orchestrator.live_watcher import LiveAlertWatcher
from traffic.bank_simulator import BankingTrafficSimulator, TransactionTelemetry

console = Console()


def render_event_line(t: TransactionTelemetry) -> None:
    time_str = t.timestamp.split("T")[1][:8] if "T" in t.timestamp else t.timestamp[:8]
    if t.is_error:
        status_style = "bold red"
        err_label = escape(t.error_code or "ERR")
        status_text = f"[{t.status_code}] FAIL ({err_label})"
    else:
        status_style = "bold green"
        status_text = f"[{t.status_code}] OK"

    console.print(
        f"[dim]{time_str}[/dim] [cyan]#{t.seq_id:04d}[/cyan] "
        f"[magenta]{escape(t.regime):<17}[/magenta] "
        f"[bold]{escape(t.operation):<19}[/bold] via [yellow]{escape(t.channel):<16}[/yellow] "
        f"-> [{status_style}]{status_text:<24}[/{status_style}] "
        f"[dim]({t.duration_ms:.1f}ms)[/dim]"
    )


def render_status_line(message: str) -> None:
    console.print(f"[bold yellow]{escape(message)}[/bold yellow]")


def check_gateway_ready(target_url: str) -> tuple[bool, str]:
    try:
        resp = httpx.get(f"{target_url.rstrip('/')}/health/ready", timeout=3.0)
        if resp.status_code == 200:
            return True, "OK"
        return False, f"Gateway returned HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuous Banking Traffic & Dynamic Anomaly Simulator"
    )
    parser.add_argument(
        "--target-url",
        default="http://127.0.0.1:18080",
        help="API Gateway URL (default: http://127.0.0.1:18080)",
    )
    parser.add_argument(
        "--harness-url",
        default="http://127.0.0.1:18080",
        help="Fault Harness Proxy URL (default: http://127.0.0.1:18080)",
    )
    parser.add_argument(
        "--prometheus-url",
        default="http://127.0.0.1:19090",
        help="Prometheus Alert URL (default: http://127.0.0.1:19090)",
    )
    parser.add_argument("--rps", type=float, default=2.0, help="Base requests per second (default: 2.0)")
    parser.add_argument("--count", type=int, default=None, help="Number of requests to send (default: continuous)")
    parser.add_argument("--duration", type=float, default=None, help="Duration in seconds to run")
    parser.add_argument("--no-faults", action="store_true", help="Disable periodic chaos fault injection")
    parser.add_argument("--fault-interval", type=float, default=50.0, help="Interval between chaos faults in seconds (default: 50s)")
    parser.add_argument("--fault-duration", type=float, default=15.0, help="Duration of each chaos fault in seconds (default: 15s)")
    parser.add_argument("--regime-duration", type=float, default=30.0, help="Seconds before workload regime shifts (default: 30s)")
    parser.add_argument("--state-db", default=os.getenv("SRE_STATE_DB", "orchestrator_state.db"), help="Workflow state SQLite DB for dossiers")
    parser.add_argument("--loki-url", default="http://127.0.0.1:13100", help="Loki URL (default: http://127.0.0.1:13100)")
    parser.add_argument("--tempo-url", default="http://127.0.0.1:13200", help="Tempo URL (default: http://127.0.0.1:13200)")
    parser.add_argument("--no-investigate", action="store_true", help="Disable automatic AI investigation when alerts fire")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip /health/ready preflight check")
    args = parser.parse_args()

    watcher: LiveAlertWatcher | None = None
    if not args.no_investigate and args.prometheus_url:
        watcher = LiveAlertWatcher(
            state_db=args.state_db,
            prometheus_url=args.prometheus_url,
            loki_url=args.loki_url,
            tempo_url=args.tempo_url,
            cooldown_sec=max(15.0, args.fault_interval * 0.8),
            on_incident=lambda item: console.print(
                f"[bold green][AI INVESTIGATED][/bold green] "
                f"incident=[cyan]{escape(str(item['incident_id']))}[/cyan] "
                f"service=[yellow]{escape(str(item['service_id']))}[/yellow] "
                f"-> [bold]{escape(str(item['state']))}[/bold] (cek Active Incidents di sre_dashboard.py)"
            ),
        )

    async def _handle_firing_alerts(_alerts: list[dict[str, object]]) -> None:
        if watcher is not None:
            await asyncio.to_thread(watcher.poll_once)

    try:
        simulator = BankingTrafficSimulator(
            target_url=args.target_url,
            harness_url=args.harness_url,
            prometheus_url=args.prometheus_url or None,
            rps=args.rps,
            enable_faults=not args.no_faults,
            fault_interval_sec=args.fault_interval,
            fault_duration_sec=args.fault_duration,
            regime_duration_sec=args.regime_duration,
            on_event=render_event_line,
            on_status=render_status_line,
            on_alerts=_handle_firing_alerts if watcher is not None else None,
        )
    except ValueError as exc:
        console.print(f"[bold red]Konfigurasi tidak valid:[/bold red] {escape(str(exc))}")
        return 2

    if not args.skip_preflight:
        ok, detail = check_gateway_ready(args.target_url)
        if not ok:
            console.print(
                f"[bold red]Gateway tidak dapat dijangkau di {escape(args.target_url)}:[/bold red] "
                f"{escape(detail)}"
            )
            console.print(
                "[yellow]Pastikan stack Docker lab sudah berjalan dengan perintah:[/yellow] "
                "[bold cyan]./scripts/lab_up.sh[/bold cyan]\n"
                "[dim](Atau gunakan --skip-preflight jika ingin tetap menjalankan simulator).[/dim]"
            )
            return 1

    console.rule("[bold cyan]Banking Traffic & Dynamic Chaos Anomaly Simulator[/bold cyan]")
    console.print(f"[bold]Target Gateway  :[/bold] {escape(args.target_url)}")
    console.print(f"[bold]Base RPS        :[/bold] {args.rps} req/sec (dinamis per regime + jitter)")
    console.print(f"[bold]Regime Shift    :[/bold] Every {args.regime_duration}s")
    chaos_badge = "[bold red]ENABLED[/bold red]" if not args.no_faults else "[bold green]DISABLED[/bold green]"
    console.print(f"[bold]Chaos Injections:[/bold] {chaos_badge}")
    if not args.no_faults:
        console.print(f"[bold]Chaos Interval  :[/bold] Every {args.fault_interval}s for {args.fault_duration}s")
    console.print("[dim]Press Ctrl+C to safely stop traffic generation and reset active faults.[/dim]\n")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal() -> None:
        console.print("\n[yellow]Stopping simulator gracefully and resetting active faults...[/yellow]")
        simulator.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    try:
        t0 = time.monotonic()
        telemetries = loop.run_until_complete(
            simulator.run(count=args.count, duration_sec=args.duration)
        )
        elapsed = time.monotonic() - t0

        total = len(telemetries)
        if total > 0:
            success = sum(1 for t in telemetries if not t.is_error)
            errors = total - success
            avg_lat = sum(t.duration_ms for t in telemetries) / total

            console.rule("[bold cyan]Traffic Run Summary[/bold cyan]")
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Metric", style="dim")
            table.add_column("Value", justify="right")
            table.add_row("Total Transactions", str(total))
            table.add_row("Successful (2xx)", f"[green]{success}[/green]")
            table.add_row("Errors / Anomalies", f"[red]{errors}[/red]")
            table.add_row("Total Elapsed Time", f"{elapsed:.1f} s")
            table.add_row("Actual Average RPS", f"{total / max(0.1, elapsed):.2f} req/s")
            table.add_row("Average Latency", f"{avg_lat:.2f} ms")
            console.print(table)
    except KeyboardInterrupt:
        simulator.stop()
        console.print("\n[yellow]Simulator aborted by user.[/yellow]")
    finally:
        loop.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
