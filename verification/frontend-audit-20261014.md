# Frontend audit — 2026-10-14

All **198** automated frontend/model checks pass, across **9** Node suites. The earlier complete 196-check run is recorded in `frontend-suite-20261014.txt`; a subsequent wallet export follow-up added 2 checks and reran the complete wallet page suite (10/10 passed). The parent task performs the final aggregate run. These checks execute local code with mock network, sound, permissions and controlled time; they do not ring the user's alarm or modify saved user settings.

## Failures reproduced and repaired

1. **An open alarm page could freeze after the backend restarted.** Its previous revision number could exceed the restarted service's revision for a long time. The controller now compares the backend `instance_id`, accepts a new process's lower revision, and refuses delayed snapshots from retired processes. Older revisions of the same process are still ignored.
2. **A browser back/forward-cache return could leave the alarm stream closed.** `pagehide` closed SSE without a matching persisted `pageshow` reconnect. The lifecycle now reconnects, restores freshness status, preserves module iframe instances and ignores obsolete stream callbacks.
3. **Editing an alarm threshold while a save was pending could lose the newer edit.** A completed save previously cleared the entire dirty state. The controller now records the submitted form generation, preserves later input and explicitly reports that the later edit still needs saving.
4. **An old asynchronous combination refresh could corrupt a reopened combination.** Its global lock blocked the new dialog's refresh, and its rejection could display an error in the new dialog. A reopened dialog starts its own refresh state; retired callbacks cannot change the new context or unlock its pending request.

Each repair has a regression that failed against the original implementation before the repair passed.

## Verification commands and counts

| Command | Passing checks |
| --- | ---: |
| `node test_terminal_frontend.js` | 51 |
| `node test_terminal_ui.js` | 12 |
| `node test_options_embed.js` | 8 |
| `node test_frontend_data.js` | 32 |
| `node test_option_payoff.js` | 18 |
| `node test_option_portfolio.js` | 32 |
| `node test_option_preview_ui.js` | 10 |
| `node terminal/wallet/test_wallet_core.mjs` | 25 |
| `node terminal/wallet/test_wallet_page.mjs` | 10 |
| **Total** | **198** |

## Coverage

- **Navigation and embedding:** all three routes, aliases and direct links; back/forward state; keyboard wrapping; one persistent options iframe; retaining wallet iframe; origin/source/active-page checks for focus messages; focus exit by Escape and navigation; informational child heights cannot resize the options viewport or create scroll feedback.
- **Alert page:** timezone labels, missing/zero/negative formatting; live versus stale/disconnected/waiting/uncalibrated market states; real controller recovery from failed bootstrap and malformed SSE; quote history sorting, deduplication and bounded rendering; settings validation, failed writes, draft preservation and pause/resume; process restarts and browser backcache; notification hydration, duplicate/old/test/future suppression and user disabling; sound preview rejection, stop, replacement and old-callback races. Audio tests use mocked `Audio` and never claim the user heard a completed playback call.
- **Options:** quote and IV precision; fresh per-field websocket data survives late REST; revision/instance handling; official expiry milliseconds and calibrated time; ask buys/bid sells for Call and Put; stale-source labels; all/future expiry selection and automatic expiry rollover; frozen selected leg prices; repeated selection toggles; clear-filters behavior; combo refresh/removal; statistics missing versus real zero and cache warnings; drawer focus trapping and nested Escape.
- **Profit/loss models and dialogs:** all four single-leg directions; theoretical finite/unlimited bounds; fees and quantity/unit scaling; exact zero-price settlements; invalid/negative/nonfinite/overflow input; many-leg piecewise roots and zero intervals; bounded spreads at enormous prices; exact decimal hedges and genuine microscopic residual risks; expiry while idle or editing; quote removal/refresh recovery; preserved scenario, quantities and fees; no positive reference quote requires explicit custom premium; different exact expiry times and fewer than two legs rejected; retired asynchronous dialog requests isolated.
- **Wallet:** historical price/FX lookup never uses a future observation; confirmed-only integer-satoshi replay, intra-block dependencies, exact zero holdings, duplicate/incomplete/address mismatch rejection and real snapshot reconciliation; cash-flow adjusted day/7/30/90-day profit; missing valuation remains unavailable; actual page currency/period/range controls and refresh recovery; local proxy routing versus independent file export providers; embedded Escape/height; private embeddings do not access browser wallet storage; wrong-address cache isolation; malformed, future or duplicate refresh data cannot replace a reconciled display. The real save handler is exercised through clone/Blob/object-URL/link boundaries: the exported HTML contains the latest validated snapshot, exported data replays to the same balance, transient controls are reset only in the clone, no network request occurs on save, URLs survive until the 1,000 ms cleanup boundary, failed refreshes export the previous valid snapshot, and script delimiters are escaped. Ordinary exports have no private-embed marker; marked isolated embeddings preserve their storage isolation by design.

## Scope of the evidence

The automated frontend run does not prove future exchange/provider uptime, the system's audible output, a physical Windows reboot, or rendering in every browser. The parent task separately performs browser smoke checks and startup integration checks. No external publication, trading, email delivery or production wallet transaction is performed by these tests.
