# Potential Trade Alerts – tracker of stocks we picked but have not entered

Code only. No broker, no orders, no Claude unless someone asks.

**What it does (Nitin, 13 Nov 2026).** We pick a stock on its chart and expect it to go our way. When we add it, the
code notes its price (CMP) and **our level** – the price at which we would invest (for example CMP ₹100, invest if it
goes to ₹102). Then, on trading days, 9:15 am – 3:30 pm IST:

- **Every hour (10:15, 11:15, 12:15, 1:15, 2:15, 3:15)** two separate Slack messages, tagging Nitin and his two friends,
  with one chart per stock:
  - `#potential-trades-positive` – stocks moving **our way**: price now vs the price when added (% and ₹ a share),
    and whether our level is crossed or how far it still is;
  - `#potential-trades-negative` – stocks going **against us**: how much, how far our level now is, and the
    wrong-way level if one was set.
- **Instantly** (checked every 3 minutes, confirmed by a second price source): a 🎯 message when a stock crosses our
  level, and a ⚠️ message when it crosses the wrong-way level (if set).
- **Once we enter a trade it leaves this tracker** – Trade Watch takes over. Reply `entered SYMBOL`, or the code sees
  the new trade in Trade Watch's "Your trades" post in #trade-watch.

**The chart** uses the Trade Analyzer / Stock Deep Check logic (`dc_core.py`, a copy of `deep_check/core.py`):
trendlines only with 3+ touches (within 1%, 5+ bars apart, no close more than 1% through), support/resistance with
touch counts, floor/ceiling zones, decision points (a rising or falling line meeting a horizontal level), 50/200-day
averages and RSI(14) – on the daily chart with the weekly lines carried down, and on the hourly chart with the daily
and weekly levels carried down. Each block links to the full Trade Analyzer view of that stock.

## Commands (in either channel, or in a thread there; only Nitin and his two friends)
`track SYMBOL up 102` (or `down`; optional `sl 97` wrong-way level, `t 110` target, `why …`) · `remove SYMBOL` ·
`entered SYMBOL` · `list` · `chart SYMBOL` · `update` (post the hourly update now) · `check SYMBOL` (Claude, only
if connected; otherwise ask in the Claude chat "Potential Trade Alerts").

## Safety and privacy
- `net.py` allows only: the free price pages (Yahoo Finance chart API with its session cookie, TradingView's public scanner as a bad-tick check), Slack, the
  optional Claude routine, and this repository's own runs. There is no broker at all – nothing here can trade.
- The watch list (`watchlist.enc`) is **encrypted** (key in the secret `WATCHLIST_KEY`): this public repository shows
  the code, never the stocks, levels or Slack IDs. Run logs print counts only.
- Memory (what was posted, threads, a 30-day event log) is kept in GitHub's job cache, not in the repository.
- Prices come from a free feed – fine for tracking. Any number behind a real decision comes from INDmoney (rule G20).

## Files
`tracker.py` the tracker · `analysis.py` chart reading on weekly/daily/hourly · `dc_core.py` Deep Check logic ·
`chart.py` the picture · `feed.py` free prices · `slackapi.py` Slack · `vault.py` encryption · `net.py` allowed web
calls · `ghruns.py` hand-over between runs · `.github/workflows/track.yml` the schedule ·
`tests/test_offline.py` a full trading day replayed offline (`python3 tests/test_offline.py -v`).

## Secrets (Settings → Secrets and variables → Actions)
`WATCHLIST_KEY` (decrypts the watch list) · `SLACK_BOT_TOKEN` (the "Potential Trade Alerts" Slack app) ·
optional `CLAUDE_ROUTINE_URL` / `CLAUDE_ROUTINE_TOKEN` (only for `check SYMBOL`).
