"""Loopback-only browser QA fixture. Synthetic quotes; no Binance/account calls."""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sell_put_fixture_server as base


class SellerFixture(base.FakeCache):
    def _snapshot_locked(self):
        snapshot = super()._snapshot_locked()
        now = int(time.time() * 1000)
        rows = []
        for side, strikes in (("PUT", [61500, 62000, 63000, 64000, 65000]),
                              ("CALL", [98000, 99000, 100000, 101000])):
            for i, strike in enumerate(strikes):
                row = base.option_row(now, self._expiry_ms, strike, side=side)
                premium = 25 + (i if side == "PUT" else 4 - i) * 20
                row.update(bid_price=str(premium), ask_price=str(premium + 5),
                           mark_price=str(premium), delta="-0.05" if side == "PUT" else "0.05")
                rows.append(row)
        rows.append(base.option_row(now, self._expiry_ms, 62500, case="stale_mark"))
        rows.append(base.option_row(now, self._expiry_ms, 63500, case="insufficient_bid_depth"))
        snapshot.update(options=rows, instance_id="seller-simple-synthetic-qa",
                        fixture_label="模拟数据验收 · 非实时行情")
        return snapshot


if __name__ == "__main__":
    cache = SellerFixture()
    server = base.DashboardServer(("127.0.0.1", 8769), cache,
                                  static_dir=base.ROOT / "dashboard" / "dist")
    server.RequestHandlerClass = base.FixtureHandler
    print("Synthetic seller UI QA: http://127.0.0.1:8769/", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        cache.stop()
        server.server_close()
