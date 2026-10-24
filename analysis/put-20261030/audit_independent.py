"""Independent quadrature verification; does not import the analysis implementation."""
import json
import math
from pathlib import Path
from statistics import NormalDist, stdev

from scipy.integrate import quad
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parent
N = NormalDist()
snap = json.loads((ROOT / "snapshot.json").read_text(encoding="utf-8"))
result = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
history = json.loads((ROOT / "realized_vol.json").read_text(encoding="utf-8"))
daily = json.loads((ROOT / "spot_daily.json").read_text(encoding="utf-8"))
S = result["metadata"]["spot_index"]
q = 0.01
options = {r["symbol"]: r for r in snap["options"]}
checks = 0
max_error = {}


def check(key, actual, stored, tolerance=1e-7):
    global checks
    error = abs(actual - stored)
    max_error[key] = max(error, max_error.get(key, 0.0))
    assert error <= tolerance, (key, actual, stored, error)
    checks += 1


def phi(z):
    return math.exp(-z*z/2) / math.sqrt(2*math.pi)


def fee(x, k):
    if x >= k:
        return 0.0
    return min(0.00015*x, 0.10*(k-x))


def integrate(function, breakpoints, upper=12.0):
    bounds = [-12.0] + sorted(set(x for x in breakpoints if -12.0 < x < upper)) + [upper]
    return sum(quad(function, a, b, epsabs=1e-10, epsrel=2e-11)[0]
               for a, b in zip(bounds, bounds[1:]))


detail = []
for row in result["rows"]:
    k, p = row["strike"], row["bid"]
    credit = p - min(0.00024*S, 0.10*p)
    years = (options[row["symbol"]]["expiry_ms"] - snap["server_now_ms"]) / (365*86400000)
    be = brentq(lambda x: credit - max(k-x, 0) - fee(x, k), 0, k, xtol=1e-8)
    check("breakeven", be, row["breakeven_with_fees"])
    check("max_profit", q*credit, row["net_max_profit_0_01"])
    check("max_loss", q*(k-credit), row["max_loss_0_01"])
    for sigma in (0.4, 0.6, 0.8):
        v = sigma*math.sqrt(years)
        m = math.log(S) - sigma*sigma*years/2
        x = lambda z: math.exp(m+v*z)
        zstrike = (math.log(k)-m)/v
        zcross = (math.log(k*0.1/0.10015)-m)/v
        zbe = (math.log(be)-m)/v
        breaks = [zstrike, zcross, zbe]
        payout = q*integrate(lambda z: max(k-x(z), 0)*phi(z), breaks)
        exercise = q*integrate(lambda z: fee(x(z), k)*phi(z), breaks)
        ev = q*credit - payout - exercise
        prefix = "sigma%d_" % round(100*sigma)
        check("expected_payout", payout, row[prefix+"expected_payout"])
        check("expected_fee", exercise, row[prefix+"expected_exercise_fee"])
        check("ev", ev, row[prefix+"ev"])
        check("loss_probability", N.cdf(zbe), row[prefix+"loss_probability"])
        for alpha, label in ((0.05, "95"), (0.01, "99")):
            ztail = N.inv_cdf(alpha)
            var = q*max(max(k-x(ztail), 0)+fee(x(ztail), k)-credit, 0)
            es = q*integrate(lambda z: max(max(k-x(z), 0)+fee(x(z), k)-credit, 0)*phi(z),
                            breaks, ztail)/alpha
            check("positive_loss_var", var, row[prefix+"var"+label])
            check("positive_loss_es", es, row[prefix+"es"+label])
        if k in (60000, 64000, 70000):
            detail.append({"strike": k, "sigma": sigma, "ev": ev,
                           "expected_exercise_fee": exercise, "breakeven": be})

closes = [float(c[4]) for c in daily["klines"]]
returns = [closes[i]/closes[i-16]-1 for i in range(16, len(closes))][-365:]
stored_returns = history["sixteen_day_returns_latest_365_windows"]
if isinstance(stored_returns[0], dict):
    stored_returns = [r["simple_return"] for r in stored_returns]
assert len(returns) == len(stored_returns) == 365
for actual, stored in zip(returns, stored_returns):
    check("historical16d_return", actual, stored)
for days in (30, 60, 90, 180, 365):
    logs = [math.log(closes[i]/closes[i-1]) for i in range(1, len(closes))][-days:]
    check("realized_volatility", stdev(logs)*math.sqrt(365),
          history["annualized_realized_volatility"][str(days)])
for row in result["rows"]:
    k, p = row["strike"], row["bid"]
    credit = p - min(0.00024*S, 0.10*p)
    pnl = [q*(credit-max(k-S*(1+r), 0)-fee(S*(1+r), k)) for r in returns]
    check("historical_ev", sum(pnl)/len(pnl), row["historical16d_recent365_ev"])

report = {"status": "all passed", "checks": checks, "contracts": len(result["rows"]),
          "quadrature": "Independent scipy quad over normal z in [-12,12], split at strike, fee crossover and breakeven; no imports from analysis implementation.",
          "max_absolute_error": max_error, "candidates": detail,
          "method_note": "Stored ES/VaR use nonnegative loss (profit clamped to zero), not signed-loss ES. This matters when loss probability is smaller than the tail fraction. Same standard ES if the full worst tail loses."}
(ROOT / "independent-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
