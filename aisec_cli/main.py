#!/usr/bin/env python3
"""
aisec — AI-driven autonomous penetration testing CLI.

Usage:
    aisec scan https://target.com
    aisec scan https://target.com --full
    aisec scan https://target.com --aggressive --max-iterations 30
    aisec scans
    aisec status

Environment variables:
    AISEC_TOKEN  API authentication token
    AISEC_API    API server URL (e.g. https://aisec.example.com)
"""

import argparse
import json
import os
import signal
import sys
import time

import requests
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

__version__ = "0.1.0"
DEFAULT_API = "https://api.aisec.tools"


# ── Scan ────────────────────────────────────────────────────────────────


def cmd_scan(args):
    """Create a scan via API and stream output via WebSocket."""
    token, api_url = _resolve_auth(args)

    target = args.target
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    ws_url = api_url.replace("https://", "wss://").replace("http://", "ws://")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Verify connection ──────────────────────────────────────────
    try:
        r = requests.get(f"{api_url}/health", timeout=5)
        r.raise_for_status()
    except Exception as e:
        console.print(f"[red]Cannot connect to API at {api_url}: {e}[/red]")
        sys.exit(1)

    # ── Build scan body ────────────────────────────────────────────
    body = {"target": target}

    # Engine / model
    if args.engine:
        body["engine"] = args.engine
    if args.model:
        body["model"] = args.model

    # Profile
    if args.full:
        body["profile"] = "aggressive"
        body["scope"] = "subdomain"
        body["max_iterations"] = 50
    elif args.aggressive:
        body["profile"] = "aggressive"
    elif args.stealth:
        body["profile"] = "stealth"

    # Overrides
    if args.max_iterations and not args.full:
        body["max_iterations"] = args.max_iterations
    if args.scope and not args.full:
        body["scope"] = args.scope
    if args.timeout:
        body["timeout_minutes"] = args.timeout

    # Auth
    if args.username:
        body["username"] = args.username
    if args.password:
        body["password"] = args.password

    # Network
    if args.proxy:
        body["proxy"] = args.proxy

    # Recon
    if args.skip_recon:
        body["skip_recon"] = True
    if args.skip_browser:
        body["skip_browser"] = True

    # ── Create scan ────────────────────────────────────────────────
    opts_str = ", ".join(f"{k}={v}" for k, v in body.items() if k != "target")

    console.print(Panel.fit(
        f"[bold red]aisec — Remote Scan[/bold red]\n"
        f"[dim]Target:[/dim] [bold]{target}[/bold]\n"
        f"[dim]API:[/dim]    {api_url}\n"
        + (f"[dim]Config:[/dim]  {opts_str}" if opts_str else ""),
        border_style="red",
    ))

    try:
        r = requests.post(f"{api_url}/api/v1/scans", json=body, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.HTTPError as e:
        console.print(f"[red]Failed to create scan: {e.response.status_code} {e.response.text}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Failed to create scan: {e}[/red]")
        sys.exit(1)

    scan = r.json()
    scan_id = scan["id"]

    if scan.get("status") == "queued":
        pos = scan.get("queue_position", "?")
        console.print(f"[yellow]Scan queued (position {pos}). Waiting for a slot...[/yellow]")
    else:
        console.print(f"[green]Scan created:[/green] [dim]{scan_id}[/dim]")

    console.print(f"[dim]Streaming output...[/dim]\n")

    # ── Connect to WebSocket ───────────────────────────────────────
    try:
        import websocket
    except ImportError:
        console.print("[red]websocket-client not installed. Run: pip install websocket-client[/red]")
        sys.exit(1)

    cancelled = False

    def handle_sigint(signum, frame):
        nonlocal cancelled
        if cancelled:
            console.print("\n[red]Force quit.[/red]")
            sys.exit(1)
        cancelled = True
        console.print("\n[yellow]Cancelling scan...[/yellow]")
        try:
            requests.post(
                f"{api_url}/api/v1/scans/{scan_id}/cancel",
                headers=headers, timeout=10,
            )
        except Exception:
            pass

    old_handler = signal.signal(signal.SIGINT, handle_sigint)

    ws = None
    start_time = time.time()
    findings_count = 0
    total_cost = 0.0

    try:
        ws = websocket.WebSocket()
        ws.settimeout(300)
        ws.connect(f"{ws_url}/ws/scans/{scan_id}?token={token}")

        while True:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                try:
                    ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    break
                continue
            except websocket.WebSocketConnectionClosedException:
                break

            if not raw:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            if msg_type == "console":
                text = data.get("text", "")
                if text:
                    sys.stdout.write(text + "\n")
                    sys.stdout.flush()

            elif msg_type == "scan_started":
                console.print("[green]Scan started on server[/green]")

            elif msg_type == "finding":
                findings_count += 1

            elif msg_type == "cost_update":
                total_cost = data.get("cost", total_cost)

            elif msg_type == "error":
                console.print(f"[red][ERROR] {data.get('message', 'Unknown error')}[/red]")

            elif msg_type == "scan_complete":
                findings_count = data.get("findings", findings_count)
                total_cost = data.get("cost", total_cost)
                duration = data.get("duration", time.time() - start_time)

                console.print()
                console.print(Panel.fit(
                    f"[bold green]Scan Complete[/bold green]\n"
                    f"[dim]Findings:[/dim] {findings_count}\n"
                    f"[dim]Cost:[/dim]     ${total_cost:.2f}\n"
                    f"[dim]Duration:[/dim] {int(duration)}s",
                    border_style="green",
                ))
                break

    except websocket.WebSocketException as e:
        console.print(f"\n[yellow]WebSocket disconnected: {e}[/yellow]")
        console.print("[dim]Scan may still be running. Check the dashboard.[/dim]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        signal.signal(signal.SIGINT, old_handler)


# ── Scans list ──────────────────────────────────────────────────────────


def cmd_scans(args):
    """List recent scans from the API."""
    token, api_url = _resolve_auth(args)
    headers = {"Authorization": f"Bearer {token}"}
    limit = args.limit or 10

    try:
        r = requests.get(f"{api_url}/api/v1/scans?limit={limit}", headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as e:
        console.print(f"[red]Failed to fetch scans: {e}[/red]")
        sys.exit(1)

    data = r.json()
    scans = data.get("items", [])

    if not scans:
        console.print("[dim]No scans found.[/dim]")
        return

    console.print(f"[bold]Recent scans ({data.get('total', 0)} total):[/bold]\n")

    status_colors = {
        "running": "green", "completed": "blue",
        "failed": "red", "cancelled": "dim", "pending": "yellow",
    }

    for s in scans:
        status = s.get("status", "?")
        color = status_colors.get(status, "white")
        domain = s.get("domain", "?")
        findings = s.get("findings_count", 0)
        cost = s.get("total_cost", 0)
        sid = str(s.get("id", ""))[:8]
        created = s.get("created_at", "")[:10]

        console.print(
            f"  [{color}]{status:<10}[/{color}] "
            f"[cyan]{domain:<30}[/cyan] "
            f"{findings:>3} findings  "
            f"${cost:>6.2f}  "
            f"[dim]{created}  {sid}[/dim]"
        )


# ── Status ──────────────────────────────────────────────────────────────


def cmd_status(args):
    """Check API connection and authentication."""
    token, api_url = _resolve_auth(args)

    # Check reachability
    try:
        r = requests.get(f"{api_url}/health", timeout=5)
        r.raise_for_status()
        console.print(f"[green]\u2713 API reachable at {api_url}[/green]")
    except Exception as e:
        console.print(f"[red]\u2717 Cannot reach API: {e}[/red]")
        sys.exit(1)

    # Check auth
    try:
        r = requests.get(
            f"{api_url}/api/v1/stats",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if r.status_code == 401:
            console.print("[red]\u2717 Invalid API token[/red]")
            sys.exit(1)
        r.raise_for_status()
        stats = r.json()
        console.print("[green]\u2713 Authenticated[/green]")
        console.print(
            f"[dim]  Scans: {stats.get('total_scans', 0)} | "
            f"Findings: {stats.get('total_findings', 0)} | "
            f"Cost: ${stats.get('total_cost', 0):.2f}[/dim]"
        )
    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[red]\u2717 Auth failed: {e}[/red]")
        sys.exit(1)


# ── Auth helpers ────────────────────────────────────────────────────────


def _resolve_auth(args):
    """Resolve token and API URL from args or env vars."""
    token = getattr(args, "token", None) or os.environ.get("AISEC_TOKEN", "")
    api_url = getattr(args, "api", None) or os.environ.get("AISEC_API", "") or DEFAULT_API

    if not token:
        console.print("[red]Token required. Use --token or set AISEC_TOKEN env var.[/red]")
        console.print("[dim]Get your token at: https://app.aisec.tools → Settings → Generate Key[/dim]")
        sys.exit(1)

    return token, api_url.rstrip("/")


# ── CLI entry point ─────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(
        prog="aisec",
        description="AI-driven autonomous penetration testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  aisec scan https://example.com\n"
            "  aisec scan https://example.com --full\n"
            "  aisec scan https://app.com -u admin -p admin --aggressive\n"
            "  aisec scans\n"
            "  aisec status\n"
            "\n"
            "Environment variables:\n"
            "  AISEC_TOKEN  API authentication token\n"
            "  AISEC_API    API server URL\n"
        ),
    )
    p.add_argument("--version", action="version", version=f"aisec {__version__}")

    sub = p.add_subparsers(dest="command")

    # ── scan ────────────────────────────────────────────────
    scan_p = sub.add_parser("scan", help="Run a security scan")
    scan_p.add_argument("target", help="Target URL (e.g. https://example.com)")
    scan_p.add_argument("--token", help="API token (or AISEC_TOKEN env)")
    scan_p.add_argument("--api", help="API URL (or AISEC_API env)")

    # Engine
    scan_p.add_argument("--engine", "-e", choices=["claude", "ollama"],
                        help="AI engine (default: claude)")
    scan_p.add_argument("--model", "-m", help="Model name")

    # Profiles
    mode = scan_p.add_mutually_exclusive_group()
    mode.add_argument("--stealth", action="store_true",
                      help="Stealth: slower, WAF evasion, avoid noisy scans")
    mode.add_argument("--aggressive", action="store_true",
                      help="Aggressive: full port scan, brute force, sqlmap")
    mode.add_argument("--full", action="store_true",
                      help="Full scan: aggressive + subdomain scope + 50 iterations")

    # Scan control
    scan_p.add_argument("--max-iterations", "-n", type=int, help="Max iterations (default: 50)")
    scan_p.add_argument("--scope", choices=["target", "domain", "subdomain"],
                        help="Scan scope (default: target)")
    scan_p.add_argument("--timeout", "-t", type=int, help="Timeout in minutes, 0=unlimited")

    # Auth
    scan_p.add_argument("--username", "-u", help="Username for authenticated scanning")
    scan_p.add_argument("--password", "-p", help="Password for authenticated scanning")

    # Network
    scan_p.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:8080)")

    # Recon control
    scan_p.add_argument("--skip-recon", action="store_true", help="Skip all recon")
    scan_p.add_argument("--skip-browser", action="store_true", help="Skip browser recon only")

    # ── scans ───────────────────────────────────────────────
    scans_p = sub.add_parser("scans", help="List recent scans")
    scans_p.add_argument("--token", help="API token (or AISEC_TOKEN env)")
    scans_p.add_argument("--api", help="API URL (or AISEC_API env)")
    scans_p.add_argument("--limit", "-l", type=int, default=10, help="Number of scans to show")

    # ── status ──────────────────────────────────────────────
    status_p = sub.add_parser("status", help="Check API connection")
    status_p.add_argument("--token", help="API token (or AISEC_TOKEN env)")
    status_p.add_argument("--api", help="API URL (or AISEC_API env)")

    args = p.parse_args()

    if not args.command:
        p.print_help()
        sys.exit(1)

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "scans":
        cmd_scans(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
