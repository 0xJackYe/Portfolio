# BTC 期权到期盈亏模拟公式核验

核验日期：2026-10-14（北京时间）。只读访问币安公开文档；未访问账户、未使用凭据、未下单。功能范围限定 BTC 且 `unit = 1`；其他合约乘数不在本次模拟范围。

## 报价方向

买入 Call / Put 使用卖一 `ask`；卖出开仓 Call / Put 使用买一 `bid`。官方 BBO 说明明确：买单对应盘口最低卖价，卖单对应盘口最高买价。报价只是模拟的入场假设，不能保证该数量全部成交，也不包含滑点。[币安 Options 交易说明，第 3.4 节](https://www.binance.com/en-AE/support/faq/detail/6b0dc23370ee4153a6581355e92555c1)

“卖出”在下列公式中指假设新建空头持仓，不是卖出已有多头的平仓损益；平仓需要原始买入成本，而本功能不读取账户成本。

## 变量与数量

- `S`：假设到期 BTC 结算价，单位 USDT/BTC，且 `S >= 0`。
- `K`：行权价，单位 USDT/BTC。
- `pAsk`、`pBid`：模拟入场权利金；本模型明确定义为 USDT/BTC。
- `q`：模拟合约数量，取正数。
- `u`：`exchangeInfo.unit`；当前 BTC 为 1 BTC/张。
- `Q = q * u`：对应的 BTC 数量。当前 BTC `u = 1`，因此 `Q = q`。
- 总支付 / 收取权利金：`pAsk * Q` / `pBid * Q`，单位 USDT。

2026-01-05 版官方合约规范第 14 条明确 BTC 合约单位为 1。API 也将 `unit` 定义为每张合约代表的标的数量。由于当前范围只支持 BTC，按每 BTC 定义权利金与其每张合约报价在数值上相同；不能把这一口径未经核实推广到 `unit != 1` 的其他标的。[官方合约规范，第 14 条](https://bin.bnbstatic.com/static/cms/cg08ou2ak0tn7mcplvfg/file/443bcc67fde7274898ff8e3f7af23c7d89e654c5e609d250772e0ddaa96409be.pdf)；[Options API `exchangeInfo`](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/market-data)

这里的 `S` 应在图表和输入框中标为“到期 BTC 结算价”。币安解释的结算价为到期前 30 分钟现货指数均价，不能等同于到期某一秒的现货价格。[官方期权基础说明，第 3 节](https://www.binance.com/en/support/faq/detail/acc50814eb0f4beba3799643d8b7a0d4)

## 四个方向的精确公式

先定义每 BTC 到期内在价值：

```text
CallValue(S) = max(S - K, 0)
PutValue(S)  = max(K - S, 0)
```

以下 `PnL` 包含入场权利金，不含费用，是持有到期时的 USDT 总损益。四个方向是对官方买方到期内在价值公式与买卖现金流的数学推导：卖方收取权利金并承担内在价值支出。[官方基础说明，第 8、9 节](https://www.binance.com/en/support/faq/detail/acc50814eb0f4beba3799643d8b7a0d4)；[官方卖空说明](https://www.binance.com/en/support/faq/detail/1ceb77f837344e3085ecf98d9a6a8097)

| 方向 | PnL（USDT） | 盈亏平衡结算价（忽略费用） |
|---|---|---|
| 买入 Call | `(max(S - K, 0) - pAsk) * Q` | `K + pAsk` |
| 卖出 Call | `(pBid - max(S - K, 0)) * Q` | `K + pBid` |
| 买入 Put | `(max(K - S, 0) - pAsk) * Q` | `K - pAsk` |
| 卖出 Put | `(pBid - max(K - S, 0)) * Q` | `K - pBid` |

必须使用 `max(..., 0)`；否则价外期权可能错误地产生超过买入权利金的到期亏损。Put 盈亏平衡价若小于 0，则在允许的 `S >= 0` 范围内不存在该盈亏平衡点。

### 最大到期损益

下列界限由上述公式在 `S >= 0` 上直接推导，均不含费用：

| 方向 | 最小 PnL | 最大 PnL |
|---|---|---|
| 买入 Call | `-pAsk * Q` | 无上限 |
| 卖出 Call | 无下限，理论亏损无限 | `pBid * Q` |
| 买入 Put | `-pAsk * Q` | `(K - pAsk) * Q` |
| 卖出 Put | `(pBid - K) * Q`（`S = 0`） | `pBid * Q` |

如果 UI 使用正数的“最大亏损”而非“最小 PnL”：买方为 `pAsk * Q`；卖出 Call 为无限；卖出 Put 为 `max(K - pBid, 0) * Q`。显示有限范围曲线时，卖出 Call 的“最大亏损”不能取可见图表端点代替理论无限值。

### 交叉验证例子

设 `K = 80000`、`pAsk = 500`、`pBid = 480`、`q = 0.1`、`u = 1`：

| 到期结算价 | 买入 Call | 卖出 Call | 买入 Put | 卖出 Put |
|---:|---:|---:|---:|---:|
| 75000 | -50 | +48 | +450 | -452 |
| 80000 | -50 | +48 | -50 | +48 |
| 85000 | +450 | -452 | -50 | +48 |

买卖两条损益相加为 `(pBid - pAsk) * Q = -2 USDT`，反映入场买卖价差；只在假设同一权利金时才会互为相反数。

## 模拟假设与费用

默认排除交易手续费、行权手续费、滑点、融资成本及到期前强平，假设仓位能够持有到期。官方 PnL Calculator FAQ 也明确其示例不包含费用。[官方计算器 FAQ](https://www.binance.com/en-AE/support/faq/detail/20fd69a9873a47f3bc86caee702f1dd1)

真实卖方还需要保证金，并存在到期前强平风险；这张到期损益图不能视为保证金需求或强平价计算器。[官方卖空说明](https://www.binance.com/en/support/faq/detail/1ceb77f837344e3085ecf98d9a6a8097)

如果后来增加费用，净损益应为 `PnL - openingFee - exerciseFee(S) - otherCosts`，而非把权利金误当成收益；行权费用可能随结算价变化，不能随意用固定费用移动盈亏平衡点。官方费用页区分交易、行权和强平费；具体账户费率与适用费率表可能不同，本次不读取账户，也不硬编码账户实际费率。[官方 Options 费用说明](https://www.binance.com/en-AE/support/faq/detail/5326e5de61c34fed98abe28d2f175a23)

当 live bid / ask 缺失或为 0 时，应明确显示该方向暂无有效盘口报价，不能静默把它当作可成交的零成本权利金。若支持手动输入，应区分“手动模拟权利金”和“当前盘口价”。
