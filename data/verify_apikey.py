#!/usr/bin/env python3
"""Verify OKX API credentials.

Tests in order:
  1. .env file exists and all required keys are present (no empty values)
  2. Public endpoint reachable (server time) — network + OKX status
  3. Private endpoint (account balance) — API key/secret/passphrase valid

Usage:
    python -m data.verify_apikey            # check production keys
    python -m data.verify_apikey --sandbox  # check sandbox/testnet keys
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so we can import project modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # data/ -> CryptoQuant/
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(PROJECT_ROOT / ".env")

# ── Colour helpers (plain fallback if not a tty) ──────────────────────

def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

def green(text: str) -> str:
    return f"\033[92m{text}\033[0m" if _supports_color() else text

def red(text: str) -> str:
    return f"\033[91m{text}\033[0m" if _supports_color() else text

def yellow(text: str) -> str:
    return f"\033[93m{text}\033[0m" if _supports_color() else text

def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if _supports_color() else text


# ── Step 1: Check .env file ───────────────────────────────────────────

def check_env(sandbox: bool) -> dict:
    """Verify .env file exists and required keys are non-empty."""
    env_path = PROJECT_ROOT / ".env"
    prefix = "OKX_SANDBOX_" if sandbox else "OKX_"

    required = {
        "api_key": f"{prefix}API_KEY",
        "api_secret": f"{prefix}API_SECRET",
        "passphrase": f"{prefix}PASSPHRASE",
    }

    # Fallback: sandbox keys can fall back to production keys
    fallback = {
        "api_key": "OKX_API_KEY",
        "api_secret": "OKX_API_SECRET",
        "passphrase": "OKX_PASSPHRASE",
    }

    print(bold("\n[Step 1] Checking .env credentials"))

    if not env_path.exists():
        print(red(f"  FAIL: .env file not found at {env_path}"))
        print(f"  Hint: copy .env.example to .env and fill in your keys")
        return {}

    print(f"  .env path: {env_path}")

    resolved = {}
    all_ok = True

    for name, env_var in required.items():
        value = os.getenv(env_var)
        source = env_var

        # Sandbox fallback to production keys
        if not value and sandbox:
            fb_var = fallback[name]
            value = os.getenv(fb_var)
            if value:
                source = f"{fb_var} (fallback)"

        if not value:
            print(red(f"  FAIL: {env_var} is missing or empty"))
            all_ok = False
        else:
            masked = value[:4] + "****" + value[-2:] if len(value) > 6 else "****"
            print(green(f"  OK:   {source} = {masked}"))
            resolved[name] = value

    if not all_ok:
        print(red("\n  Cannot proceed — fix the missing keys in .env"))
        return {}

    return resolved


def _build_exchange_config(creds: dict | None = None, sandbox: bool = False) -> dict:
    """Build ccxt exchange config with optional proxy from environment.

    Reads HTTP_PROXY / HTTPS_PROXY / http_proxy / https_proxy and injects
    the first one found as ccxt's proxies setting.
    """
    config: dict = {"enableRateLimit": True}

    if creds:
        config["apiKey"] = creds["api_key"]
        config["secret"] = creds["api_secret"]
        config["password"] = creds["passphrase"]

    # Detect proxy from environment (covers WSL / corporate setups)
    proxy = (
        os.getenv("HTTPS_PROXY")
        or os.getenv("HTTP_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("http_proxy")
    )
    if proxy:
        config["proxies"] = {
            "http": proxy,
            "https": proxy,
        }
        config["aiohttp_proxy"] = proxy

    return config


# ── Step 2: Public endpoint (server time) ─────────────────────────────

def check_public_connectivity(sandbox: bool) -> bool:
    """Fetch OKX server time without authentication."""
    import ccxt

    print(bold("\n[Step 2] Testing public endpoint (server time)"))

    try:
        config = _build_exchange_config(sandbox=sandbox)
        exchange = ccxt.okx(config)
        if sandbox:
            exchange.set_sandbox_mode(True)

        server_time = exchange.fetch_time()
        import datetime
        dt = datetime.datetime.fromtimestamp(server_time / 1000, tz=datetime.timezone.utc)
        print(green(f"  OK:   OKX server time = {dt.isoformat()}"))
        if hasattr(exchange, "close"):
            exchange.close()
        return True

    except ccxt.NetworkError as e:
        print(red(f"  FAIL: Network error — {e}"))
        print("  Hint: check your internet connection or proxy settings")
        return False

    except Exception as e:
        print(red(f"  FAIL: {type(e).__name__} — {e}"))
        return False


# ── Step 3: Private endpoint (account balance) ────────────────────────

def check_private_access(creds: dict, sandbox: bool) -> bool:
    """Fetch account balance to verify API key validity."""
    import ccxt

    mode = "SANDBOX" if sandbox else "PRODUCTION"
    print(bold(f"\n[Step 3] Testing private endpoint (balance) [{mode}]"))

    try:
        config = _build_exchange_config(creds=creds, sandbox=sandbox)

        exchange = ccxt.okx(config)
        if sandbox:
            exchange.set_sandbox_mode(True)

        balance = exchange.fetch_balance()

        # Show non-zero balances
        non_zero = {
            currency: info
            for currency, info in balance.get("total", {}).items()
            if info and float(info) > 0
        }

        if non_zero:
            print(green("  OK:   API key is valid!"))
            print("  Non-zero balances:")
            for currency, amount in sorted(non_zero.items()):
                print(f"    {currency}: {amount}")
        else:
            print(green("  OK:   API key is valid!"))
            print(yellow("  Note:  No non-zero balances found (account may be empty)"))

        if hasattr(exchange, "close"):
            exchange.close()
        return True

    except ccxt.AuthenticationError as e:
        print(red(f"  FAIL: Authentication failed — {e}"))
        print("  Common causes:")
        print("    - Wrong API key, secret, or passphrase")
        print("    - API key belongs to a different OKX account")
        print("    - Using production keys in sandbox mode (or vice versa)")
        print("    - API key has been revoked or expired")
        return False

    except ccxt.NetworkError as e:
        print(red(f"  FAIL: Network error — {e}"))
        print("  Hint: check internet connection or proxy")
        return False

    except Exception as e:
        print(red(f"  FAIL: {type(e).__name__} — {e}"))
        return False


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Verify OKX API credentials",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m data.verify_apikey            # test production keys
  python -m data.verify_apikey --sandbox  # test sandbox/testnet keys
""",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Test sandbox (testnet) credentials instead of production",
    )
    args = parser.parse_args()

    mode = "SANDBOX" if args.sandbox else "PRODUCTION"
    print(bold(f"=== OKX API Key Verification [{mode}] ==="))

    # Step 1: env check
    creds = check_env(args.sandbox)
    if not creds:
        sys.exit(1)

    # Step 2: public connectivity
    if not check_public_connectivity(args.sandbox):
        sys.exit(1)

    # Step 3: private access
    if not check_private_access(creds, args.sandbox):
        sys.exit(1)

    print(bold(green("\n=== All checks passed! API key is valid and working. ===")))
    sys.exit(0)


if __name__ == "__main__":
    main()
