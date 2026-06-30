# CryptoQuant Production Operations Manual

## Quick Start

```bash
# 1. Configure
cp .env.example .env
nano .env               # Fill in OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE

# 2. Review config
nano config.yaml        # Adjust risk params, symbol, timeframe

# 3. Dry-run (validates setup without trading)
uv run python live_runner.py --dry-run

# 4. Start live trading (testnet first!)
uv run python live_runner.py --symbol BTC/USDT --timeframe 1h --interval 60

# 5. Monitor logs
tail -f logs/cryptoquant_$(date +%Y-%m-%d).log
```

## Configuration

All settings in `config.yaml` with `.env` overlay for secrets.

### Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `risk.max_positions` | 3 | Max concurrent positions |
| `risk.max_daily_trades` | 20 | Max trades per day |
| `risk.max_daily_loss_pct` | 5.0 | Daily loss limit (%) |
| `risk.max_daily_loss_abs` | 500.0 | Daily loss limit (USDT) |
| `risk.max_drawdown_pct` | 20.0 | Max drawdown before halt |
| `risk.drawdown_tier1_pct` | 10.0 | Reduce to 50% position size |
| `risk.drawdown_tier2_pct` | 15.0 | Reduce to 25% position size |
| `risk.drawdown_tier3_pct` | 20.0 | Full trading halt |

### Trading Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `trading.account_type` | spot | spot or swap |
| `trading.min_order_usdt` | 10.0 | Minimum order value |
| `trading.max_order_usdt` | 1000.0 | Maximum order value |
| `trading.order_timeout` | 30 | Seconds to wait for fill |
| `trading.cooldown_bars` | 1 | Bars to wait after exit |
| `trading.stop_loss_pct` | null | Stop loss percentage (e.g., 5.0) |
| `trading.take_profit_pct` | null | Take profit percentage (e.g., 10.0) |
| `trading.max_hold_hours` | null | Max hours to hold a position |

## Startup Sequence

1. Load config (`config.yaml` + `.env`)
2. Initialize logging (console + file in `logs/`)
3. Connect to exchange (testnet unless `exchange.okx.testnet: false`)
4. Initialize data feed (SQLite in `data/cryptoquant.db`)
5. Initialize risk manager (load daily stats, set initial balance)
6. Load strategy (from `strategies/` package)
7. Startup health check (exchange connectivity, balance, data freshness)
8. **Reconcile exchange state** — cancel stale orders, sync positions
9. Begin tick loop

## Tick Loop (each interval)

```
┌──────────────────────────────┐
│ 0. Daily reset check         │
│ 1. Cooldown check            │
│ 2. Fetch OHLCV data          │
│ 3. Validate data quality     │
│ 4. Generate signal           │
│ 5. Check position (exchange) │
│    ├─ Has position → exit checks (SL/TP/time/signal)
│    └─ No position → entry checks (risk/signal)
│ 6. Execute order (if needed) │
│ 7. Save state                │
│ 8. Heartbeat (every N ticks) │
└──────────────────────────────┘
```

## Exit Priority

`stop_loss > take_profit > time_exit > signal_reverse`

- **Stop loss**: bar low (long) / bar high (short) crosses stop price
- **Take profit**: bar high (long) / bar low (short) crosses take profit price
- **Time exit**: position held longer than `max_hold_hours`
- **Signal reverse**: strategy generates opposite signal

## Monitoring

### Log Files

```
logs/
├── cryptoquant_YYYY-MM-DD.log  # All levels (DEBUG+)
├── cryptoquant_YYYY-MM-DD.jsonl # JSON format (if json_format: true)
├── error_YYYY-MM-DD.log         # ERROR+ only
├── trade_journal_<strategy>.jsonl # Trade records
└── stdout.log / stderr.log     # systemd captured output
```

### Heartbeat Format

```
[HEARTBEAT] tick=360 bal=10250.00 pos=N trades=5 pnl=+2.50%
```

Appears every `heartbeat_ticks * interval` seconds (default: every hour for 1h bars).

### Key Metrics to Watch

| Metric | Where | What to look for |
|--------|-------|-----------------|
| Balance | heartbeat | Decreasing → losing trades |
| drawdown_tier | heartbeat | REDUCE_HALF/QUARTER/HALT → trouble |
| daily_trades | heartbeat | Hit limit → max_daily_trades reached |
| consecutive_errors | log | 3+ → broker.reconnect() triggered |
| active_orders | heartbeat | Non-zero → unfilled orders stuck |

### Health Check

Run manually: `uv run python -c "from cryptoquant.monitor.health import ..."`

Checks: exchange connectivity, data freshness (<5 min stale), balance (> min_balance), risk state (no emergency stop, normal tier).

## Crash Recovery

On restart, the engine automatically:

1. **Cancels stale orders** — any open orders on the exchange are cancelled
2. **Syncs positions** — fetches actual positions from exchange
3. **Restores risk state** — if position exists on exchange but not in risk manager, it's restored
4. **Loads saved state** — `trades_count`, `total_pnl_pct`, `initial_capital` from state file

State files: `state/state_<strategy>_<symbol>.json` (with SHA-256 checksum + 5 backups)

## Emergency Procedures

### Engine Not Responding

```bash
# Check process
ps aux | grep live_runner

# Graceful stop (SIGTERM → saves state)
kill -TERM <pid>

# Force stop (SIGKILL → no state save)
kill -KILL <pid>
```

### Emergency Stop Triggered

The risk manager triggers emergency stop when:
- Balance drops below `min_balance`
- Drawdown exceeds `max_drawdown_pct`

**Auto-recovery**: cooldown expires after `emergency_cooldown_minutes` → reduced to half-position mode.

**Manual clear** (requires code change or API):
```python
risk_manager.clear_emergency()
```

### Stuck Orders

If an order remains unfilled after `order_timeout` seconds, it's auto-cancelled. To manually cancel all:

```python
broker.cancel_all_orders(symbol)
```

### Data Staleness

If the exchange feed stops, health check fails. The engine continues skipping ticks. Recovery is automatic when data resumes.

## Deployment

### Docker

```bash
docker build -t cryptoquant .
docker run -d \
  --name cryptoquant \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/state:/app/state \
  --env-file .env \
  cryptoquant
```

### systemd (Linux)

```bash
sudo bash deploy/install.sh
sudo systemctl start cryptoquant
sudo systemctl status cryptoquant
sudo journalctl -u cryptoquant -f
```

### Windows

```powershell
# Direct run
uv run python live_runner.py --symbol BTC/USDT --timeframe 1h

# As scheduled task (Task Scheduler)
# Trigger: At system startup
# Action: Start program: C:\Users\<user>\Home\Code\CryptoQuant\.venv\Scripts\python.exe
# Arguments: C:\Users\<user>\Home\Code\CryptoQuant\live_runner.py --symbol BTC/USDT
```

## Alert Webhook

Configure `alert.webhook_url` in config.yaml or env `ALERT__WEBHOOK_URL`.

Supported: Discord, Slack, Teams, or any HTTP POST endpoint.

Alert features:
- **Rate limiting**: max `rate_limit_per_minute` (default 10)
- **Deduplication**: suppresses identical messages within `dedup_window_seconds` (default 300s)

## Pre-Live Checklist

- [ ] `.env` configured with testnet API keys
- [ ] `exchange.okx.testnet: true` in config.yaml
- [ ] `--dry-run` passes without errors
- [ ] Paper trading tested with 100+ ticks
- [ ] Strategy backtested on 1+ year of data
- [ ] Risk limits reviewed for your account size
- [ ] Alert webhook tested (send test CRITICAL log)
- [ ] `stop_loss_pct` and `take_profit_pct` set (or intentionally null)
- [ ] Sufficient balance on exchange (> 2x max_order_usdt)

### Go Live

1. Change `exchange.okx.testnet` to `false`
2. Replace `.env` with live API keys
3. Start with small `max_order_usdt` (e.g., 50 USDT)
4. Monitor for 24h before scaling up
5. Gradually increase `max_order_usdt`

## Directory Structure (runtime)

```
/opt/cryptoquant/
├── .env                  # API keys (not in git)
├── config.yaml           # Runtime configuration
├── live_runner.py        # Main entry point
├── cryptoquant/          # Core library
├── strategies/           # Strategy implementations
├── data/
│   └── cryptoquant.db    # OHLCV cache (SQLite)
├── logs/
│   ├── cryptoquant_*.log # Application logs
│   ├── error_*.log       # Error logs
│   └── trade_journal_*.jsonl # Trade records
└── state/
    └── state_*.json      # Engine state snapshots
```
