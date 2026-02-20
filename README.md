# aisec

AI-driven autonomous penetration testing CLI.

## Install

```bash
pip install git+https://github.com/stuseek/aisec-cli.git
```

## Setup

Get your API token from the dashboard at [app.aisec.tools](https://app.aisec.tools) → Settings → Generate Key:

```bash
export AISEC_TOKEN=ask_your_token_here
```

That's it. The CLI connects to `api.aisec.tools` by default.

## Usage

```bash
# Run a scan (default: balanced profile)
aisec scan https://target.com

# Full scan (aggressive + subdomains + 50 iterations)
aisec scan https://target.com --full

# Aggressive mode
aisec scan https://target.com --aggressive

# Stealth mode (slow, WAF evasion)
aisec scan https://target.com --stealth

# List recent scans
aisec scans

# Check connection & auth
aisec status
```

## Scan Profiles

| Profile | Description |
|---------|-------------|
| (default) | Balanced scan with standard toolset |
| `--stealth` | Slower, WAF evasion, avoids noisy scans |
| `--aggressive` | Full port scan, brute force, sqlmap |
| `--full` | Aggressive + subdomain scope + 50 iterations |

## Authentication

```bash
# Login credentials (auto-submitted on login forms)
aisec scan https://target.com -u admin -p admin

# Session cookies from file
aisec scan https://target.com --cookies @cookies.json

# Session cookies inline
aisec scan https://target.com --cookies '[{"name":"session","value":"abc123","domain":".example.com"}]'
```

## Scan Control

```bash
# Custom iterations (default: 50)
aisec scan https://target.com --max-iterations 30

# Scope: target (default), domain, subdomain
aisec scan https://target.com --scope domain

# Timeout in minutes (0 = unlimited)
aisec scan https://target.com --timeout 60

# Skip reconnaissance phases
aisec scan https://target.com --skip-recon
aisec scan https://target.com --skip-browser
```

## AI Engine & Model

```bash
# Use Claude (default)
aisec scan https://target.com -e claude

# Use self-hosted Ollama
aisec scan https://target.com -e ollama -m qwen2.5:32b

# Adjust AI temperature (0.0 = precise, 1.0 = creative, default: 0.4)
aisec scan https://target.com --temperature 0.7
```

## Network Options

```bash
# Route traffic through proxy
aisec scan https://target.com --proxy http://127.0.0.1:8080

# Custom headers (comma-separated or from file)
aisec scan https://target.com --headers "X-Auth:token123,X-Custom:value"
aisec scan https://target.com --headers @headers.txt
```

## All Flags

```
aisec scan <target> [options]

Profiles (mutually exclusive):
  --stealth              Slow scanning, WAF/IDS evasion
  --aggressive           All tools, brute-force, no rate limits
  --full                 Aggressive + subdomain scope + 50 iterations

Engine:
  -e, --engine           AI engine: claude (default) or ollama
  -m, --model            Model name (e.g. claude-sonnet-4-5-20250929, qwen2.5:32b)
  --temperature          AI temperature 0.0-1.0 (default: 0.4)

Scan control:
  -n, --max-iterations   Max AI iterations (default: 50)
  --scope                target | domain | subdomain (default: target)
  -t, --timeout          Timeout in minutes, 0=unlimited

Authentication:
  -u, --username         Username for authenticated scanning
  -p, --password         Password for authenticated scanning
  --cookies              Session cookies: JSON string or @filepath

Network:
  --proxy                Proxy URL (e.g. http://127.0.0.1:8080)
  --headers              Custom headers: Key:Value pairs, comma-separated or @filepath

Recon:
  --skip-recon           Skip all infrastructure recon
  --skip-browser         Skip browser-based recon only

Connection:
  --token                API token (or AISEC_TOKEN env var)
  --api                  API URL override (default: https://api.aisec.tools)

aisec scans [options]
  -l, --limit            Number of scans to show (default: 10)

aisec status             Check API connection and authentication
```
