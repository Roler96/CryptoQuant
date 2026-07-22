#!/usr/bin/env bash
# Hourly derivative archival plus the immutable OIFR forward observer.
#
# Run from cron at minute 10 of every UTC hour. OKX serves ~3 months of funding
# history and ~30 days of open interest; an OIFR decision missed after minute
# 30 is deliberately not backfilled.
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
  overall=0

  # The observer needs the just-closed DOGE spot and swap bars as well as the
  # derivative snapshot. Use an explicit rolling window: an old database may
  # contain bars without an `ohlcv_sync` completion marker, in which case the
  # generic incremental resumer correctly (but far too slowly for this hourly
  # observer) restarts at 2021. Re-reading three days is bounded and leaves any
  # longer outage visible as `data_unavailable`, never silently backfilled as a
  # forward signal.
  SYNC_START="$(date -u -d '3 days ago' '+%Y-%m-%d')"
  uv run cq data sync --start "$SYNC_START" --instruments DOGE-USDT DOGE-USDT-SWAP
  sync_status=$?
  if [ "$sync_status" -ne 0 ]; then
    overall=$sync_status
  fi

  uv run cq data archive-derivs
  archive_status=$?
  if [ "$archive_status" -ne 0 ]; then
    overall=$archive_status
  fi

  uv run cq research observe-oifr
  observer_status=$?
  if [ "$observer_status" -ne 0 ]; then
    overall=$observer_status
  fi

  # Coverage after the run makes a silent gap visible in the same log.
  uv run cq data coverage
  echo "sync=$sync_status archive=$archive_status observer=$observer_status overall=$overall"
  exit $overall
} >> "$LOG" 2>&1
