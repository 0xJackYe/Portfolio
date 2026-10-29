// node --test tests/
const test = require("node:test");
const assert = require("node:assert/strict");
const Payoff = require("../web/payoff.js");

const option = (side, direction, extra = {}) => ({side, direction, strike: 64000, premium: 400, quantity: 0.01, unit: 1, ...extra});
const close = (actual, expected, digits = 9) => assert.ok(Math.abs(actual - expected) < 10 ** -digits, `${actual} ≉ ${expected}`);

test("profit and loss at expiry for all four trades", () => {
  // Sold put: keep the premium above the strike, owe the shortfall below it.
  close(Payoff.pnl(option("PUT", "SELL"), 80000), 4);
  close(Payoff.pnl(option("PUT", "SELL"), 64000), 4);
  close(Payoff.pnl(option("PUT", "SELL"), 60000), -36);
  close(Payoff.pnl(option("PUT", "SELL"), 0), -636);
  close(Payoff.pnl(option("PUT", "BUY"), 60000), 36);
  close(Payoff.pnl(option("CALL", "BUY"), 70000), 56);
  close(Payoff.pnl(option("CALL", "BUY"), 50000), -4);
  close(Payoff.pnl(option("CALL", "SELL"), 70000), -56);
  close(Payoff.pnl(option("CALL", "SELL", {quantity: 2}), 64000), 800);
  assert.ok(Object.is(Payoff.pnl(option("PUT", "SELL"), 63600), 0), "breakeven is +0, never −0");
});

test("contract unit scales the position", () => {
  close(Payoff.pnl(option("PUT", "SELL", {unit: 0.1, quantity: 1}), 80000), 40);
  close(Payoff.pnl(option("PUT", "SELL", {unit: undefined}), 80000), 4);
});

test("metrics cover every settlement price", () => {
  assert.deepEqual(Payoff.metrics(option("PUT", "SELL")), {premium: 4, breakeven: 63600, maxProfit: 4, maxLoss: 636});
  assert.deepEqual(Payoff.metrics(option("PUT", "BUY")), {premium: 4, breakeven: 63600, maxProfit: 636, maxLoss: 4});
  assert.deepEqual(Payoff.metrics(option("CALL", "BUY")), {premium: 4, breakeven: 64400, maxProfit: Infinity, maxLoss: 4});
  assert.deepEqual(Payoff.metrics(option("CALL", "SELL")), {premium: 4, breakeven: 64400, maxProfit: 4, maxLoss: Infinity});
  // A put premium above its strike can never lose for the seller and has no positive breakeven.
  assert.deepEqual(Payoff.metrics(option("PUT", "SELL", {premium: 70000})), {premium: 700, breakeven: null, maxProfit: 700, maxLoss: 0});
});

test("metrics agree with the payoff function", () => {
  for (const side of ["CALL", "PUT"]) {
    for (const direction of ["BUY", "SELL"]) {
      const o = option(side, direction);
      const m = Payoff.metrics(o);
      close(Payoff.pnl(o, m.breakeven), 0);
      const samples = [0, 10000, 40000, 63600, 64000, 64400, 90000, 200000].map((s) => Payoff.pnl(o, s));
      if (Number.isFinite(m.maxProfit)) close(Math.max(...samples), m.maxProfit);
      if (Number.isFinite(m.maxLoss)) close(-Math.min(...samples), m.maxLoss);
    }
  }
});

test("valid rejects anything that is not a priced, sized option", () => {
  assert.equal(Payoff.valid(option("PUT", "SELL")), true);
  for (const bad of [null, {}, option("PUT", "HOLD"), option("STRADDLE", "BUY"), option("PUT", "SELL", {premium: 0}),
    option("PUT", "SELL", {premium: null}), option("PUT", "SELL", {premium: "400"}), option("PUT", "SELL", {quantity: -1}),
    option("PUT", "SELL", {strike: NaN}), option("PUT", "SELL", {quantity: Infinity}), option("PUT", "SELL", {unit: 0})]) {
    assert.equal(Payoff.valid(bad), false, JSON.stringify(bad));
  }
});

test("premium per day and annualized yield", () => {
  close(Payoff.perDay(option("PUT", "SELL"), 10), 0.4);
  close(Payoff.perDay(option("PUT", "SELL"), 0.25), 16);
  // 400 on a 64,000 strike for 36.5 days is 6.25% a year.
  close(Payoff.annualized(option("PUT", "SELL"), 36.5, 80000), 0.0625);
  // Calls tie up the BTC itself, valued at the index.
  close(Payoff.annualized(option("CALL", "SELL"), 36.5, 80000), 0.05);
});

test("standard normal distribution", () => {
  close(Payoff.normal(0), 0.5, 7);
  close(Payoff.normal(1.959964), 0.975, 6);
  close(Payoff.normal(-1), 0.158655, 6);
  close(Payoff.normal(-8), 0, 6);
});

test("chance of profit from implied volatility", () => {
  const sell = option("PUT", "SELL");
  const chance = Payoff.chanceOfProfit(sell, 80000, 0.5, 30 / 365);
  // ln(80000 / 63600) ≈ 0.2294; σ√T ≈ 0.1434; d2 ≈ 1.528 → about 93.7%.
  close(chance, 0.9367, 3);
  close(chance + Payoff.chanceOfProfit(option("PUT", "BUY"), 80000, 0.5, 30 / 365), 1);
  close(Payoff.chanceOfProfit(option("CALL", "BUY"), 80000, 0.5, 30 / 365) +
    Payoff.chanceOfProfit(option("CALL", "SELL"), 80000, 0.5, 30 / 365), 1);
  // More volatility, less certainty for the seller.
  assert.ok(Payoff.chanceOfProfit(sell, 80000, 0.9, 30 / 365) < chance);
  for (const [index, iv, years] of [[80000, null, 0.1], [80000, 0, 0.1], [null, 0.5, 0.1], [80000, 0.5, 0]]) {
    assert.equal(Payoff.chanceOfProfit(sell, index, iv, years), null);
  }
  assert.equal(Payoff.chanceOfProfit(option("PUT", "SELL", {premium: 70000}), 80000, 0.5, 0.1), null);
});
