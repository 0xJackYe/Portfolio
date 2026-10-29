/* BTC Options: a live Binance options chain and an at-expiry payoff inspector. */
"use strict";

const STRINGS = {
  en: {
    appName: "BTC Options",
    indexLabel: "Bitcoin index price",
    sell: "Sell", buy: "Buy", puts: "Puts", calls: "Calls",
    direction: "Buy or sell", optionType: "Option type", expiries: "Expiry date",
    strike: "Strike", distance: "Distance", bid: "Bid", ask: "Ask",
    perDay: "Per day", annualized: "Annualized", breakeven: "Breakeven",
    tipDistance: "How far the strike is from the index price",
    tipBid: "Best bid per BTC: what selling one contract pays now",
    tipAsk: "Best ask per BTC: what buying one contract costs now",
    tipPerDay: "Premium per BTC divided by the days left",
    tipAnnualized: "Premium as a yearly rate on the cash it ties up: the strike for puts, BTC for calls",
    tipBreakeven: "Where BTC must settle for the trade to break even",
    perDayShort: "{value} per day",
    loading: "Loading", connecting: "Connecting", live: "Live", delayed: "Delayed", offline: "Offline",
    loadingTip: "Loading market data", connectingTip: "Connecting to the Binance live stream",
    liveTip: "Streaming live from Binance", delayedTip: "Live stream interrupted; refreshing every 15 seconds",
    offlineTip: "The dashboard server is not responding",
    updatedAt: "Last update {time}",
    bannerOffline: "Lost connection to the dashboard server. Reconnecting…",
    bannerNoData: "Can't reach Binance yet. Retrying…",
    banner_network: "Can't reach Binance. Showing data from {time} and retrying.",
    banner_rate_limit: "Binance is limiting requests. Showing data from {time}; retrying shortly.",
    banner_server: "Binance returned an error. Showing data from {time} and retrying.",
    banner_data: "Binance sent unexpected data. Showing data from {time} and retrying.",
    dayHour: "{d}d {h}h", hourMinute: "{h}h {m}m", minutes: "{m}m",
    chipDays: "{d}d", chipHours: "{h}h", chipMinutes: "{m}m",
    boardNote: "Expires at {time} · {left} left · ATM IV {iv}",
    leftSuffix: "{left} left",
    loadingMarket: "Loading market…",
    noContracts: "No contracts for this date.",
    footer: "Binance public market data · Read-only, never places orders · Times in your time zone",
    sellPut: "Sell put", sellCall: "Sell call", buyPut: "Buy put", buyCall: "Buy call",
    youReceive: "You receive", youPay: "You pay",
    totalNote: "{price} × {qty} BTC {source}",
    atBid: "at the live bid", atAsk: "at the live ask", atCustom: "at your price",
    noQuote: "No live {quote} right now. Enter a price to simulate.",
    bidWord: "bid", askWord: "ask",
    invalidPrice: "Enter a price above zero.",
    price: "Price", quantity: "Quantity", less: "Less", more: "More",
    liveBid: "Live bid", liveAsk: "Live ask", useLive: "Use live price",
    pnlAtExpiry: "Profit or loss at expiry",
    ifSettles: "if BTC settles at {price}", ifStays: "if BTC stays at {price}",
    now: "Now",
    noChart: "Enter a price to see the payoff.",
    chartLabel: "BTC settlement price for the payoff chart",
    chartValue: "{price}: {pnl} USDT",
    maxProfit: "Max profit", maxLoss: "Max loss", unlimited: "Unlimited",
    ifAbove: "if BTC ≥ {price}", ifBelow: "if BTC ≤ {price}", ifZero: "if BTC falls to 0",
    fromNow: "{pct} from now",
    perDayNote: "for {qty} BTC",
    annualizedNote: "on {amount} USDT",
    distanceNote: "strike vs. index",
    chance: "Chance of profit", chanceNote: "at IV {iv}",
    market: "Market", symbol: "Contract", mark: "Mark", bidSize: "Bid size", askSize: "Ask size",
    iv: "Implied vol.", delta: "Delta", gamma: "Gamma", theta: "Theta", vega: "Vega", volume: "24h volume",
    fineprint: "Estimates assume you hold to expiry and exclude fees. Binance settles on the average index over the last 30 minutes before expiry. Chance of profit comes from the option's implied volatility; it is a model, not a forecast. Read-only: nothing here places orders.",
    close: "Close",
    themeDark: "Use dark appearance", themeLight: "Use light appearance",
    switchLanguage: "切换到中文",
  },
  zh: {
    appName: "BTC 期权",
    indexLabel: "比特币指数价格",
    sell: "卖出", buy: "买入", puts: "Put", calls: "Call",
    direction: "买卖方向", optionType: "期权类型", expiries: "到期日",
    strike: "行权价", distance: "距现价", bid: "买价", ask: "卖价",
    perDay: "每日", annualized: "年化", breakeven: "盈亏平衡",
    tipDistance: "行权价与当前指数价格的距离",
    tipBid: "每 BTC 最优买价：现在卖出一张可收的权利金",
    tipAsk: "每 BTC 最优卖价：现在买入一张需付的权利金",
    tipPerDay: "每 BTC 权利金 ÷ 剩余天数",
    tipAnnualized: "权利金按占用资金折算的年化比率：Put 按行权价，Call 按 BTC 价格",
    tipBreakeven: "到期时不赚不亏的 BTC 结算价",
    perDayShort: "每日 {value}",
    loading: "加载中", connecting: "连接中", live: "实时", delayed: "延迟", offline: "离线",
    loadingTip: "正在加载行情", connectingTip: "正在连接币安实时推送",
    liveTip: "币安实时推送中", delayedTip: "实时推送中断，每 15 秒刷新一次",
    offlineTip: "本地看板服务无响应",
    updatedAt: "最后更新 {time}",
    bannerOffline: "与本地看板服务的连接中断，正在重连…",
    bannerNoData: "暂时无法连接币安，正在重试…",
    banner_network: "暂时无法连接币安，显示 {time} 的数据，正在重试。",
    banner_rate_limit: "币安暂时限制请求，显示 {time} 的数据，稍后自动重试。",
    banner_server: "币安返回错误，显示 {time} 的数据，正在重试。",
    banner_data: "币安返回的数据异常，显示 {time} 的数据，正在重试。",
    dayHour: "{d}天{h}小时", hourMinute: "{h}小时{m}分", minutes: "{m}分钟",
    chipDays: "{d}天", chipHours: "{h}小时", chipMinutes: "{m}分",
    boardNote: "{time} 到期 · 剩余 {left} · 平值 IV {iv}",
    leftSuffix: "剩余 {left}",
    loadingMarket: "正在加载行情…",
    noContracts: "该到期日暂无合约。",
    footer: "币安公开行情 · 只读，不会下单 · 时间为本机时区",
    sellPut: "卖出 Put", sellCall: "卖出 Call", buyPut: "买入 Put", buyCall: "买入 Call",
    youReceive: "收取权利金", youPay: "支付权利金",
    totalNote: "{price} × {qty} BTC，{source}",
    atBid: "按实时买价", atAsk: "按实时卖价", atCustom: "按自定义价格",
    noQuote: "当前没有{quote}，可输入价格试算。",
    bidWord: "买价", askWord: "卖价",
    invalidPrice: "请输入大于 0 的价格。",
    price: "价格", quantity: "数量", less: "减少", more: "增加",
    liveBid: "实时买价", liveAsk: "实时卖价", useLive: "恢复实时价",
    pnlAtExpiry: "到期盈亏",
    ifSettles: "若 BTC 结算价为 {price}", ifStays: "若 BTC 保持在 {price}",
    now: "现价",
    noChart: "输入价格后显示盈亏曲线。",
    chartLabel: "盈亏曲线的 BTC 结算价",
    chartValue: "{price}：{pnl} USDT",
    maxProfit: "最大盈利", maxLoss: "最大亏损", unlimited: "无上限",
    ifAbove: "BTC ≥ {price} 时", ifBelow: "BTC ≤ {price} 时", ifZero: "BTC 跌至 0 时",
    fromNow: "距现价 {pct}",
    perDayNote: "{qty} BTC 合计",
    annualizedNote: "按 {amount} USDT 占用",
    distanceNote: "行权价相对指数",
    chance: "盈利概率", chanceNote: "按 IV {iv}",
    market: "盘口", symbol: "合约", mark: "标记价", bidSize: "买量", askSize: "卖量",
    iv: "隐含波动率", delta: "Delta", gamma: "Gamma", theta: "Theta", vega: "Vega", volume: "24h 成交量",
    fineprint: "按持有到期估算，未计手续费。币安以到期前 30 分钟指数均价结算。盈利概率由期权隐含波动率推算，是模型估计而非预测。本看板只读，不会下单。",
    close: "关闭",
    themeDark: "使用深色外观", themeLight: "使用浅色外观",
    switchLanguage: "Switch to English",
  },
};

const DAY = 86400000;
const MINUS = "−";
const SETTINGS_KEY = "btc-options";
const COLUMNS = {
  SELL: ["strike", "distance", "premium", "perDay", "annualized"],
  BUY: ["strike", "distance", "premium", "perDay", "breakeven"],
};
const wide = matchMedia("(min-width: 1100px)");
const prefersDark = matchMedia("(prefers-color-scheme: dark)");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const $ = (id) => document.getElementById(id);
const isPositive = (value) => typeof value === "number" && Number.isFinite(value) && value > 0;

/* State ---------------------------------------------------------------------- */

const saved = (() => {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {};
  } catch {
    return {};
  }
})();

const state = {
  lang: ["en", "zh"].includes(saved.lang) ? saved.lang : /^zh\b/i.test(navigator.language || "") ? "zh" : "en",
  theme: ["light", "dark"].includes(saved.theme) ? saved.theme : null, // null follows the system
  direction: saved.direction === "BUY" ? "BUY" : "SELL",
  side: saved.side === "CALL" ? "CALL" : "PUT",
  expiry: Number.isFinite(saved.expiry) ? saved.expiry : null,
  quantity: isPositive(saved.quantity) ? saved.quantity : 0.01,
  selected: null,     // contract shown in the inspector
  customPrice: null,  // a typed premium; null follows the live quote
  scrub: null,        // settlement price under the pointer in the chart
};

let market = null;           // latest snapshot from the server
let contracts = new Map();   // symbol -> contract
let chain = new Map();       // expiry -> {PUT: [...], CALL: [...]}, strikes ascending
let connection = "connecting";
let tableKey = "";
let chipsKey = "";
let chartKey = "";
let chartRange = null;
let geometry = null;         // scales of the drawn chart, for scrubbing
let model = null;            // option and index behind the inspector
let tabSymbol = null;        // the one row reachable with Tab; arrow keys move within the list

function saveSettings() {
  const {lang, theme, direction, side, expiry, quantity} = state;
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({lang, theme, direction, side, expiry, quantity}));
  } catch {
    // Private windows may refuse storage; settings then last for this visit.
  }
}

/* Text and numbers ----------------------------------------------------------- */

function t(key, vars) {
  const text = STRINGS[state.lang][key] ?? STRINGS.en[key] ?? key;
  return vars ? text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? "")) : text;
}

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function setText(element, text) {
  if (element && element.textContent !== text) element.textContent = text;
}

function setHtml(element, html) {
  // Rebuild only on change, so live ticks don't disturb text selection or screen readers.
  if (element.dataset.html !== html) {
    element.innerHTML = html;
    element.dataset.html = html;
  }
}

const numberFormats = new Map();
function fmt(value, max = 2, min = 0, sign = false) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const key = `${max}|${min}|${sign}`;
  let format = numberFormats.get(key);
  if (!format) {
    format = new Intl.NumberFormat("en-US", {maximumFractionDigits: max, minimumFractionDigits: min, signDisplay: sign ? "exceptZero" : "auto"});
    numberFormats.set(key, format);
  }
  return format.format(value).replace("-", MINUS);
}

const usdt = (value, sign = false) => fmt(value, 2, 2, sign);
const price = (value) => fmt(value, 2);
const whole = (value) => fmt(value, 0);
const percent = (value, digits = 1, sign = false) =>
  typeof value === "number" && Number.isFinite(value) ? `${fmt(value * 100, digits, digits, sign)}%` : "—";
const compact = (value) => value >= 1000 ? `${fmt(value / 1000, 1)}k` : fmt(value, 0);
const plain = (value) => String(Math.round(value * 1e4) / 1e4);

const dateFormats = new Map();
const DATE_OPTIONS = {
  chip: {month: "short", day: "numeric"},
  long: {weekday: "short", year: "numeric", month: "short", day: "numeric"},
  medium: {weekday: "short", month: "short", day: "numeric"},
  time: {hour: "2-digit", minute: "2-digit", hourCycle: "h23"},
  clock: {hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"},
};
function dateText(ms, kind) {
  const key = state.lang + kind;
  if (!dateFormats.has(key)) {
    // Chinese chips use the compact 12/12 form; "12月12日" would not fit a row of dates.
    const options = state.lang === "zh" && kind === "chip" ? {month: "numeric", day: "numeric"} : DATE_OPTIONS[kind];
    dateFormats.set(key, new Intl.DateTimeFormat(state.lang === "zh" ? "zh-CN" : "en-US", options));
  }
  return dateFormats.get(key).format(new Date(ms));
}

function duration(ms) {
  const minutes = Math.max(0, Math.floor(ms / 60000));
  const d = Math.floor(minutes / 1440), h = Math.floor((minutes % 1440) / 60), m = minutes % 60;
  return d ? t("dayHour", {d, h}) : h ? t("hourMinute", {h, m}) : t("minutes", {m});
}

function shortDuration(ms) {
  if (ms >= DAY) return t("chipDays", {d: Math.floor(ms / DAY)});
  if (ms >= 3600000) return t("chipHours", {h: Math.floor(ms / 3600000)});
  return t("chipMinutes", {m: Math.max(1, Math.floor(ms / 60000))});
}

/* Market data ---------------------------------------------------------------- */

const now = () => Date.now() + (market?.offset ?? 0);
const daysLeft = (contract) => Math.max((contract.expiry - now()) / DAY, 1 / 1440);
const liveQuote = (contract, direction = state.direction) => direction === "SELL" ? contract.bid : contract.ask;

function ingest(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.contracts)) return;
  market = snapshot;
  contracts = new Map();
  chain = new Map();
  for (const contract of snapshot.contracts) {
    contracts.set(contract.symbol, contract);
    let group = chain.get(contract.expiry);
    if (!group) chain.set(contract.expiry, (group = {PUT: [], CALL: []}));
    group[contract.side]?.push(contract);
  }
}

function liveExpiries() {
  const time = now();
  return [...chain.keys()].filter((expiry) => expiry > time);
}

function ensureExpiry() {
  const list = liveExpiries();
  if (!list.length) return null;
  if (!list.includes(state.expiry)) {
    const justExpired = state.expiry !== null && now() - state.expiry < DAY;
    // The date on screen just expired: move to the next one. Otherwise start about a month out.
    const target = justExpired ? now() : now() + 30 * DAY;
    state.expiry = list.reduce((best, expiry) => Math.abs(expiry - target) < Math.abs(best - target) ? expiry : best);
  }
  return state.expiry;
}

function rowValues(contract) {
  const index = market.index;
  const premium = liveQuote(contract);
  const days = daysLeft(contract);
  const quoted = isPositive(premium);
  return {
    distance: isPositive(index) ? contract.strike / index - 1 : null,
    premium: quoted ? premium : null,
    perDay: quoted ? premium / days : null,
    annualized: quoted && isPositive(index) ? Payoff.annualized({side: contract.side, strike: contract.strike, premium}, days, index) : null,
    breakeven: quoted ? (contract.side === "PUT" ? contract.strike - premium : contract.strike + premium) : null,
    itm: isPositive(index) && (contract.side === "PUT" ? contract.strike > index : contract.strike < index),
  };
}

function atmIv(group) {
  const index = market.index;
  const all = [...group.PUT, ...group.CALL];
  if (!isPositive(index) || !all.length) return null;
  const strike = all.reduce((best, c) => Math.abs(c.strike - index) < Math.abs(best - index) ? c.strike : best, all[0].strike);
  const ivs = all.filter((c) => c.strike === strike && isPositive(c.iv)).map((c) => c.iv);
  return ivs.length ? ivs.reduce((a, b) => a + b, 0) / ivs.length : null;
}

/* Rendering ------------------------------------------------------------------ */

let frame = 0;
function schedule() {
  if (!frame) frame = requestAnimationFrame(() => {
    frame = 0;
    if (!document.hidden) render();
  });
}

function render() {
  renderStatus();
  renderHero();
  renderPicker("directionPicker", state.direction);
  renderPicker("sidePicker", state.side);
  renderPicker("sheetDirection", state.direction);
  const expiry = market && market.status !== "loading" ? ensureExpiry() : null;
  if (expiry === null) {
    renderSkeleton();
    return;
  }
  renderExpiries(liveExpiries());
  renderBoard(expiry);
  renderInspector();
}

function renderStatus() {
  const status = connection === "lost" ? "offline" : market ? market.status : "loading";
  $("status").dataset.state = status;
  $("status").title = t(`${status}Tip`);
  setText($("statusText"), t(status));
  let message = "";
  if (connection === "lost") message = t("bannerOffline");
  else if (market?.error) message = market.updated ? t(`banner_${market.error}`, {time: dateText(market.updated, "clock")}) : t("bannerNoData");
  const banner = $("banner");
  banner.hidden = !message;
  banner.dataset.tone = connection === "lost" ? "error" : "warning";
  setText(banner, message);
  setText($("heroNote"), status === "delayed" && market?.updated ? t("updatedAt", {time: dateText(market.updated, "clock")}) : "");
}

function renderHero() {
  const index = market?.index;
  $("hero").classList.toggle("pending", !isPositive(index));
  setText($("indexPrice"), isPositive(index) ? fmt(index, 2, 2) : "");
  setText($("navPrice"), isPositive(index) ? `BTC ${fmt(index, 2, 2)}` : "");
  const title = isPositive(index) ? `${whole(index)} · ${t("appName")}` : t("appName");
  if (document.title !== title) document.title = title;
}

function renderPicker(id, value) {
  const picker = $(id);
  const buttons = [...picker.querySelectorAll("button")];
  picker.style.setProperty("--count", buttons.length);
  buttons.forEach((button, i) => {
    const on = button.dataset.value === value;
    button.setAttribute("aria-pressed", String(on));
    if (on) picker.style.setProperty("--index", i);
  });
}

function renderExpiries(list) {
  const box = $("expiries");
  const key = state.lang + list.join();
  if (key !== chipsKey) {
    chipsKey = key;
    box.innerHTML = list.map((expiry) =>
      `<button type="button" class="chip" data-expiry="${expiry}"><span>${escapeHtml(dateText(expiry, "chip"))}</span><small></small></button>`).join("");
    requestAnimationFrame(() => revealChip(false));
  }
  for (const chip of box.children) {
    const expiry = Number(chip.dataset.expiry);
    chip.setAttribute("aria-pressed", String(expiry === state.expiry));
    chip.title = `${dateText(expiry, "long")} ${dateText(expiry, "time")}`;
    setText(chip.querySelector("small"), shortDuration(expiry - now()));
  }
}

function revealChip(smooth = true) {
  // Scroll the date row just enough to show the selected date clear of the faded edges.
  const box = $("expiries");
  const chip = box.querySelector('[aria-pressed="true"]');
  if (!chip) return;
  const edge = 32;
  const min = chip.offsetLeft + chip.offsetWidth + edge - box.clientWidth;
  const max = chip.offsetLeft - edge;
  const left = Math.min(Math.max(box.scrollLeft, min), max);
  if (Math.abs(left - box.scrollLeft) > 1) box.scrollTo({left, behavior: smooth && !reducedMotion.matches ? "smooth" : "auto"});
}

function renderBoard(expiry) {
  const group = chain.get(expiry) ?? {PUT: [], CALL: []};
  const rows = group[state.side];
  setText($("boardTitle"), dateText(expiry, "long"));
  setText($("boardNote"), t("boardNote", {time: dateText(expiry, "time"), left: duration(expiry - now()), iv: percent(atmIv(group))}));
  $("empty").hidden = rows.length > 0;
  setText($("empty"), t("noContracts"));
  renderTable(rows);
}

function columnLabel(column) {
  return column === "premium" ? t(state.direction === "SELL" ? "bid" : "ask") : t(column);
}

function columnTip(column) {
  const key = column === "premium" ? (state.direction === "SELL" ? "bid" : "ask") : column;
  return column === "strike" ? "" : t(`tip${key[0].toUpperCase()}${key.slice(1)}`);
}

const columnClass = (column) => `col-${column.toLowerCase()}`;

function renderHead(columns) {
  $("chainHead").innerHTML = columns.map((column) => {
    const tip = columnTip(column);
    return `<th scope="col" class="${columnClass(column)}"${tip ? ` title="${escapeHtml(tip)}"` : ""}>${escapeHtml(columnLabel(column))}</th>`;
  }).join("");
}

function rowHtml(contract, columns) {
  return `<tr class="row" data-symbol="${escapeHtml(contract.symbol)}">${columns.map((column) => {
    if (column === "strike") return `<td class="col-strike"><button type="button" class="strike" data-cell="strike"></button><span class="sub" data-cell="distanceSub"></span></td>`;
    if (column === "premium") return `<td class="col-premium"><span class="premium" data-cell="premium"></span><span class="sub" data-cell="perDaySub"></span></td>`;
    return `<td class="${columnClass(column)}${column === "distance" ? " distance" : ""}" data-cell="${column}"></td>`;
  }).join("")}</tr>`;
}

function renderTable(rows) {
  const columns = COLUMNS[state.direction];
  const key = [state.lang, state.direction, state.side, state.expiry, rows.map((c) => c.symbol).join()].join("|");
  if (key !== tableKey) {
    tableKey = key;
    renderHead(columns);
    const spot = `<tr class="spot-row" aria-hidden="true"><td colspan="${columns.length}"><div class="spot"><span data-spot></span></div></td></tr>`;
    $("chainBody").innerHTML = spot + rows.map((contract) => rowHtml(contract, columns)).join("");
  }
  placeSpot(rows);
  updateRows();
}

/* Move the BTC price line between the strikes around it; rows stay put, so focus and hover survive. */
function placeSpot(rows) {
  const body = $("chainBody");
  const spot = body.querySelector(".spot-row");
  const index = market.index;
  spot.hidden = !isPositive(index) || !rows.length;
  if (spot.hidden) return;
  const above = rows.find((c) => c.strike > index);
  const next = above ? body.querySelector(`tr.row[data-symbol="${CSS.escape(above.symbol)}"]`) : null;
  if (spot.nextElementSibling !== next) body.insertBefore(spot, next);
}

function updateRows() {
  const body = $("chainBody");
  setText(body.querySelector("[data-spot]"), `BTC ${fmt(market.index, 2, 2)}`);
  const sideWord = state.side === "PUT" ? "Put" : "Call";
  const rows = [...body.querySelectorAll("tr.row")];
  const tabRow = rows.find((r) => r.dataset.symbol === state.selected) ?? rows.find((r) => r.dataset.symbol === tabSymbol) ?? rows[0];
  for (const row of rows) {
    row.querySelector(".strike").tabIndex = row === tabRow ? 0 : -1;
    const contract = contracts.get(row.dataset.symbol);
    if (!contract) continue;
    const v = rowValues(contract);
    row.classList.toggle("itm", v.itm);
    row.classList.toggle("selected", contract.symbol === state.selected);
    for (const cell of row.querySelectorAll("[data-cell]")) {
      const name = cell.dataset.cell;
      const text = {
        strike: whole(contract.strike),
        distance: percent(v.distance, 1, true),
        distanceSub: percent(v.distance, 1, true),
        premium: price(v.premium),
        perDay: usdt(v.perDay),
        perDaySub: v.perDay === null ? "" : t("perDayShort", {value: usdt(v.perDay)}),
        annualized: percent(v.annualized),
        breakeven: whole(v.breakeven),
      }[name];
      if (name === "premium") {
        const before = Number(cell.dataset.value);
        const after = v.premium ?? NaN;
        if (Number.isFinite(before) && Number.isFinite(after) && before !== after) flash(cell, after > before);
        cell.dataset.value = after;
      }
      setText(cell, text);
    }
    const label = `${whole(contract.strike)} ${sideWord}, ${columnLabel("premium")} ${price(v.premium)}, ${t("perDay")} ${usdt(v.perDay)}`;
    const button = row.querySelector(".strike");
    if (button.getAttribute("aria-label") !== label) button.setAttribute("aria-label", label);
  }
}

function flash(cell, up) {
  cell.classList.remove("up", "down");
  cell.classList.add(up ? "up" : "down");
  clearTimeout(cell.flashTimer);
  cell.flashTimer = setTimeout(() => cell.classList.remove("up", "down"), 650);
}

function renderSkeleton() {
  const key = `skeleton|${state.lang}|${state.direction}`;
  setText($("boardTitle"), t("loadingMarket"));
  setText($("boardNote"), " ");
  if (tableKey === key) return;
  tableKey = key;
  chipsKey = "";
  const columns = COLUMNS[state.direction];
  $("expiries").innerHTML = '<span class="chip placeholder"></span>'.repeat(7);
  renderHead(columns);
  $("chainBody").innerHTML = `<tr class="skeleton">${columns.map((column) => `<td class="${columnClass(column)}"><span></span></td>`).join("")}</tr>`.repeat(10);
  $("empty").hidden = true;
}

/* Scroll anchoring: keep the strikes you were looking at in place ------------ */

function captureAnchor() {
  const line = $("chain").tHead.getBoundingClientRect().bottom;
  const rows = [...$("chainBody").querySelectorAll("tr.row")];
  if (!rows.length || rows[0].getBoundingClientRect().top >= line) return null;
  const row = rows.find((r) => r.getBoundingClientRect().bottom > line + 1);
  const contract = row && contracts.get(row.dataset.symbol);
  return contract ? {strike: contract.strike, top: row.getBoundingClientRect().top} : null;
}

function restoreAnchor(anchor) {
  if (!anchor) return;
  const strikeOf = (row) => contracts.get(row.dataset.symbol)?.strike ?? Infinity;
  const rows = [...$("chainBody").querySelectorAll("tr.row")];
  if (!rows.length) return;
  const row = rows.reduce((best, r) => Math.abs(strikeOf(r) - anchor.strike) < Math.abs(strikeOf(best) - anchor.strike) ? r : best);
  window.scrollBy(0, row.getBoundingClientRect().top - anchor.top);
}

function change(update) {
  const anchor = captureAnchor();
  const focused = document.activeElement?.closest?.("#chainBody tr.row");
  const focusedStrike = focused ? contracts.get(focused.dataset.symbol)?.strike : null;
  update();
  saveSettings();
  render();
  restoreAnchor(anchor);
  if (focusedStrike != null && !$("chainBody").contains(document.activeElement)) {
    // The rows were rebuilt: keep keyboard focus on the same strike, or the nearest one.
    const rows = [...$("chainBody").querySelectorAll("tr.row")];
    const distance = (row) => Math.abs((contracts.get(row.dataset.symbol)?.strike ?? Infinity) - focusedStrike);
    const row = rows.find((r) => r.dataset.symbol === state.selected) ?? rows.reduce((best, r) => distance(r) < distance(best) ? r : best, rows[0]);
    if (row) {
      tabSymbol = row.dataset.symbol;
      row.querySelector(".strike").tabIndex = 0;
      row.querySelector(".strike").focus({preventScroll: true});
    }
  }
}

/* Follow the open inspector to the nearest strike of the new expiry or side. */
function followSelection() {
  const current = contracts.get(state.selected);
  const rows = chain.get(state.expiry)?.[state.side] ?? [];
  if (!current) return;
  if (!rows.length) {
    closeInspector();
    return;
  }
  const next = rows.reduce((best, c) => Math.abs(c.strike - current.strike) < Math.abs(best.strike - current.strike) ? c : best);
  if (next.symbol !== state.selected) {
    state.selected = next.symbol;
    state.customPrice = null;
    state.scrub = null;
  }
}

function selectExpiry(expiry) {
  if (expiry === state.expiry) return;
  change(() => {
    state.expiry = expiry;
    followSelection();
  });
  revealChip();
}

function setDirection(direction) {
  if (direction === state.direction) return;
  change(() => {
    state.direction = direction;
    state.customPrice = null;
  });
}

function setSide(side) {
  if (side === state.side) return;
  change(() => {
    state.side = side;
    followSelection();
  });
}

/* Inspector ------------------------------------------------------------------ */

function openInspector(symbol) {
  const sheet = $("inspector");
  if (state.selected !== symbol) {
    state.selected = symbol;
    state.customPrice = null;
    state.scrub = null;
  }
  if (!sheet.open || sheet.classList.contains("closing")) {
    clearTimeout(closeTimer);
    sheet.classList.remove("closing");
    sheet.style.transform = "";
    if (sheet.open) sheet.close();
    chartKey = "";
    if (wide.matches) {
      // A side panel beside the list: show it without moving focus, so arrow keys keep browsing.
      sheet.setAttribute("open", "");
      document.body.classList.add("inspecting");
    } else {
      sheet.showModal();
      sheet.focus({preventScroll: true});
    }
    sheet.scrollTop = 0;
  }
  render();
}

let closeTimer = 0;
function closeInspector() {
  const sheet = $("inspector");
  if (!sheet.open || sheet.classList.contains("closing")) return;
  const symbol = state.selected;
  const hadFocus = sheet.contains(document.activeElement);
  sheet.classList.add("closing");
  document.body.classList.remove("inspecting");
  closeTimer = setTimeout(() => {
    sheet.classList.remove("closing");
    sheet.style.transform = "";
    sheet.close();
    state.selected = null;
    state.customPrice = null;
    state.scrub = null;
    render();
    const row = [...$("chainBody").querySelectorAll("tr.row")].find((r) => r.dataset.symbol === symbol);
    if (hadFocus || document.activeElement === document.body) row?.querySelector(".strike").focus({preventScroll: true});
  }, reducedMotion.matches ? 0 : 300);
}

function quantityText(quantity) {
  return fmt(quantity, 4);
}

function renderInspector() {
  const sheet = $("inspector");
  if (!sheet.open || sheet.classList.contains("closing")) return;
  const contract = contracts.get(state.selected);
  if (!contract || contract.expiry <= now()) {
    closeInspector();
    return;
  }
  const sell = state.direction === "SELL";
  const put = contract.side === "PUT";
  const custom = state.customPrice !== null;
  const premium = custom ? state.customPrice : liveQuote(contract);
  const option = {side: contract.side, direction: state.direction, strike: contract.strike,
    premium, quantity: state.quantity, unit: contract.unit};
  const valid = Payoff.valid(option);
  const metrics = valid ? Payoff.metrics(option) : null;
  const index = market.index;
  const days = daysLeft(contract);
  const qty = quantityText(state.quantity);
  model = {option, valid, index};

  setText($("sheetEyebrow"), t(`${sell ? "sell" : "buy"}${put ? "Put" : "Call"}`));
  setText($("sheetTitle"), `${whole(contract.strike)} ${put ? "Put" : "Call"}`);
  setText($("sheetNote"), `${dateText(contract.expiry, "medium")} · ${dateText(contract.expiry, "time")} · ${t("leftSuffix", {left: duration(contract.expiry - now())})}`);

  setText($("totalLabel"), t(sell ? "youReceive" : "youPay"));
  setText($("totalValue"), metrics ? usdt(metrics.premium) : "—");
  setText($("totalNote"), valid
    ? t("totalNote", {price: price(premium), qty, source: t(custom ? "atCustom" : sell ? "atBid" : "atAsk")})
    : custom ? t("invalidPrice") : t("noQuote", {quote: t(sell ? "bidWord" : "askWord")}));

  const priceInput = $("priceInput");
  if (document.activeElement !== priceInput) priceInput.value = isPositive(premium) ? plain(premium) : "";
  priceInput.setAttribute("aria-invalid", String(custom && !isPositive(premium)));
  const tag = $("priceLive");
  tag.classList.toggle("custom", custom);
  tag.tabIndex = custom ? 0 : -1;
  tag.setAttribute("aria-disabled", String(!custom));
  setText(tag, custom ? t("useLive") : t(sell ? "liveBid" : "liveAsk"));
  const quantityInput = $("quantityInput");
  if (document.activeElement !== quantityInput) quantityInput.value = plain(state.quantity);

  renderChart();

  const worthless = t(put ? "ifAbove" : "ifBelow", {price: whole(contract.strike)});
  const extreme = put ? t("ifZero") : "";
  const money = (value, signed) => value === Infinity ? t("unlimited") : usdt(signed, true);
  const chance = valid ? Payoff.chanceOfProfit(option, index, contract.iv, days / 365) : null;
  const stats = [
    [t("breakeven"), metrics?.breakeven ? whole(metrics.breakeven) : "—",
      metrics?.breakeven && isPositive(index) ? t("fromNow", {pct: percent(metrics.breakeven / index - 1, 1, true)}) : "", ""],
    [t("maxProfit"), metrics ? money(metrics.maxProfit, metrics.maxProfit) : "—", sell ? worthless : extreme, "positive"],
    [t("maxLoss"), metrics ? money(metrics.maxLoss, -metrics.maxLoss) : "—", sell ? extreme : worthless, "negative"],
    [t("perDay"), valid ? usdt(Payoff.perDay(option, days)) : "—", t("perDayNote", {qty}), ""],
    sell
      ? [t("annualized"), valid && isPositive(index) ? percent(Payoff.annualized(option, days, index)) : "—",
        t("annualizedNote", {amount: whole((put ? contract.strike : index) * state.quantity * contract.unit)}), ""]
      : [t("distance"), percent(isPositive(index) ? contract.strike / index - 1 : null, 1, true), t("distanceNote"), ""],
    [t("chance"), chance === null ? "—" : percent(chance, 0), isPositive(contract.iv) ? t("chanceNote", {iv: percent(contract.iv)}) : "", ""],
  ];
  setHtml($("stats"), stats.map(([label, value, note, tone]) =>
    `<div><dt>${escapeHtml(label)}</dt><dd${tone && metrics ? ` class="${tone}"` : ""}>${escapeHtml(value)}${note ? `<small>${escapeHtml(note)}</small>` : ""}</dd></div>`).join(""));

  const size = (value) => typeof value === "number" ? `${fmt(value, 2)} BTC` : "—";
  const details = [
    [t("bid"), price(contract.bid)], [t("ask"), price(contract.ask)],
    [t("bidSize"), contract.bid ? size(contract.bidSize) : "—"], [t("askSize"), contract.ask ? size(contract.askSize) : "—"],
    [t("mark"), price(contract.mark)], [t("iv"), percent(contract.iv)],
    [t("delta"), fmt(contract.delta, 3)], [t("gamma"), fmt(contract.gamma, 6)],
    [t("theta"), fmt(contract.theta, 2)], [t("vega"), fmt(contract.vega, 2)],
    [t("volume"), size(contract.volume)], [t("symbol"), contract.symbol, "symbol"],
  ];
  setHtml($("details"), details.map(([label, value, kind]) =>
    `<div${kind ? ` class="${kind}"` : ""}><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join(""));
}

/* Payoff chart --------------------------------------------------------------- */

function stableRange(option, index) {
  // Keep the scale still while quotes tick; rescale only when a key price nears an edge.
  const key = `${state.selected}|${option.direction}`;
  const breakeven = option.side === "PUT" ? option.strike - option.premium : option.strike + option.premium;
  const points = [option.strike, breakeven, index].filter(isPositive);
  const inside = chartRange && chartRange.key === key &&
    points.every((p) => p > chartRange.lo + (chartRange.hi - chartRange.lo) * 0.08 && p < chartRange.hi - (chartRange.hi - chartRange.lo) * 0.08);
  if (!inside) chartRange = {key, lo: Math.max(0, Math.min(...points) * 0.72), hi: Math.max(...points) * 1.28};
  return chartRange;
}

function niceTicks(lo, hi, count) {
  const raw = (hi - lo) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw);
  const ticks = [];
  for (let value = Math.ceil(lo / step) * step; value <= hi; value += step) ticks.push(value);
  return ticks;
}

function renderChart() {
  const box = $("chart");
  const {option, valid, index} = model;
  if (!valid || !isPositive(index)) {
    chartKey = "";
    geometry = null;
    for (const name of ["tabindex", "role", "aria-label", "aria-valuemin", "aria-valuemax", "aria-valuenow", "aria-valuetext"]) box.removeAttribute(name);
    box.innerHTML = `<div class="chart-empty">${escapeHtml(t("noChart"))}</div>`;
    updateReadout();
    return;
  }
  const width = Math.round(box.clientWidth) || 360;
  const height = Math.round(box.clientHeight) || 206;
  const {lo, hi} = stableRange(option, index);
  const key = [option.side, option.direction, option.strike, option.premium, option.quantity, lo, hi, width, height, state.lang].join();
  if (key !== chartKey) {
    chartKey = key;
    box.innerHTML = drawChart(option, lo, hi, width, height);
    // Arrow keys move the settlement price, so the chart is a slider whose value reads out the P&L.
    box.tabIndex = 0;
    box.setAttribute("role", "slider");
    box.setAttribute("aria-label", t("chartLabel"));
    box.setAttribute("aria-valuemin", String(Math.round(lo)));
    box.setAttribute("aria-valuemax", String(Math.round(hi)));
  }
  const marker = box.querySelector(".now-marker");
  const inView = index >= lo && index <= hi;
  marker.style.display = inView ? "" : "none";
  if (inView) marker.setAttribute("transform", `translate(${geometry.x(index).toFixed(1)} 0)`);
  updateReadout();
}

function drawChart(option, lo, hi, width, height) {
  const pad = {top: 22, right: 4, bottom: 26, left: 4};
  const xs = [lo, option.strike, hi];
  const ys = xs.map((s) => Payoff.pnl(option, s));
  let top = Math.max(0, ...ys);
  let bottom = Math.min(0, ...ys);
  const span = top - bottom || 1;
  top += span * 0.12;
  bottom -= span * 0.12;
  const x = (s) => pad.left + ((s - lo) / (hi - lo)) * (width - pad.left - pad.right);
  const y = (v) => pad.top + ((top - v) / (top - bottom)) * (height - pad.top - pad.bottom);
  geometry = {x, y, lo, hi, pad, width, height};
  const zero = y(0).toFixed(1);
  const line = xs.map((s, i) => `${i ? "L" : "M"}${x(s).toFixed(1)} ${y(ys[i]).toFixed(1)}`).join("");
  const area = `${line}L${x(hi).toFixed(1)} ${zero}L${x(lo).toFixed(1)} ${zero}Z`;
  const bottomY = height - pad.bottom;
  const ticks = niceTicks(lo, hi, 4).filter((tick) => x(tick) > 18 && x(tick) < width - 18);
  const breakeven = Payoff.metrics(option).breakeven;
  return `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <defs>
      <linearGradient id="chartUp" gradientUnits="userSpaceOnUse" x1="0" y1="${pad.top}" x2="0" y2="${zero}">
        <stop class="stop-up" offset="0" stop-opacity="0.24"/><stop class="stop-up" offset="1" stop-opacity="0.02"/></linearGradient>
      <linearGradient id="chartDown" gradientUnits="userSpaceOnUse" x1="0" y1="${zero}" x2="0" y2="${bottomY}">
        <stop class="stop-down" offset="0" stop-opacity="0.02"/><stop class="stop-down" offset="1" stop-opacity="0.22"/></linearGradient>
      <clipPath id="clipUp"><rect x="0" y="-20" width="${width}" height="${(Number(zero) + 20).toFixed(1)}"/></clipPath>
      <clipPath id="clipDown"><rect x="0" y="${zero}" width="${width}" height="${(height - Number(zero) + 20).toFixed(1)}"/></clipPath>
    </defs>
    ${ticks.map((tick) => `<line class="grid" x1="${x(tick).toFixed(1)}" x2="${x(tick).toFixed(1)}" y1="${pad.top}" y2="${bottomY}"/><text x="${x(tick).toFixed(1)}" y="${height - 6}" text-anchor="middle">${compact(tick)}</text>`).join("")}
    <path class="area-up" d="${area}" clip-path="url(#clipUp)"/>
    <path class="area-down" d="${area}" clip-path="url(#clipDown)"/>
    <line class="zero" x1="0" x2="${width}" y1="${zero}" y2="${zero}"/>
    <path class="line line-up" d="${line}" clip-path="url(#clipUp)"/>
    <path class="line line-down" d="${line}" clip-path="url(#clipDown)"/>
    <g class="now-marker"><line class="now" x1="0" x2="0" y1="${pad.top - 2}" y2="${bottomY}"/><text class="now-label" x="0" y="${pad.top - 9}" text-anchor="middle">${escapeHtml(t("now"))}</text></g>
    ${breakeven && breakeven >= lo && breakeven <= hi ? `<circle class="breakeven" cx="${x(breakeven).toFixed(1)}" cy="${zero}" r="4"/>` : ""}
    <g class="scrub"><line x1="0" x2="0" y1="${pad.top - 2}" y2="${bottomY}"/><circle r="5.5"/></g>
  </svg>`;
}

function updateReadout() {
  const {option, valid, index} = model;
  const value = $("readoutValue");
  if (!valid || !isPositive(index)) {
    setText(value, "—");
    value.className = "readout-value";
    setText($("readoutNote"), "");
    return;
  }
  const settle = state.scrub ?? index;
  const pnl = Payoff.pnl(option, settle);
  setText(value, `${usdt(pnl, true)} USDT`);
  value.className = `readout-value ${pnl > 0 ? "positive" : pnl < 0 ? "negative" : ""}`;
  setText($("readoutNote"), t(state.scrub === null ? "ifStays" : "ifSettles", {price: whole(settle)}));
  const box = $("chart");
  box.classList.toggle("scrubbing", state.scrub !== null);
  box.setAttribute("aria-valuenow", String(Math.round(settle)));
  box.setAttribute("aria-valuetext", t("chartValue", {price: whole(settle), pnl: usdt(pnl, true)}));
  const scrub = box.querySelector(".scrub");
  if (!scrub || !geometry) return;
  const cx = geometry.x(settle).toFixed(1);
  scrub.querySelector("line").setAttribute("transform", `translate(${cx} 0)`);
  const dot = scrub.querySelector("circle");
  dot.setAttribute("cx", cx);
  dot.setAttribute("cy", geometry.y(pnl).toFixed(1));
  dot.style.stroke = pnl >= 0 ? "var(--green)" : "var(--red)";
}

function scrubTo(settle) {
  if (!geometry) return;
  state.scrub = settle === null ? null : Math.min(geometry.hi, Math.max(geometry.lo, settle));
  updateReadout();
}

function scrubFromPointer(event) {
  if (!geometry) return;
  const rect = $("chart").getBoundingClientRect();
  const ratio = (event.clientX - rect.left - geometry.pad.left) / (rect.width - geometry.pad.left - geometry.pad.right);
  scrubTo(geometry.lo + ratio * (geometry.hi - geometry.lo));
}

/* Appearance and language ---------------------------------------------------- */

const systemTheme = () => prefersDark.matches ? "dark" : "light";

function applyTheme() {
  if (state.theme) document.documentElement.dataset.theme = state.theme;
  else delete document.documentElement.dataset.theme;
  const label = t((state.theme ?? systemTheme()) === "dark" ? "themeLight" : "themeDark");
  $("themeButton").setAttribute("aria-label", label);
  $("themeButton").title = label;
}

function applyLanguage() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  for (const element of document.querySelectorAll("[data-t]")) setText(element, t(element.dataset.t));
  for (const element of document.querySelectorAll("[data-t-label]")) element.setAttribute("aria-label", t(element.dataset.tLabel));
  $("langButton").textContent = state.lang === "zh" ? "EN" : "中文";
  $("langButton").setAttribute("aria-label", t("switchLanguage"));
  $("langButton").title = t("switchLanguage");
  applyTheme();
  tableKey = chipsKey = chartKey = "";
}

/* Live connection ------------------------------------------------------------ */

let source = null;
let reconnectTimer = 0;
function connect() {
  source?.close();
  source = new EventSource("/api/events");
  source.onopen = () => {
    connection = "open";
    schedule();
  };
  source.onmessage = (event) => {
    connection = "open";
    try {
      ingest(JSON.parse(event.data));
    } catch {
      return;
    }
    schedule();
  };
  source.onerror = () => {
    connection = "lost";
    schedule();
    if (source.readyState === EventSource.CLOSED) {
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    }
  };
}

/* Events --------------------------------------------------------------------- */

function onPicker(id, handler) {
  $(id).addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (button) handler(button.dataset.value);
  });
}

onPicker("directionPicker", setDirection);
onPicker("sheetDirection", setDirection);
onPicker("sidePicker", setSide);

$("expiries").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip[data-expiry]");
  if (chip) selectExpiry(Number(chip.dataset.expiry));
});

$("chainBody").addEventListener("click", (event) => {
  const row = event.target.closest("tr.row");
  if (!row) return;
  tabSymbol = row.dataset.symbol;
  openInspector(row.dataset.symbol);
});

/* Up and down arrows walk the strikes; with the panel open they inspect each in turn. */
function stepRow(fromSymbol, delta) {
  const rows = [...$("chainBody").querySelectorAll("tr.row")];
  const at = rows.findIndex((r) => r.dataset.symbol === fromSymbol);
  const next = rows[at === -1 ? 0 : at + delta];
  if (!next) return;
  tabSymbol = next.dataset.symbol;
  for (const row of rows) row.querySelector(".strike").tabIndex = row === next ? 0 : -1;
  next.querySelector(".strike").focus();
  if ($("inspector").open) openInspector(next.dataset.symbol);
}

$("chainBody").addEventListener("keydown", (event) => {
  const row = event.target.closest("tr.row");
  if (!row || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
  event.preventDefault();
  stepRow(row.dataset.symbol, event.key === "ArrowDown" ? 1 : -1);
});

document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
  const target = event.target instanceof Element ? event.target : document.body;
  if (event.key === "Escape" && $("inspector").open && !$("inspector").matches(":modal")) {
    closeInspector();
    return;
  }
  if ((event.key === "ArrowDown" || event.key === "ArrowUp") && target === document.body && state.selected) {
    // After a mouse click nothing has focus yet; arrows still browse from the selected strike.
    event.preventDefault();
    stepRow(state.selected, event.key === "ArrowDown" ? 1 : -1);
    return;
  }
  if ((event.key !== "ArrowLeft" && event.key !== "ArrowRight") || target.closest("input, textarea, .chart")) return;
  const list = liveExpiries();
  const next = list[list.indexOf(state.expiry) + (event.key === "ArrowRight" ? 1 : -1)];
  if (next === undefined) return;
  event.preventDefault();
  selectExpiry(next);
  const chip = $("expiries").querySelector(`[data-expiry="${next}"]`);
  if (target.closest(".chip")) chip?.focus({preventScroll: true});
});

$("sheetClose").addEventListener("click", closeInspector);
$("inspector").addEventListener("scroll", (event) => event.target.classList.toggle("scrolled", event.target.scrollTop > 4), {passive: true});
$("inspector").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeInspector();
});
$("inspector").addEventListener("click", (event) => {
  // A click on the backdrop of the mobile sheet lands on the dialog itself.
  const sheet = $("inspector");
  if (event.target !== sheet || !sheet.matches(":modal")) return;
  const r = sheet.getBoundingClientRect();
  if (event.clientY < r.top || event.clientY > r.bottom || event.clientX < r.left || event.clientX > r.right) closeInspector();
});

wide.addEventListener("change", () => {
  const sheet = $("inspector");
  if (!sheet.open || !state.selected) return;
  sheet.close();
  document.body.classList.remove("inspecting");
  openInspector(state.selected);
});

$("priceInput").addEventListener("input", (event) => {
  const text = event.target.value.replace(/,/g, "").trim();
  state.customPrice = text === "" ? null : /^\d*\.?\d+$|^\d+\.$/.test(text) ? Number(text) : NaN;
  state.scrub = null;
  renderInspector();
});

$("priceLive").addEventListener("click", () => {
  if (state.customPrice === null) return;
  state.customPrice = null;
  $("priceInput").blur();
  renderInspector();
});

$("quantityInput").addEventListener("input", (event) => {
  const value = Number(event.target.value.replace(/,/g, "").trim());
  const ok = isPositive(value) && value <= 1e6;
  event.target.setAttribute("aria-invalid", String(!ok));
  if (!ok) return;
  state.quantity = value;
  saveSettings();
  renderInspector();
});

$("quantityInput").addEventListener("blur", (event) => {
  event.target.setAttribute("aria-invalid", "false");
  renderInspector();
});

function stepQuantity(direction) {
  const contract = contracts.get(state.selected);
  const step = contract?.minQty || 0.01;
  const steps = Math.round(state.quantity / step) + direction;
  state.quantity = Math.max(step, Math.round(steps * step * 1e8) / 1e8);
  saveSettings();
  renderInspector();
}
$("quantityDown").addEventListener("click", () => stepQuantity(-1));
$("quantityUp").addEventListener("click", () => stepQuantity(1));

const chartBox = $("chart");
chartBox.addEventListener("pointermove", scrubFromPointer);
chartBox.addEventListener("pointerdown", scrubFromPointer);
chartBox.addEventListener("pointerleave", () => scrubTo(null));
chartBox.addEventListener("keydown", (event) => {
  if (!geometry || !model?.valid) return;
  const step = (geometry.hi - geometry.lo) / 50;
  const from = state.scrub ?? model.index;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") scrubTo(from + (event.key === "ArrowRight" ? step : -step));
  else if (event.key === "Escape" && state.scrub !== null) scrubTo(null);
  else return;
  event.preventDefault();
  event.stopPropagation();
});
chartBox.addEventListener("blur", () => scrubTo(null));

// Swipe the mobile sheet down to dismiss it.
let drag = null;
for (const handle of [$("grabber"), document.querySelector(".sheet-head")]) {
  handle.addEventListener("pointerdown", (event) => {
    const sheet = $("inspector");
    if (!sheet.matches(":modal") || event.target.closest("button")) return;
    drag = {y: event.clientY, time: performance.now(), dy: 0};
    handle.setPointerCapture(event.pointerId);
    sheet.classList.add("dragging");
  });
  handle.addEventListener("pointermove", (event) => {
    if (!drag) return;
    drag.dy = Math.max(0, event.clientY - drag.y);
    $("inspector").style.transform = `translateY(${drag.dy}px)`;
  });
  const release = () => {
    if (!drag) return;
    const sheet = $("inspector");
    const fast = drag.dy / Math.max(1, performance.now() - drag.time) > 0.5;
    const dismiss = drag.dy > 120 || (fast && drag.dy > 24);
    drag = null;
    sheet.classList.remove("dragging");
    if (dismiss) {
      closeInspector();
    } else {
      sheet.style.transition = "transform 0.35s var(--ease)";
      sheet.style.transform = "";
      setTimeout(() => (sheet.style.transition = ""), 360);
    }
  };
  handle.addEventListener("pointerup", release);
  handle.addEventListener("pointercancel", release);
}

$("themeButton").addEventListener("click", () => {
  const next = (state.theme ?? systemTheme()) === "dark" ? "light" : "dark";
  state.theme = next === systemTheme() ? null : next;
  applyTheme();
  saveSettings();
});
prefersDark.addEventListener("change", applyTheme);

$("langButton").addEventListener("click", () => {
  state.lang = state.lang === "zh" ? "en" : "zh";
  saveSettings();
  applyLanguage();
  render();
});

// Dock the price in the navigation bar once the large price scrolls away.
new IntersectionObserver(([entry]) => document.body.classList.toggle("price-docked", !entry.isIntersecting),
  {rootMargin: "-52px 0px 0px 0px"}).observe($("indexPrice"));
// Give the toolbar its frosted background once it sticks under the navigation bar.
new IntersectionObserver(([entry]) => document.body.classList.toggle("toolbar-stuck", !entry.isIntersecting),
  {rootMargin: "-53px 0px 0px 0px"}).observe($("hero"));
new ResizeObserver(() => document.documentElement.style.setProperty("--toolbar-h", `${$("toolbar").offsetHeight}px`)).observe($("toolbar"));
new ResizeObserver(() => {
  chartKey = "";
  if ($("inspector").open) schedule();
}).observe(chartBox);

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) schedule();
});
setInterval(schedule, 1000); // countdowns and per-day values move with the clock

applyLanguage();
render();
connect();
