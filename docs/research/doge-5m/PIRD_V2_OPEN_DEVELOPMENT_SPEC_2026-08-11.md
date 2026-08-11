# PIRD v2 — Propagator Impact Residual Decay

日期：2026-08-11
状态：开放开发规格；历史数据均为已见 research pool，不构成确认样本。

## 1. 目标

检验 DOGE 5m bar 中，正常 signed-flow impact 之外的同向价格 overshoot 是否在随后30–120分钟衰减。

PIRD v2 不交易低成交额流动性真空，也不交易“强流、弱价格”的 muted-flow 状态。它要求至少正常成交活动、传播子预测与实际收益同向，随后逆向交易超出传播子解释的 residual。

## 2. 输入和执行

- 市场：`DOGE-USDT-SWAP`
- 周期：原生5m标准 OHLCV
- 只使用 DOGE 自身数据
- 成交额代理：`A_t = close_t * volume_t`
- bar `t` 收盘决策，`t+1 open` 成交
- target weight：`0.25 * signal`
- 主成本：15 bps/side
- 持仓期间忽略新信号，不直接翻仓
- 固定持有后发 flat intent，下一根 open 平仓
- 缺完整退出 open 时不入场

## 3. 因果特征

```text
r_t = log(close_t / close_{t-1})
M_t = median(A_{t-288}, ..., A_{t-1})
CLV_t = 2*(close_t-low_t)/(high_t-low_t)-1
q_t = CLV_t * log1p(A_t/M_t)
```

非有限值、非正价格、`volume<=0`、`high<=low` 或时间缺口使当前状态无效。发生无效bar后传播子重置并重新burn-in。

`tau` 表示半衰期bars：

```text
a = 2**(-1/tau)
I_t = a*I_{t-1} + q_t
g_t = I_t-I_{t-1} = q_t-(1-a)*I_{t-1}
B = ceil(5*tau)
```

每次重置后的前 `B` 根有效bar只更新状态，不进入模型拟合。

## 4. 日更模型

UTC每天第一根bar开始前，仅使用此前连续的 `W` 个有效 `(g_i,r_i)`：

```text
r_i = alpha + beta*g_i + epsilon_i
beta = cov(g,r)/var(g)
alpha = mean(r)-beta*mean(g)
sigma_e = 1.4826*median(abs(epsilon-median(epsilon)))
```

当天固定使用同一组 `alpha/beta/sigma_e`，不会读取当天未来bar。

当前bar：

```text
pred_t = alpha + beta*g_t
e_t = r_t-pred_t
z_t = e_t/sigma_e
```

## 5. 信号

仅在以下条件同时满足时触发：

```text
beta > 0
abs(z_t) >= z_resid
A_t/M_t >= 1
sign(pred_t) == sign(e_t) == sign(r_t) != 0
abs(pred_t)/abs(r_t) >= 0.25
```

信号方向：`signal_t = -sign(e_t)`。

## 6. 开放探索网格

阶段A固定 `L=288, H=12`：

```text
W       in {2016, 4032}
tau     in {3, 6, 12}
z_resid in {3.0, 4.0}
```

共12组。

只有同一 `W,z_resid` 下至少两个相邻tau同时满足以下条件，才存在结构平台：

- 至少30 episodes；
- 净收益>0；
- daily Sharpe>=0.50；
- MaxDD>=-20%；
- long与short aggregate PnL均>0。

存在平台时，选择相邻tau中的自然中心，并额外运行 `H in {6,24}`；否则PIRD v2直接停止。

## 7. 晋级后的消融

仅在主规格形成平台后运行：

1. raw-return reversal；
2. 以无记忆 `q_t` 替代 `g_t`；
3. 以纯CLV替代成交额加权flow；
4. 同事件顺 residual 交易；
5. 取消高活动门的污染诊断；
6. 研究脚本中的真实 quote-volume 替代检查。

主规格必须优于 raw-return reversal 和无记忆消融，否则标记 `MECHANISM_FAIL`。

## 8. 表述边界

全部可用历史已经被开放研究查看。本轮只产生 development evidence；任何盈利结果都不能称为 OOS、forward-confirmed 或可部署。
