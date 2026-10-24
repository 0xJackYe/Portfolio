# 币安 BTC 期权官网及公开接口核验

核验日期：2026-10-13，北京时间。所有请求仅访问官方公开行情；没有读取、使用或发送任何用户凭据，没有登录，没有交易。

## 日期与合约

官网 BTCUSDT 期权页的全部 10 个日期与 `/eapi/v1/exchangeInfo` 有效 BTCUSDT 合约日期集合完全一致。接口于 2026-10-13T20:25:03+08:00 取得 676 个 `TRADING` 且尚未到期的 BTC 合约。到期时间均为当天北京时间 16:00。

| 到期日期 | 北京时间 | BTC Call + Put 合约数 | 官网日期标签 |
|---|---|---:|---|
| 2026-10-14 | 16:00 | 46 | 一致 |
| 2026-10-15 | 16:00 | 48 | 一致 |
| 2026-10-16 | 16:00 | 50 | 一致 |
| 2026-10-23 | 16:00 | 50 | 一致 |
| 2026-10-30 | 16:00 | 102 | 一致 |
| 2026-11-27 | 16:00 | 86 | 一致 |
| 2026-12-25 | 16:00 | 90 | 一致 |
| 2027-03-26 | 16:00 | 76 | 一致 |
| 2027-06-25 | 16:00 | 84 | 一致 |
| 2027-09-24 | 16:00 | 44 | 一致 |

官网入口：[Binance BTCUSDT Options](https://www.binance.com/en/eoptions/BTCUSDT)。合约名单直接取自官方实时 `exchangeInfo`，并非猜测每天应有哪些到期日。

## 行情抽样

买价指买一，卖价指卖一；标记价与最近成交价是不同字段。下表 IV 顺序为买 IV / 标记 IV / 卖 IV，API 小数乘 100 后以百分比显示。

| 合约 | 来源 / 采样北京时间 | 买一 | 标记价 | 卖一 | IV（买 / 标记 / 卖） |
|---|---|---:|---:|---:|---|
| BTC-261014-83500-P | API 20:29:30 | 485 | 491.2 | 500 | 27.703702% / 28.100000% / 28.662264% |
| BTC-261014-83500-P | 官网 20:29:40.668 | 480 | 485.83 | 495 | 27.72% / 28.10% / 28.68% |
| BTC-261127-64000-P | API 20:25:27 | 320 | 315.961 | 325 | 49.535334% / 49.400000% / 49.701750% |
| BTC-261127-64000-P | 官网 20:25:39.366 | 320 | 315.896 | 325 | 49.53% / 49.40% / 49.70% |

2026-11-27、64,000 Put 的买一 320、卖一 325 与官网完全相同；标记 IV 49.40% 和卖 IV 49.70% 在两位小数显示下相同。API 买 IV 0.49535334 等于 49.535334%，常规四舍五入两位为 49.54%，与官网 49.53% 相差 0.01 个百分点。采样间隔约 12 秒，可能存在 IV 变动或官网截断显示差异，不能据此断言买 IV 完全匹配。其标记价相差 0.065 USDT。近到期的 83,500 Put 在约 10 秒间隔内买卖报价各变动 5 USDT，标记 IV 均为 28.10%。这次读取验证了合约与字段口径，不能证明跨采样时刻逐值完全相等，更不能保证两个网页在任意毫秒都一样。

官网截图：[2026-10-14](binance_official_20261014.jpg)、[2026-11-27](binance_official_20261127.jpg)。原始官网列顺序和 API 响应见同目录 JSON，保留了各自采样时间。

## REST 访问限制

本次实时 `exchangeInfo.rateLimits`：`REQUEST_WEIGHT` 400 / 1 分钟；`ORDERS` 100 / 1 分钟及 30 / 10 秒。这里只展示行情，因此下单配额不参与使用。400 是当前实测值；文档 JSON 示例的 2400 不应作为当前额度。

| GET 接口 | 官方 IP 权重 |
|---|---:|
| `/eapi/v1/exchangeInfo` | 1 |
| `/eapi/v1/time` | 1 |
| `/eapi/v1/index` | 1 |
| `/eapi/v1/mark` | 5 |
| `/eapi/v1/ticker?symbol=…` | 1 |
| `/eapi/v1/ticker`（全部合约） | 40 |
| `/eapi/v1/depth`，limit 5/10/20/50 | 1 |

次数并非固定的每分钟 400 次：不同接口耗费不同权重。额度按公网 IP 累计，并非按 API Key 分开；同 IP 的其他程序会共享。全量 ticker 单独最多约 10 次/分钟，实际还需给其他接口留额度。上述 time + exchangeInfo + index + mark + 全量 ticker 每组 48 权重；每秒轮询约 2880 权重/分钟，会超过实测配额。响应提供 `X-MBX-USED-WEIGHT-*`；触发 429 应退避，持续违规可能导致 418 IP 封禁。

[官方 Options 通用说明](https://developers.binance.com/en/docs/products/derivatives-trading-options/general-info)；[官方 Options 行情接口及权重](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/market-data)。

## WebSocket

官方当前 Options 流：`/public` 上的单合约 `@bookTicker` 按买卖一变化实时推送；`@optionTicker` 每 1000ms 推送有变化的成交统计。`/market` 上的 `btcusdt@optionMarkPrice` 每 1000ms 推送标记价、买卖价、IV、Greeks；`!index@arr` 每 1000ms 推送指数；Open Interest 每 60 秒。因此“实时”应表示按官方推送到达更新，不意味着所有字段每毫秒刷新。

Options Connect 文档写明：最多 200 streams / 连接；客户端发往服务器最多 10 incoming messages / 秒；单连接 24 小时后断开；服务端每 5 分钟 ping，15 分钟没有 pong 时断开。10 / 秒指客户端控制消息，不能误解为服务器行情每秒最多 10 条。需要自动重连和保活。

[Options Connect 及限制](https://developers.binance.com/en/docs/products/derivatives-trading-options/websocket-market-streams/Connect)；[Options Public 流](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/ws-streams/public)；[Options Market 流](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/ws-streams/market)。

用户之前给出的字符串是否有效、是否启用指定权限、是否受账户 IP 白名单限制，本次没有验证，也无需借助它读取这些公开行情。
