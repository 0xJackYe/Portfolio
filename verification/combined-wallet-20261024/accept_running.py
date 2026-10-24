"""Verify native cached APIs without persisting account amounts or credentials."""
import json
import sys
import time
from decimal import Decimal, localcontext
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from okx_wallet_service import OKXVault
from crypto_portfolio_service import BinanceVault


def main():
    opener = build_opener(ProxyHandler({}))
    samples = []
    def read(path):
        start = time.monotonic()
        with opener.open('http://127.0.0.1:8766' + path, timeout=8) as response:
            assert response.status == 200
            assert response.headers.get('Server', '').startswith('BitcoinTerminal/')
            data = json.loads(response.read())
        samples.append((time.monotonic() - start) * 1000)
        return data
    online = read('/api/wallet/okx')
    combined = read('/api/wallet/combined')
    portfolio = read('/api/wallet/portfolio')
    terminal = read('/api/terminal')
    market = read('/api/market')
    assert online['status'] == 'connected' and online['permissions']['read_only']
    assert combined['ok'] and not combined['stale']
    assert portfolio['complete'] and not portfolio['stale']
    assert portfolio['binance']['status'] == 'connected'
    assert {s['id'] for s in portfolio['sources']} == {'offline', 'okx', 'binance'}
    assert all(s['status'] == 'connected' for s in portfolio['sources'])
    with localcontext() as context:
        context.prec = 256
        assert Decimal(combined['totals']['btc']) == sum(Decimal(s['btc']) for s in combined['sources'])
        assert {s['id'] for s in combined['sources']} == {'offline', 'okx'}
        assert all(Decimal(a['usd_value']) >= 5 for a in portfolio['assets'])
        total = Decimal(portfolio['total_usd'])
        assert total == sum(Decimal(a['usd_value']) for a in portfolio['assets'])
        assert abs(sum(a['percentage'] for a in portfolio['assets']) - 100) < 1e-8
        if portfolio['location_allocation_complete']:
            assert total == sum(Decimal(a['usd_value']) for a in portfolio['locations'])
            assert abs(sum(a['percentage'] for a in portfolio['locations']) - 100) < 1e-8
    serialized = json.dumps([online, combined, portfolio, terminal, market])
    for vault in (OKXVault(), BinanceVault()):
        for credential in vault.read().values():
            assert not credential or credential not in serialized
    assert isinstance(terminal.get('settings'), dict)
    assert market.get('status') == 'SUCCESS' and market.get('stale') is False
    assert market.get('btc_contracts_total', 0) > 0 and market.get('options')
    # These APIs serve in-memory snapshots rather than waiting for exchange I/O.
    for _ in range(3):
        read('/api/wallet/combined')
        read('/api/wallet/portfolio')
    report = {
        'passed': True,
        'read_only_okx': True,
        'binance_connected': True,
        'combined_btc_exact': True,
        'all_three_portfolio_sources_connected': True,
        'all_included_coin_values_at_least_5_usd': True,
        'coin_and_location_percentages_reconcile': True,
        'no_credentials_in_public_responses': True,
        'history_points': len(combined['history']),
        'portfolio_currencies': len(portfolio['assets']),
        'cached_http_max_ms': round(max(samples), 2),
        'market_keys': sorted(market)[:15],
    }
    Path(__file__).with_name('running-acceptance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
