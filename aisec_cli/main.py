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

import random

import requests
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

THINKING_VERBS = [
    "Thinking", "Analyzing", "Probing", "Investigating", "Evaluating",
    "Inspecting", "Scanning", "Crafting", "Assessing", "Examining",
    "Mapping", "Enumerating", "Fingerprinting", "Strategizing",
]

__version__ = "0.2.0"
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
    body = {"target": target, "source": "cli"}

    # Engine / model
    if args.engine:
        body["engine"] = args.engine
    if args.model:
        body["model"] = args.model

    # Scan type
    if args.scan_type and args.scan_type != "web":
        body["scan_type"] = args.scan_type

    # Profile
    if args.full:
        body["profile"] = "full"
    elif args.bounty:
        body["profile"] = "bounty"
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

    # AI tuning
    if args.temperature is not None:
        body["temperature"] = args.temperature
    if args.review_model:
        body["review_model"] = args.review_model
    if args.cost_cap:
        body["cost_cap"] = args.cost_cap

    # Auth
    if args.username:
        body["username"] = args.username
    if args.password:
        body["password"] = args.password
    if args.cookies:
        cookies_val = args.cookies
        if cookies_val.startswith("@"):
            with open(cookies_val[1:]) as f:
                cookies_val = f.read()
        body["cookies_json"] = cookies_val

    # Network
    if args.proxy:
        body["proxy"] = args.proxy
    if args.headers:
        headers_val = args.headers
        if headers_val.startswith("@"):
            with open(headers_val[1:]) as f:
                headers_val = f.read()
        custom_headers = {}
        for pair in headers_val.replace("\n", ",").split(","):
            pair = pair.strip()
            if ":" in pair:
                k, v = pair.split(":", 1)
                custom_headers[k.strip()] = v.strip()
        if custom_headers:
            body["custom_headers"] = custom_headers

    # Recon
    if args.skip_recon:
        body["skip_recon"] = True
    if args.skip_browser:
        body["skip_browser"] = True

    # Advanced
    if args.localstorage:
        ls_val = args.localstorage
        if ls_val.startswith("@"):
            with open(ls_val[1:]) as f:
                ls_val = f.read()
        body["localstorage_json"] = ls_val
    if args.custom_instructions:
        body["custom_instructions"] = args.custom_instructions
    if args.disable_tools:
        body["disabled_tools"] = [t.strip() for t in args.disable_tools.split(",")]
    if args.disable_enrichments:
        body["disabled_enrichments"] = [e.strip() for e in args.disable_enrichments.split(",")]
    if args.out_of_scope:
        body["out_of_scope"] = [s.strip() for s in args.out_of_scope.split(",")]
    if args.wordlist:
        body["wordlist"] = args.wordlist
    if args.auto_compact:
        body["auto_compact"] = True
    if args.project_id:
        body["project_id"] = args.project_id

    # ── Fetch account info ──────────────────────────────────────────
    account_plan = "?"
    account_credits = 0.0
    try:
        me = requests.get(f"{api_url}/api/v1/auth/me", headers=headers, timeout=5).json()
        account_plan = me.get("plan", "free")
        account_credits = float(me.get("credits_balance", 0))
    except Exception:
        pass

    # ── Create scan ────────────────────────────────────────────────
    opts_str = ", ".join(f"{k}={v}" for k, v in body.items() if k != "target")

    console.print(Panel.fit(
        f"[bold red]aisec — Remote Scan[/bold red]\n"
        f"[dim]Target:[/dim]  [bold]{target}[/bold]\n"
        f"[dim]Account:[/dim] {account_plan} · [bold yellow]{account_credits:.1f}[/bold yellow] credits\n"
        f"[dim]API:[/dim]     {api_url}\n"
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

    thinking_status = None  # Rich Status spinner

    def _stop_thinking():
        nonlocal thinking_status
        if thinking_status:
            thinking_status.stop()
            thinking_status = None

    def _start_thinking():
        nonlocal thinking_status
        _stop_thinking()
        verb = random.choice(THINKING_VERBS)
        thinking_status = console.status(f"[dim italic]{verb}[/dim italic]", spinner="dots", spinner_style="cyan")
        thinking_status.start()

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

            if msg_type == "thinking":
                if data.get("status") == "start":
                    _start_thinking()
                else:
                    _stop_thinking()

            elif msg_type == "console":
                _stop_thinking()
                text = data.get("text", "")
                if text:
                    sys.stdout.write(text + "\n")
                    sys.stdout.flush()

            elif msg_type == "scan_started":
                console.print("[green]Scan started on server[/green]")

            elif msg_type == "finding":
                _stop_thinking()
                findings_count += 1

            elif msg_type in ("credits_update", "cost_update"):
                total_cost = data.get("credits_used", data.get("cost", total_cost))

            elif msg_type == "error":
                _stop_thinking()
                console.print(f"[red][ERROR] {data.get('message', 'Unknown error')}[/red]")

            elif msg_type == "scan_complete":
                _stop_thinking()
                findings_count = data.get("findings", findings_count)
                total_cost = data.get("credits_used", data.get("cost", total_cost))
                duration = data.get("duration", time.time() - start_time)

                # Fetch remaining credits
                remaining = "?"
                try:
                    me = requests.get(f"{api_url}/api/v1/auth/me", headers=headers, timeout=5).json()
                    remaining = f"{float(me.get('credits_balance', 0)):.1f}"
                except Exception:
                    pass

                console.print()
                console.print(Panel.fit(
                    f"[bold green]Scan Complete[/bold green]\n"
                    f"[dim]Findings:[/dim]  {findings_count}\n"
                    f"[dim]Credits:[/dim]   {total_cost:.1f} used · [bold yellow]{remaining}[/bold yellow] remaining\n"
                    f"[dim]Duration:[/dim]  {int(duration)}s",
                    border_style="green",
                ))
                break

    except websocket.WebSocketException as e:
        console.print(f"\n[yellow]WebSocket disconnected: {e}[/yellow]")
        console.print("[dim]Scan may still be running. Check the dashboard.[/dim]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
    finally:
        _stop_thinking()
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
        cost = s.get("credits_used", s.get("total_cost", 0))
        sid = str(s.get("id", ""))[:8]
        created = s.get("created_at", "")[:10]

        console.print(
            f"  [{color}]{status:<10}[/{color}] "
            f"[cyan]{domain:<30}[/cyan] "
            f"{findings:>3} findings  "
            f"{cost:>6.1f} cr  "
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
            f"Credits used: {stats.get('credits_used', stats.get('total_cost', 0)):.1f}[/dim]"
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

    # Scan type
    scan_p.add_argument("--scan-type", choices=["web", "network", "crypto"],
                        default="web", help="Scan type (default: web)")

    # Engine
    scan_p.add_argument("--engine", "-e", choices=["claude", "ollama"],
                        help="AI engine (default: claude)")
    scan_p.add_argument("--model", "-m", help="Model name")
    scan_p.add_argument("--review-model", help="Review model (default: claude-sonnet-4-6)")

    # Profiles
    mode = scan_p.add_mutually_exclusive_group()
    mode.add_argument("--stealth", action="store_true",
                      help="Stealth: slower, WAF evasion, avoid noisy scans")
    mode.add_argument("--aggressive", action="store_true",
                      help="Aggressive: full port scan, brute force, sqlmap")
    mode.add_argument("--full", action="store_true",
                      help="Full scan: aggressive + subdomain scope + 50 iterations")
    mode.add_argument("--bounty", action="store_true",
                      help="Bug bounty: high-impact vulns, skip noise, PoC-ready output")

    # Scan control
    scan_p.add_argument("--max-iterations", "-n", type=int, help="Max iterations (default: 50)")
    scan_p.add_argument("--scope", choices=["target", "domain", "subdomain"],
                        help="Scan scope (default: target)")
    scan_p.add_argument("--timeout", "-t", type=int, help="Timeout in minutes, 0=unlimited")

    # AI tuning
    scan_p.add_argument("--temperature", type=float,
                        help="AI temperature 0.0-1.0 (default: 0.4)")

    # Auth
    scan_p.add_argument("--username", "-u", help="Username for authenticated scanning")
    scan_p.add_argument("--password", "-p", help="Password for authenticated scanning")
    scan_p.add_argument("--cookies",
                        help="Session cookies as JSON string or @filepath (e.g. @cookies.json)")

    # Network
    scan_p.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:8080)")
    scan_p.add_argument("--headers",
                        help="Custom headers as Key:Value pairs, comma-separated or @filepath")

    # Cost
    scan_p.add_argument("--cost-cap", type=float, help="Max credits to spend (0=no limit)")

    # Recon control
    scan_p.add_argument("--skip-recon", action="store_true", help="Skip all recon")
    scan_p.add_argument("--skip-browser", action="store_true", help="Skip browser recon only")

    # Advanced
    scan_p.add_argument("--localstorage",
                        help="Browser localStorage as JSON string or @filepath")
    scan_p.add_argument("--custom-instructions",
                        help="Free-text guidance for the AI agent (max 500 chars)")
    scan_p.add_argument("--disable-tools",
                        help="Comma-separated tools to disable (e.g. sqlmap,hydra,nikto)")
    scan_p.add_argument("--disable-enrichments",
                        help="Comma-separated enrichments to disable (e.g. leak_check,shodan)")
    scan_p.add_argument("--out-of-scope",
                        help="Comma-separated domains/paths to exclude (e.g. payments.example.com,/admin)")
    scan_p.add_argument("--wordlist", choices=["common", "big", "api-endpoints"],
                        help="Wordlist for directory brute force")
    scan_p.add_argument("--auto-compact", action="store_true",
                        help="Auto-compact context for long scans (saves credits)")
    scan_p.add_argument("--project-id",
                        help="Assign scan to a project by ID")

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
