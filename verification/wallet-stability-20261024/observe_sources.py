"""Short native read-only soak test; no balances or credentials in its report."""
import datetime as dt
import json
from pathlib import Path
import time
from urllib.request import build_opener, ProxyHandler


def main():
    opener = build_opener(ProxyHandler({}))
    samples = []
    for index in range(12):
        with opener.open('http://127.0.0.1:8766/api/wallet/portfolio', timeout=5) as response:
            portfolio = json.loads(response.read())
        with opener.open('http://127.0.0.1:8766/api/wallet/okx', timeout=5) as response:
            okx = json.loads(response.read())
        samples.append({
            'at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'sources': {s['id']: s['status'] for s in portfolio['sources']},
            'complete': portfolio['complete'], 'stale': portfolio['stale'],
            'okx_status': okx['status'], 'okx_success_at': okx['last_success_at'],
            'binance_success_at': portfolio['binance'].get('last_success_at'),
            'shared_valuation_available': bool(okx.get('cash_valuation')),
        })
        if index < 11:
            time.sleep(5)
    passed = all(row['complete'] and not row['stale']
                 and set(row['sources']) == {'okx', 'binance', 'offline'}
                 and all(value == 'connected' for value in row['sources'].values())
                 and row['okx_status'] == 'connected' and row['shared_valuation_available']
                 for row in samples)
    versions = len({row['okx_success_at'] for row in samples})
    result = {'passed': passed and versions >= 2, 'observations': len(samples),
              'distinct_okx_successes': versions, 'samples': samples,
              'scope': '55-second native cached-API observation, not an external uptime guarantee.'}
    Path(__file__).with_name('source-stability-acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'samples'}), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
