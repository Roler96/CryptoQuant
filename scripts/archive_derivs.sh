#!/usr/bin/env bash
# Nightly derivative archival.
#
# Run from cron. OKX serves ~3 months of funding history and ~30 days of open
# interest; a day missed here cannot be recovered later at any price.
#
# cron starts with almost no environment, which breaks this job in two
# non-obvious ways:
#   1. `uv` is not on the default PATH;
#   2. HTTPS_PROXY is unset, and ccxt sets `session.trust_env = False`, so
#      without an explicit proxy every OKX call ends in a connect timeout.
# Both are handled below rather than assumed.

set -uo pipefail

REPO="${CQ_REPO:-/home/roler/Code/CQuant}"
export PATH="/home/roler/.local/bin:/usr/local/bin:/usr/bin:/bin"

# Override by exporting HTTPS_PROXY before invoking, or by setting CQ_PROXY.
PROXY="${CQ_PROXY:-${HTTPS_PROXY:-http://192.168.10.128:10808}}"
export HTTPS_PROXY="$PROXY" HTTP_PROXY="$PROXY"
export https_proxy="$PROXY" http_proxy="$PROXY"
export NO_PROXY="localhost,127.0.0.1"

cd "$REPO" || { echo "cannot cd to $REPO"; exit 1; }
mkdir -p logs

LOG="logs/archive_derivs.log"
{
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') UTC ==="
  uv run cq data archive-derivs
  status=$?
  echo "exit status: $status"
  # Coverage after the run makes a silent gap visible in the same log.
  uv run cq data coverage
  exit $status
} >> "$LOG" 2>&1
