# aisec

AI-driven autonomous penetration testing CLI.

## Install

```bash
pip install git+https://github.com/stuseek/aisec-cli.git
```

## Setup

Get your API token from the dashboard (Settings → Generate Key), then:

```bash
export AISEC_TOKEN=ask_your_token_here
export AISEC_API=https://your-api-url.com
```

Or pass them as flags: `--token` and `--api`.

## Usage

```bash
# Run a scan
aisec scan https://target.com

# Full scan (aggressive + subdomains + 50 iterations)
aisec scan https://target.com --full

# Aggressive mode
aisec scan https://target.com --aggressive

# Stealth mode
aisec scan https://target.com --stealth

# With auth credentials
aisec scan https://target.com -u admin -p admin

# Custom iterations and scope
aisec scan https://target.com --max-iterations 30 --scope domain

# List recent scans
aisec scans

# Check connection
aisec status
```

## Scan Profiles

| Profile | Description |
|---------|-------------|
| (default) | Balanced scan with standard toolset |
| `--stealth` | Slower, WAF evasion, avoids noisy scans |
| `--aggressive` | Full port scan, brute force, sqlmap |
| `--full` | Aggressive + subdomain scope + 50 iterations |
