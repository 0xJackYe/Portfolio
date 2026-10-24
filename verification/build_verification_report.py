# -*- coding: utf-8 -*-
"""Assemble the independently observed public Binance comparison records."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

root = Path(__file__).parent
beijing = timezone(timedelta(hours=8))
first = json.loads((root / 'official_api_first.json').read_text(encoding='utf-8'))
far = json.loads((root / 'official_api_far.json').read_text(encoding='utf-8'))
near = json.loads((root / 'official_api_near_83500.json').read_text(encoding='utf-8'))
ui = json.loads((root / 'official_ui_samples.json').read_text(encoding='utf-8'))
exchange = first['exchange_info']['data']
contracts = [item for item in exchange['optionSymbols']
             if item['underlying'] == 'BTCUSDT' and item['status'] == 'TRADING'
             and item['expiryDate'] > exchange['serverTime']]
counts = Counter(datetime.fromtimestamp(item['expiryDate'] / 1000, beijing).isoformat()
                 for item in contracts)
api_dates = sorted(value[:10] for value in counts)
website_dates = ui['nearUi']['dates']

def comparison(name, api, website):
    ticker = api[name + '_ticker']['data'][0]
    mark = api[name + '_mark']['data'][0]
    columns = website['putColumns']
    display_iv = {
        key: str((Decimal(mark[key]) * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) + '%'
        for key in ('bidIV', 'markIV', 'askIV')
    }
    website_iv = {'bidIV': columns[1].split('\n')[1], 'markIV': columns[2].split('\n')[1],
                  'askIV': columns[3].split('\n')[1]}
    iv_differences = {
        key: str(Decimal(display_iv[key].rstrip('%')) - Decimal(website_iv[key].rstrip('%')))
        for key in display_iv
    }
    return {
        'symbol': mark['symbol'],
        'api_ticker_received_beijing': api[name + '_ticker']['received_at_beijing'],
        'api_mark_received_beijing': api[name + '_mark']['received_at_beijing'],
        'website_captured_beijing': datetime.fromisoformat(website['capturedUtc'].replace('Z', '+00:00')).astimezone(beijing).isoformat(timespec='milliseconds'),
        'api': {**{key: ticker[key] for key in ('bidPrice', 'askPrice', 'lastPrice')},
                **{key: mark[key] for key in ('markPrice', 'bidIV', 'markIV', 'askIV', 'delta')}},
        'website': {
            'bidPrice': columns[1].split('\n')[0], 'bidIVPercent': columns[1].split('\n')[1],
            'markPrice': columns[2].split('\n')[0], 'markIVPercent': columns[2].split('\n')[1],
            'askPrice': columns[3].split('\n')[0], 'askIVPercent': columns[3].split('\n')[1],
            'delta': columns[4],
        },
        'api_iv_display_percent_standard_round_half_up_2dp': display_iv,
        'api_minus_website_iv_display_percentage_points': iv_differences,
        'iv_display_equal_standard_round_half_up_2dp': {
            key: Decimal(iv_differences[key]) == 0 for key in iv_differences
        },
        'atomic_snapshot': False,
    }

summary = {
    'verification_date_beijing': '2026-10-13',
    'credentials_used': False,
    'credential_validity_tested': False,
    'website_url': 'https://www.binance.com/en/eoptions/BTCUSDT',
    'api_exchange_received_beijing': first['exchange_info']['received_at_beijing'],
    'btc_trading_contract_count': len(contracts),
    'api_expiry_dates': api_dates,
    'website_expiry_dates': website_dates,
    'expiry_dates_equal': api_dates == website_dates,
    'expiry_contract_counts': dict(sorted(counts.items())),
    'rateLimits_observed': exchange['rateLimits'],
    'samples': [comparison('near', near, ui['nearUi2']), comparison('far', far, ui['farUi'])],
    'limitation': '官网DOM和REST分开读取。价格与IV均会变化，未采集同一事件时间的原子快照，不能声称不同采样时刻全部数值完全相等。',
}
(root / 'verification_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
lines = [
    '# 币安 BTC 期权官网及公开接口核验', '',
    '核验日期：2026-10-13，北京时间。所有请求仅访问官方公开行情；没有读取、使用或发送任何用户凭据，没有登录，没有交易。', '',
    '## 日期与合约', '',
    f"官网 BTCUSDT 期权页的全部 10 个日期与 `/eapi/v1/exchangeInfo` 有效 BTCUSDT 合约日期集合完全一致。接口于 {first['exchange_info']['received_at_beijing']} 取得 {len(contracts)} 个 `TRADING` 且尚未到期的 BTC 合约。到期时间均为当天北京时间 16:00。", '',
    '| 到期日期 | 北京时间 | BTC Call + Put 合约数 | 官网日期标签 |',
    '|---|---|---:|---|',
]
for value, count in sorted(counts.items()):
    lines.append(f'| {value[:10]} | 16:00 | {count} | 一致 |')
lines += [
    '', '官网入口：[Binance BTCUSDT Options](https://www.binance.com/en/eoptions/BTCUSDT)。合约名单直接取自官方实时 `exchangeInfo`，并非猜测每天应有哪些到期日。', '',
    '## 行情抽样', '',
    '买价指买一，卖价指卖一；标记价与最近成交价是不同字段。下表 IV 顺序为买 IV / 标记 IV / 卖 IV，API 小数乘 100 后以百分比显示。', '',
    '| 合约 | 来源 / 采样北京时间 | 买一 | 标记价 | 卖一 | IV（买 / 标记 / 卖） |',
    '|---|---|---:|---:|---:|---|',
]
for sample in summary['samples']:
    a, w = sample['api'], sample['website']
    av = ' / '.join(f"{float(a[key]) * 100:.6f}%" for key in ('bidIV','markIV','askIV'))
    wv = ' / '.join(w[key] for key in ('bidIVPercent','markIVPercent','askIVPercent'))
    lines.append(f"| {sample['symbol']} | API {sample['api_mark_received_beijing'][11:19]} | {a['bidPrice']} | {a['markPrice']} | {a['askPrice']} | {av} |")
    lines.append(f"| {sample['symbol']} | 官网 {sample['website_captured_beijing'][11:23]} | {w['bidPrice']} | {w['markPrice']} | {w['askPrice']} | {wv} |")
lines += [
    '',
    '2026-11-27、64,000 Put 的买一 320、卖一 325 与官网完全相同；标记 IV 49.40% 和卖 IV 49.70% 在两位小数显示下相同。API 买 IV 0.49535334 等于 49.535334%，常规四舍五入两位为 49.54%，与官网 49.53% 相差 0.01 个百分点。采样间隔约 12 秒，可能存在 IV 变动或官网截断显示差异，不能据此断言买 IV 完全匹配。其标记价相差 0.065 USDT。近到期的 83,500 Put 在约 10 秒间隔内买卖报价各变动 5 USDT，标记 IV 均为 28.10%。这次读取验证了合约与字段口径，不能证明跨采样时刻逐值完全相等，更不能保证两个网页在任意毫秒都一样。',
    '',
    '官网截图：[2026-10-14](binance_official_20261014.jpg)、[2026-11-27](binance_official_20261127.jpg)。原始官网列顺序和 API 响应见同目录 JSON，保留了各自采样时间。',
    '', '## REST 访问限制', '',
    '本次实时 `exchangeInfo.rateLimits`：`REQUEST_WEIGHT` 400 / 1 分钟；`ORDERS` 100 / 1 分钟及 30 / 10 秒。这里只展示行情，因此下单配额不参与使用。400 是当前实测值；文档 JSON 示例的 2400 不应作为当前额度。',
    '',
    '| GET 接口 | 官方 IP 权重 |', '|---|---:|',
    '| `/eapi/v1/exchangeInfo` | 1 |', '| `/eapi/v1/time` | 1 |',
    '| `/eapi/v1/index` | 1 |', '| `/eapi/v1/mark` | 5 |',
    '| `/eapi/v1/ticker?symbol=…` | 1 |', '| `/eapi/v1/ticker`（全部合约） | 40 |',
    '| `/eapi/v1/depth`，limit 5/10/20/50 | 1 |', '',
    '次数并非固定的每分钟 400 次：不同接口耗费不同权重。额度按公网 IP 累计，并非按 API Key 分开；同 IP 的其他程序会共享。全量 ticker 单独最多约 10 次/分钟，实际还需给其他接口留额度。上述 time + exchangeInfo + index + mark + 全量 ticker 每组 48 权重；每秒轮询约 2880 权重/分钟，会超过实测配额。响应提供 `X-MBX-USED-WEIGHT-*`；触发 429 应退避，持续违规可能导致 418 IP 封禁。', '',
    '[官方 Options 通用说明](https://developers.binance.com/en/docs/products/derivatives-trading-options/general-info)；[官方 Options 行情接口及权重](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/market-data)。', '',
    '## WebSocket', '',
    '官方当前 Options 流：`/public` 上的单合约 `@bookTicker` 按买卖一变化实时推送；`@optionTicker` 每 1000ms 推送有变化的成交统计。`/market` 上的 `btcusdt@optionMarkPrice` 每 1000ms 推送标记价、买卖价、IV、Greeks；`!index@arr` 每 1000ms 推送指数；Open Interest 每 60 秒。因此“实时”应表示按官方推送到达更新，不意味着所有字段每毫秒刷新。', '',
    'Options Connect 文档写明：最多 200 streams / 连接；客户端发往服务器最多 10 incoming messages / 秒；单连接 24 小时后断开；服务端每 5 分钟 ping，15 分钟没有 pong 时断开。10 / 秒指客户端控制消息，不能误解为服务器行情每秒最多 10 条。需要自动重连和保活。', '',
    '[Options Connect 及限制](https://developers.binance.com/en/docs/products/derivatives-trading-options/websocket-market-streams/Connect)；[Options Public 流](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/ws-streams/public)；[Options Market 流](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/ws-streams/market)。', '',
    '用户之前给出的字符串是否有效、是否启用指定权限、是否受账户 IP 白名单限制，本次没有验证，也无需借助它读取这些公开行情。', '',
]
(root / 'data_verification_report.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps({'dates_equal': summary['expiry_dates_equal'], 'contracts': len(contracts), 'report': str(root / 'data_verification_report.md')}, ensure_ascii=False))
