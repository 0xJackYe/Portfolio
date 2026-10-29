/* Expiry payoff of one USDT-settled BTC option, held to expiry.
 *
 * An option is {side: "CALL"|"PUT", direction: "BUY"|"SELL", strike, premium, quantity, unit}
 * where premium is USDT per 1 BTC (as Binance quotes it), quantity is contracts and
 * unit is BTC per contract (1 for Binance BTC options). Amounts returned are USDT.
 * Pure math: no network, no orders.
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Payoff = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const positive = (value) => typeof value === "number" && Number.isFinite(value) && value > 0;

  function valid(option) {
    return !!option && (option.side === "CALL" || option.side === "PUT") &&
      (option.direction === "BUY" || option.direction === "SELL") &&
      positive(option.strike) && positive(option.premium) && positive(option.quantity) &&
      (option.unit === undefined || positive(option.unit));
  }

  const size = (option) => option.quantity * (option.unit || 1);

  /** Net profit (+) or loss (−) if BTC settles at `settlement`. */
  function pnl(option, settlement) {
    const intrinsic = Math.max(option.side === "CALL" ? settlement - option.strike : option.strike - settlement, 0);
    const value = (intrinsic - option.premium) * size(option) * (option.direction === "BUY" ? 1 : -1);
    return value === 0 ? 0 : value; // no −0
  }

  /** Totals over every settlement price ≥ 0. Infinity means unlimited. */
  function metrics(option) {
    const amount = size(option);
    const premium = option.premium * amount;
    const call = option.side === "CALL";
    const buy = option.direction === "BUY";
    const breakeven = call ? option.strike + option.premium : option.strike - option.premium;
    const putAtZero = Math.max(0, (option.strike - option.premium) * amount); // a put's net value if BTC goes to 0
    return {
      premium,
      breakeven: breakeven > 0 ? breakeven : null,
      maxProfit: call ? (buy ? Infinity : premium) : (buy ? putAtZero : premium),
      maxLoss: call ? (buy ? premium : Infinity) : (buy ? premium : putAtZero),
    };
  }

  /** Premium spread evenly over the days left, in USDT per day. */
  function perDay(option, days) {
    return option.premium * size(option) / days;
  }

  /** Simple annualized premium yield of a sale on the cash it ties up: the strike for a put, BTC for a call. */
  function annualized(option, days, index) {
    return option.premium / (option.side === "PUT" ? option.strike : index) * 365 / days;
  }

  // Standard normal CDF (Abramowitz & Stegun 7.1.26, error < 1.5e-7).
  function normal(x) {
    const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2);
    const erf = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x / 2);
    return x >= 0 ? (1 + erf) / 2 : (1 - erf) / 2;
  }

  /** Chance the trade ends in profit, if BTC moves lognormally with volatility `iv` (zero drift). */
  function chanceOfProfit(option, index, iv, years) {
    const level = metrics(option).breakeven;
    if (!positive(index) || !positive(iv) || !positive(years) || level === null) return null;
    const vol = iv * Math.sqrt(years);
    const above = normal((Math.log(index / level) - vol * vol / 2) / vol);
    // A sold put or a bought call profits above breakeven; the other two below it.
    return (option.side === "PUT") === (option.direction === "SELL") ? above : 1 - above;
  }

  return Object.freeze({valid, pnl, metrics, perDay, annualized, chanceOfProfit, normal});
});
