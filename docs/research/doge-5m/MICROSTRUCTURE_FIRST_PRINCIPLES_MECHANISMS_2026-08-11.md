# DOGE-only 5m：三个微观结构 / 随机过程机制设计

- 日期：2026-08-11
- 研究角色：**开发候选设计**；仓库历史池及相关日期已被反复查看，因此后续结果只能称为 development evidence，不能称 OOS。
- 市场：`DOGE-USDT-SWAP`，5m 原生 OHLCV；允许 long/short，最大 1x。
- 执行：bar `t` 收盘后决策，bar `t+1` open 成交；每次开、平各扣 15 bps/side。
- 持有约束：最短 6 bars（30m），最长 144 bars（12h）。
- 输入限制：只读标准 bar 字段 `ts, open, high, low, close, volume`。成交额代理一律定义为 `dvol_t = close_t * volume_t`；即使数据库另有 `quote_volume` 也不读取，确保机制可由标准 OHLCV 严格复现。
- 去重声明：不采用仓库已有的 Donchian、coherent-path efficiency reversal、upper-range acceptance、negative-funding rebound、spot/swap participation persistence、逐-bar GBM 或跨币种残差机制。

## 0. 共用因果与数据契约

对按 `ts` 升序且连续的 5m bar：

```text
p_t = log(close_t)
r_t = p_t - p_{t-1}
dvol_t = close_t * volume_t                # 标准OHLCV成交额代理
slot_t = ((ts_t / 300000) mod 288)         # UTC 5m slot, 0..287
```

1. `high >= max(open,close)`、`low <= min(open,close)`、价格严格正、成交量非负；任何非有限值使 run INVALID。
2. `high<=low` 或 `volume<=0` 的 bar 不产生信号；不得删除后把不连续时间误当连续。所有 rolling window 都要求相邻时间戳差恰为 300000ms。
3. rolling 估计在计算事件 `t` 时只使用 `<=t-1`；事件本身只进入事件统计，不进入自己的基准。
4. 活跃仓位期间忽略新信号；固定持有后在决策 bar 发 flat intent，下一 bar open 平仓。若 segment 尾部没有完整退出 open，则不入场。
5. 不使用 bar 内止盈/止损，避免 OHLC 无法识别同 bar 触发先后。每个 episode 恰有 entry/exit 两个 open fill。
6. 多空对称；方向记为 `s in {-1,+1}`。目标仓位固定 `s * 0.25`，不把仓位大小放进参数网格。
7. 同一时间只运行一个机制时，成本按 target notional 的换手逐 side 收取 15 bps；反向不得一步翻仓，必须先平，下一 bar 才可重新入场。

---

## 1. JDAC：跳跃—扩散分解后的“永久跳跃确认”

### 1.1 第一性原理

在 jump-diffusion 中，短时收益写为：

```text
dp_t = mu dt + sigma_t dW_t + J_t dN_t
```

连续扩散噪声由相邻绝对收益的 bipower variation（BV）估计；单根收益显著超出该扩散尺度时才称为 jump。若 jump 携带新信息，其价格位移应在短暂做市库存调整后保留；若是纯流动性冲击，它会迅速回吐。因此本机制不是普通突破：先识别统计跳跃，再等待一个预先固定的“永久性确认窗”，只交易未衰减的跳跃方向。

### 1.2 严格 bar 定义

在候选 jump bar `t`，用此前 `n` 根收益（结尾为 `t-1`）计算：

```text
BV_t = (pi/2) * sum_{i=t-n+1}^{t-1} |r_i| |r_{i-1}| / (n-1)
sigmaD_t = sqrt(BV_t)                     # 每 bar 扩散尺度
zJ_t = |r_t| / max(sigmaD_t, 1e-12)
s = sign(r_t)
```

说明：这里 `BV_t` 是相邻乘积的均值形式，因此 `sqrt(BV_t)` 已是每-bar尺度，不再除以 `sqrt(n)`。

事件条件：

```text
zJ_t >= z_jump
|r_t| / log(high_t/low_t) >= body_ratio   # 方向位移不是纯双边振荡
dvol_t / median(dvol_{t-n:t-1}) >= v_jump
```

若满足，等待 `d` 根完整 bar，到 `u=t+d` 收盘计算跳跃保留率：

```text
retention = s * (p_u - p_{t-1}) / |r_t|
post_noise = sqrt(sum_{i=t+1}^{u} r_i^2)
```

仅当 `retention >= rho` 且 `s*(p_u-p_t) >= -0.5*post_noise` 时，于 `u+1` open 顺 jump 方向入场。第二项禁止“总位移勉强保留但确认窗正在快速反向”的情况。固定持有 `H` 根 5m bar；在入场后的第 `H` 根 bar 收盘发 flat，下一 open 平仓。

### 1.3 有限参数网格（36 组）

固定：`body_ratio=0.60`，`v_jump=2.0`。

```text
n       in {144, 288}          # 12h / 24h 扩散基准
z_jump  in {4.0, 5.0, 6.0}
d       in {2, 3}              # 10m / 15m 确认
rho     in {0.60, 0.80}
H       in {12, 24, 48}        # 1h / 2h / 4h
```

为控制搜索量，采用分阶段冻结而非 2*3*2*2*3=72 全笛卡尔积：

- 结构扫描（24组）：`H=24`，扫描 `n × z_jump × d × rho`。
- 持有扫描（12组）：只对结构扫描预先规定的 plateau center（按相邻通过数、非最佳 Sharpe）扫描 `H`；若没有 plateau，JDAC 淘汰，不进入持有扫描。

### 1.4 机制可证伪预测

- 真 jump 的 forward return 应随 `zJ` 增大而同向改善，而不是只在单一阈值有效。
- `rho` 提高应减少交易并提高单笔 gross expectancy；若相反，所谓“永久确认”没有区分力。
- 消融 `BV jump gate`、改成普通 `|r_t|` 百分位后若不劣，jump-diffusion 解释被否定。

---

## 2. PIRD：传播子模型的瞬态价格冲击残差衰减

### 2.1 第一性原理

线性 propagator 模型把价格变化拆成订单流产生的衰减冲击与无法由当期流解释的残差：

```text
r_t = beta * sum_j G(j) q_{t-j} + epsilon_t,   G(j)=exp(-j/tau)
```

5m OHLCV 没有逐笔主动买卖量，因此只能用 bar 内 close location 构造一个明确、可复现的 signed-flow proxy。机制假设：在给定历史冲击传播子后，异常大的价格残差主要是做市库存/流动性失衡，随后均值回归。这里不使用 RSI、布林带或价格均线。

### 2.2 严格 bar 定义

对每根非退化 bar：

```text
clv_t = 2*(close_t-low_t)/(high_t-low_t) - 1        # [-1,1]
scale_t = median(dvol_{t-W:t-1})
q_t = clv_t * log1p(dvol_t / max(scale_t, eps))
```

每个 `t` 的 `beta_t` 仅由训练窗 `[t-W,t-1]` 拟合。先对该窗逐点按同一 `tau` 递推：

```text
x_i = exp(-1/tau)*x_{i-1} + q_i
beta_t = sum(x_i*r_i) / max(sum(x_i^2), eps)
e_i = r_i - beta_t*x_i
sigmae_t = 1.4826 * median(|e_i - median(e)|)
```

为避免窗口左边未知状态，拟合时 `x` 从0开始并丢弃前 `ceil(5*tau)` 个 burn-in 点。当前 bar：

```text
x_t = exp(-1/tau)*x_{t-1} + q_t
e_t = r_t - beta_t*x_t
z_t = e_t / max(sigmae_t, 1e-12)
```

信号要求冲击模型本身方向合理且残差不是单纯 spread/no-volume 噪声：

```text
beta_t > 0
|z_t| >= z_resid
dvol_t >= median(dvol_{t-W:t-1})
sign(e_t) == sign(r_t)
```

在 `t+1` open 入场 `s=-sign(e_t)`。固定持有 `H` bars 后 next-open 平仓。此机制与 JDAC 的关键区别：JDAC 顺着被确认的永久 jump；PIRD 逆着“扣除可解释流冲击后的瞬态残差”，不要求单 bar jump。

### 2.3 有限参数网格（36 组）

```text
W       in {2016, 4032}        # 7d / 14d
 tau    in {3, 6, 12}          # 15m / 30m / 60m 半衰形状参数（bar单位）
z_resid in {3.0, 4.0}
H       in {6, 12, 24}         # 30m / 1h / 2h
```

先固定 `H=12` 扫 `W × tau × z_resid`（12组），再只对 plateau center 扫 `H` 及其相邻 `tau`（最多24组）；总执行上限36组。`beta` 不网格化，完全由 causal OLS 得到。

### 2.4 机制可证伪预测

- 入场后 signed residual `sign(e_t)*(p_{t+h}-p_t)` 应随 `h` 从正向异常向0衰减；若继续扩大，则瞬态假设错误。
- 去掉 propagator、只对 raw return 做 z-score 的消融若不劣，传播子没有增量价值。
- `tau` 的邻域应形成平台；只有一个 `tau` 盈利视为离散过拟合。
- 多空 gross PnL 必须都为正，防止结果只是 DOGE 长期 beta。

---

## 3. VCOS：成交量时钟下的订单拆分延续 + 时段流动性扩张

### 3.1 第一性原理

subordinated diffusion 把价格过程写成 `p(t)=B(V(t))`：信息到达和方差更接近随成交量时间而非墙上时间推进。若大单被拆分执行，相邻“等成交额桶”中的方向应持续；而下一时段预期流动性扩张时，剩余订单更容易继续执行且冲击成本较低。因此本机制在**成交量时钟**上测延续，并用历史 UTC slot 季节性选择从低容量向高容量过渡的时刻。它不使用固定根数动量窗口，也不使用 coherent-path efficiency。

### 3.2 只用 5m bar 构造因果成交量时钟

在 `t` 决策时，使用此前 `D` 个完整 UTC 日（不含当日）估计：

```text
seasonal_dvol[k] = median(dvol of slot k over prior D complete days)
base_dvol = median(seasonal_dvol[0:288])
dv_i = dvol_i / max(base_dvol, eps)           # 标准化成交量时间增量
```

从 `t` 向后累加 `dv_i`，按 crossing 顺序构造最近两个不重叠桶 `B0`（最新）、`B1`（更早），每桶目标成交量时间 `Q`。边界 bar 不做分数切割：整根归入首先被 crossing 的桶；因此算法只需 bar 数据且结果唯一。任一桶超过 `max_span=72` bars（6h）仍未达到 `Q`，则无信号。

对每桶：

```text
R(B) = log(close_last / open_first)
RV(B) = sqrt(sum_{i in B} r_i^2)
jump_share(B) = max_i |r_i| / max(RV(B),eps)
```

延续事件：

```text
sign(R(B0)) == sign(R(B1)) != 0
|R(B0)|/RV(B0) >= z_vol
|R(B1)|/RV(B1) >= z_vol
max(jump_share(B0),jump_share(B1)) <= 0.75   # 排除由单跳主导，留给JDAC
```

时段容量扩张门：以入场 slot `k=(slot_t+1) mod 288` 为起点，比较未来 `H` 个 slot 与刚过去 `H` 个 slot 的历史季节性成交额：

```text
L = sum_{j=0}^{H-1} seasonal_dvol[(k+j) mod 288] /
    sum_{j=1}^{H} seasonal_dvol[(k-j) mod 288]
L >= gamma
```

满足时在 `t+1` open 沿两桶共同方向入场，持有 `H` bars，下一 open 平仓。跨 UTC 日期只按 modulo 288 处理；季节性样本仍只能来自 `t` 之前已经完整结束的日期。

### 3.3 有限参数网格（36 组）

固定：`max_span=72`，`jump_share_max=0.75`。

```text
D       in {14, 28}            # 时段季节性估计日数
Q       in {6, 12, 24}         # 每桶标准化成交量单位
z_vol   in {0.60, 0.80}
gamma   in {1.10, 1.25}
H       in {6, 12, 24}         # 30m / 1h / 2h
```

结构扫描固定 `D=28,H=12`，扫描 `Q × z_vol × gamma`（12组）；只有存在相邻 `Q/z_vol/gamma` 平台时，才对 plateau center 扫 `D × H` 及一个相邻 `Q`（最多24组），总上限36组。

### 3.4 机制可证伪预测

- 等成交额桶的 continuation 应显著强于用相同平均墙上 bars 的固定时间桶；否则 volume clock 没有增量价值。
- `gamma` 门应降低交易数但改善净每笔收益；若只改善 gross、不改善扣15bps后的 net，则容量扩张不足以覆盖成本。
- 去掉 `jump_share` 后若利润只来自少数大 jump，订单拆分解释被否定，应归入 JDAC 而非 VCOS。
- 按 entry UTC slot 报告收益；单一 slot 贡献超过总正 PnL 的35%视为时段偶然性，不通过。

---

## 4. 共用开发验证顺序（不声称 OOS）

1. **合成因果测试**：对每个机制人工构造事件，改变 `t+1` 之后的 OHLCV 不得改变 `t` 的 intent；fill 必须严格为 next-bar-open。
2. **信号数量先行**：不读收益，先确认每个结构候选至少30个完整 episodes；不足即淘汰，不放宽阈值。
3. **有限网格**：严格按每节的结构扫描→plateau center→持有扫描顺序；不得执行未列出的参数。
4. **成本核算**：主结果15bps/side；额外只做20和25bps/side压力，不以0成本结果选参。
5. **最低经济门（development gate）**：净收益>0、daily Sharpe>=0.50、MaxDD>=-20%、long和short aggregate PnL均>0、至少30 episodes。
6. **机制消融**：每个候选必须跑本节规定的核心消融；主机制若不优于朴素消融，则即使赚钱也标为 `ECONOMIC-ONLY / MECHANISM-FAIL`。
7. **稳定性**：按自然年、UTC slot、long/short、事件强度分桶报告；任何单年贡献>60%总正PnL或最佳5笔贡献>=60%总正episode PnL，标记集中度失败。
8. **研究表述**：由于历史研究池已多次查看，只能说“开发样本支持/不支持”，不能使用 OOS、forward-confirmed 或 validated。

## 5. 三机制的互斥与组合原则

- JDAC：单跳主导、确认后顺势；PIRD：扣除传播子后的异常残差、逆势；VCOS：明确排除单跳、在等成交量桶上顺势。
- 若同一 bar 多机制同时触发，本轮单机制开发分别运行，不做事后优先级优化。
- 只有各自单独通过后，才允许预先冻结组合规则；禁止根据重叠交易的已知盈亏决定谁优先。
