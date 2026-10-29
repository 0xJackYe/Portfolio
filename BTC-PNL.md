# 比特币长期持仓成本与浮盈

本机只读接口：`GET /api/wallet/btc-pnl`。`GET /api/wallet/combined` 包含同一结果的 `lifetime_pnl` 字段。计算长期持仓的平均买入价、现价、浮盈及收益率。

后台每 20 秒核算，页面每 30 秒刷新，服务随原比特币终端启动。每天的新定投成交同步到成本账本后自动计入，无需手动登记或每日执行命令。HTTP 请求只读缓存，不同步调用交易所。

## 计算方式

从首笔买入开始，按时间读取账户绑定的已核验完整账本：

- 买入：净到账 BTC 加入数量，实际支付金额加入成本；成交费和返佣已包含，不重复扣除。
- 历史卖出：仅按卖出前移动加权平均成本减少剩余数量和账面成本；卖出回款不参与当前浮盈。
- 后续定投：按同样方式持续加入新的实际数量和成本。

```text
持仓平均买入价 = 剩余持仓成本 / 实际 BTC 总持有
当前浮盈 = 实际 BTC 总持有 × BTC/USDT 现价 − 剩余持仓成本
收益率 = 当前浮盈 / 剩余持仓成本 × 100%
```

`metrics.average_cost`、`price_usdt`、`unrealized_net`、`unrealized_return_pct` 对应四项主指标，`remaining_cost` 为剩余成本。成本为零时收益率为 `null`。

`first_buy_at` / `last_buy_at` 为首笔及最新净买入时间；`first_net_buy_price` / `last_net_buy_price` 为实际支出除以净到账数量的含费有效单价。`buy_count` 为买入成交笔数，拆分成交分别计数。

## 计价及范围

金额以 USDT 计价，使用十进制字符串。ETH、USDC 支付按成交当分钟 OKX/USDT 完整收盘价折算。历史汇率缺失时不当作零，保留带过期标记的上次结果。

Received 等转入的成本处理需在本机核对后按账户配置；未补齐原始取得成本时，相关结果属于估算。Earn、历史 BTC 合约现金净变动、提币费用和矿工费用作为期末实际数量相对现货账本数量的调整，不重复加减。范围为原面板的欧易 BTC 净持有及指定离线钱包。

用户口径存放于账户绑定的 DPAPI 加密文件。账户切换清空旧账户缓存；新账户历史未核对时返回不可用。新增无法解释的 BTC 数量变动会标记待核对。行情或余额超时显示缓存。

OKX 行情只调用固定公共 GET 接口。主链上数据源不可用时，用 Blockstream 固定地址接口独立核对已确认数量。API 密钥不会发往公共行情或链上服务。

## 验证

```text
python -m unittest test_btc_pnl_service test_btc_cost_tracker test_btc_cost_http test_btc_terminal_server test_combined_wallet_service -q
node test_combined_wallet_ui.js
```

本机核对快照保存在忽略的 `verification/` 目录。测试包括费用、历史跨币种折算、卖出回款不影响浮盈、新定投自动更新平均成本与最后买入时间、账户隔离、异常缓存及零成本收益率。
