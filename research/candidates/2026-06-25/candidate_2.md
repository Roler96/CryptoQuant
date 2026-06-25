# Candidate: TrendPullbackRSI

**Date:** 2026-06-25
**Source:** Anti-pattern learning from 2026-06-25 (RSIBBMeanReversion failure) + standard pullback trading literature
**Status:** candidate

## Core Idea

RSI pullback entries WITH a mandatory trend direction filter (EMA). This directly addresses the anti-pattern: "Pure mean reversion without trend filter fails in trending markets."

The strategy only enters in the direction of the trend, using RSI dips/bounces as entry timing:
- **Uptrend** (price > EMA): Wait for RSI to pull back to 40-50 range → enter long (buy the dip)
- **Downtrend** (price < EMA): Wait for RSI to bounce to 50-60 range → enter short (sell the rip)

## Why It's Different

The failed RSIBBMeanReversion entered on RSI<30 + price<BB_lower — which in a bull market meant buying genuinely weak assets. This strategy:
1. **Mandatory EMA trend filter** — never trades against the trend
2. **Moderate RSI thresholds** (40-50, not 30/70) — catches pullbacks, not reversals
3. **Trades WITH momentum** — "buy strength on weakness" rather than "buy weakness"

## Implementation Plan

**Trend Filter:** `EMA(period=200)` — classic institutional trend line
**Entry (Long):** `close > EMA_200 AND 40 <= RSI <= 50 AND RSI rising (RSI > RSI.shift(1))`
**Entry (Short):** `close < EMA_200 AND 50 <= RSI <= 60 AND RSI falling (RSI < RSI.shift(1))`
**Exit:** 
- Stop loss: `ATR(14) * 1.5` from entry
- Take profit: `ATR(14) * 3.0` from entry
- Time exit: after 48 bars (2 days on 1h)
- Trend reversal: `close` crosses `EMA_200`

### Parameters (initial)
- `ema_period`: 200
- `rsi_period`: 14
- `rsi_low`: 40
- `rsi_high`: 50 (long entry zone)
- `rsi_short_low`: 50
- `rsi_short_high`: 60 (short entry zone)
- `atr_period`: 14
- `stop_loss_atr`: 1.5
- `take_profit_atr`: 3.0
- `time_exit_bars`: 48
- `min_bars`: 250 (200 for EMA + buffer)

### Signal Convention
- `1` = long, `-1` = short, `0` = flat
- Exit priority: stop_loss > take_profit > time_exit > trend_reverse

### Expected Trade Count
Target: 50-200 trades/year. RSI dips to 40-50 happen frequently in uptrends (2-4 times/month). Should produce 24-48 long trades + similar shorts.

## Risks & Mitigations

- **EMA lag:** EMA(200) is slow to react. In a sudden trend change, the strategy may continue trading the old direction for several bars.
  - Mitigation: time exit (48 bars) limits exposure. Also, ATR-based SL catches sharp reversals.
- **Range-bound markets:** If price oscillates around EMA(200), chop risk increases.
  - Mitigation: RSI rising/falling condition filters some noise.

## Test Plan

Test on BTC/USDT and ETH/USDT, 1h and 4h timeframes. 365-day lookback.
Gate thresholds: ≥30 trades, Sharpe >0.5, MaxDD <30%.
