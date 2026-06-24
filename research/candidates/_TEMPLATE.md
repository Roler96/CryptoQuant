# Strategy Candidate: {{NAME}}

**Generated:** {{DATE}}
**Source:** {{SOURCE_TYPE}} — {{SOURCE_URL}}

## Strategy Concept

<!-- 用 3-5 句话描述核心交易逻辑：什么条件触发入场？什么条件退出？逻辑依据是什么？ -->

{{CONCEPT}}

## Pseudocode

```
{{PSEUDOCODE}}
```

## Expected Indicators

<!-- 需要哪些技术指标？检查 signals.py 是否已有 -->

- [ ] {{INDICATOR_1}}
- [ ] {{INDICATOR_2}}

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| {{PARAM_1}} | {{RANGE_1}} | {{DEFAULT_1}} | {{DESC_1}} |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | {{SHARPE_REASON}} |
| MaxDD | <40% | <30% | {{MAXDD_REASON}} |
| Win Rate | >40% | >50% | {{WINRATE_REASON}} |

## References

- [{{REF_TITLE_1}}]({{REF_URL_1}})
- [{{REF_TITLE_2}}]({{REF_URL_2}})

## Implementation Notes

<!-- 实现时需要注意的 CryptoQuant 特定约束 -->

- Use `DEFAULT_PARAMS` dict, never hardcode
- Signal convention: 1=long, -1=short, 0=flat
- Return Series same length as input DataFrame
- Add new indicators to `cryptoquant/strategy/signals.py` if needed
- Use `self.preprocess(df)` for validation
