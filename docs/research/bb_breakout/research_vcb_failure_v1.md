# Volatility Compression Breakout — Failed Strategy

> **TL;DR:** VCB (Bollinger Band squeeze + breakout) does NOT work as a long-only strategy on BTC 1h. All variants are negative expectancy. The compression filter actively hurts performance. However, this research led to the discovery of the profitable BB Upper Breakout strategy (see ../bb_breakout/STRATEGY.md).

## Hypothesis

After periods of abnormally low volatility (BB width compression), price breaks out directionally with volume expansion. The breakout tends to continue, producing a tradeable move. This is a classic trend-following approach popular in traditional markets.

## Signal Logic (Tested)

```
1. Compute Bollinger Band width = (upper - lower) / middle
2. Detect compression: BB width < 20th percentile of its 100-bar history
3. Detect breakout: close > upper_band (long)
4. Volume confirmation: breakout bar volume > 1.5× 20-bar avg volume
5. Entry: next bar open
6. Exit: stop loss, take profit, time exit
```

## Results Summary

### Baseline Variants (all negative)

| Variant | Trades | Sum | Sharpe | Max DD | Win Rate | PF |
|---------|--------|-----|--------|--------|----------|-----|
| VCB Baseline (long+short) | 1030 | +1866.7% | +6.78 | 7.5% | 77.9% | 6.34 |
| VCB Long Only | 393 | -61.7% | -0.49 | 59.9% | 41.5% | 0.85 |
| VCB Long + Volume | 243 | -46.1% | -0.46 | 48.6% | 39.1% | 0.82 |
| VCB Long + SMA200 | 271 | -45.2% | -0.43 | 54.2% | 42.8% | 0.84 |
| VCB Long + Vol + SMA | 166 | -56.1% | -0.69 | 50.1% | 38.5% | 0.70 |

**Note:** The "Baseline (long+short)" with Sharpe +6.78 is an artifact of the signal-reversal exit mechanism, not genuine predictive power. When restricted to long-only, all variants are negative.

### Parameter Sweeps (all negative)

Best parameters found: target=6%, stop=1.5%, hold=4h, compression_pctile=50%
- Sharpe: -0.22 (still negative)
- The 50th percentile compression means "no compression filter" was best

### Walk-Forward (optimized, 6 splits)

| Split | Period | Sum | Sharpe |
|-------|--------|-----|--------|
| 1 | 2019-12→2020-11 | +7.6% | +0.65 |
| 2 | 2020-11→2021-10 | +6.2% | +0.48 |
| 3 | 2021-10→2022-09 | -27.0% | -2.67 |
| 4 | 2022-09→2023-08 | +5.5% | +0.45 |
| 5 | 2023-08→2024-07 | +5.5% | +0.52 |
| 6 | 2024-07→2025-06 | -18.9% | -1.69 |

→ 4/6 profitable, but mean Sharpe: -0.38. Two deeply negative splits.

### Key Findings

1. **Compression filter hurts.** The 50th percentile (no compression requirement) was best. Requiring "tight bands before breakout" eliminates profitable signals.

2. **MFE analysis shows tiny moves.** Mean MFE is only +1.81%, median +1.16%. The "breakouts" produce very small moves before reversing.

3. **4h hold is optimal (but still negative).** The signal has some very short-term momentum (within 4h) but it's too small to overcome stop losses.

4. **Volume confirmation doesn't help.** Higher volume thresholds reduce trade count but never achieve positive expectancy.

5. **BB Lower Band Bounce is TERRIBLE.** As a follow-up, we tested mean-reversion at the lower band: 0/6 walk-forward splits profitable, Sharpe -1.10. Mean reversion at BB bands doesn't work on BTC 1h.

## Why It Failed

1. **BTC 1h doesn't have the same volatility regime dynamics as equities or forex.** Crypto volatility clusters differently. "Compression" on 1h BTC is usually just a brief pause before continuation, not a setup for a new trend.

2. **The BB width percentile is a lagging indicator.** By the time BB width drops below the 20th percentile, the move has often already started. The "breakout" bar is already too late.

3. **Mean reversion doesn't work at 1h scale on BTC.** Both the VCB (which is a form of mean reversion from compressed state) and the BB Lower Bounce fail. BTC 1h is dominated by momentum, not mean reversion.

4. **The long+short baseline profit is a signal-reversal artifact.** When you flip between long and short constantly in an uptrend, the long exits via signal reversal are profitable (you're exiting longs at higher prices). This is not genuine alpha.

## Lessons Learned

1. **Don't assume strategies from traditional markets transfer to crypto.** BB squeeze breakouts are popular in equities but fail on BTC 1h.

2. **Compression filters can hurt more than help.** If the underlying signal (BB breakout) is profitable, adding a compression filter just reduces trade count without improving per-trade expectancy.

3. **The discovery process is valuable.** Even though VCB failed, testing it led to the discovery that simple BB upper breakouts ARE profitable (without the compression filter). This became the BB Upper Breakout strategy (Sharpe +1.38).

4. **MFE analysis is diagnostic.** The tiny MFE (+1.81% mean) told us the signal had no predictive power before we even looked at final PnL.

## Recommendation

### ❌ DISCARD

The Volatility Compression Breakout strategy does not work on BTC 1h. Do not implement.

However, the related **BB Upper Breakout** strategy (without compression filter) IS profitable. See `../bb_breakout/STRATEGY.md`.

## Reproduction

```bash
python research/backtest_vol_compression_breakout.py
python research/backtest_bb_breakout_followup.py
```
