"""Read-only live acceptance; private input snapshots remain DPAPI encrypted."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from btc_terminal_server import WalletProxy, wallet_address
from combined_wallet_service import AddressSnapshots, adapt_view, iso
from combined_wallet_engine import build_combined
from okx_wallet_service import OKXWalletService


def main():
    online_service = OKXWalletService()
    if not online_service.refresh_once():
        print(json.dumps({'live_okx': False, 'error_code': online_service.read_public().get('error_code')}))
        return 1
    online = online_service.read_public()
    source = AddressSnapshots(WalletProxy(wallet_address()))
    source.refresh()
    now_ms = int(time.time() * 1000)
    ledger = online_service.client_factory(dict(online_service.credentials)).read_btc_history(now_ms - 90*86400000, now_ms)
    # The ledger's closing balances are at its reported coverage end.
    historical = json.loads(json.dumps(online))
    from decimal import Decimal, localcontext
    with localcontext() as context:
        context.prec = 256
        total = sum((Decimal(ledger['closing_balances'][k]) for k in ('trading','funding')), Decimal(0))
    historical['summary']['btc_holdings_total'] = format(total, 'f')
    historical['last_success_at'] = iso(ledger['coverage_end_ms'])
    result = build_combined(source.snapshot, historical, ledger, now_ms=now_ms)
    with online_service.vault.lock:
        online_service.vault._write('combined-live-inputs.protected.json', {'onchain':source.snapshot,'okx':online,'historical_okx':historical,'ledger':ledger})
    report = {'live_okx':True,'read_only_verified':online['permissions']['verified'] and online['permissions']['read_only'],
              'ledger_complete':ledger['complete'],'ledger_reason':ledger.get('reason'),
              'ledger_events':len(ledger['events']),'history_points':len(result['history']),
              'coverage':result['coverage'],'totals':result['current'],
              'pnl':{k:{'usd':v['value_usd'],'cny':v['value_cny'],'reason':v['reason']} for k,v in result['pnl'].items()}}
    # Keep exact user holdings in the private vault; public acceptance artifact
    # records only scope, counts and success, not amounts or bill identifiers.
    safe={k:v for k,v in report.items() if k not in ('totals','pnl')}
    Path(__file__).with_name('live-result.json').write_text(json.dumps(safe,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
