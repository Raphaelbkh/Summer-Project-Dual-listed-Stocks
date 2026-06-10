# Dual-Listed Arbitrage Monitor

Observe-only monitor for user-selected dual-listed or triple-listed Nordic
equities. The MVP watches manually approved pairs, fetches executable bid/ask
quotes, calculates spread snapshots, and logs observations to CSV.

## MVP Scope

Included markets:

- Sweden / Nasdaq Stockholm / SEK
- Finland / Nasdaq Helsinki / EUR
- Denmark / Nasdaq Copenhagen / DKK

Excluded from the MVP:

- Norway
- NOK
- Oslo / Oslo Bors / Euronext Oslo
- TradingView as a backend
- Nordnet as the primary live source
- Nasdaq direct feed

## Target Architecture

The intended architecture is split by account/environment:

- IG live Web API: live market data only.
- IG demo Web API: future demo/paper execution only.
- ProRealTime: visual review of trades, P&L, and equity curve.
- Live order placement is not implemented.

The system should not use ProRealTime as the primary quote backend when IG live
Web API credentials and live market data permissions are available.

## Data Sources

- IG live Web API is the intended live market data source.
- IG demo Web API is reserved for demo/paper connectivity and future paper
  execution.
- ProRealTime is for monitoring and visual review, not primary backend data.
- IBKR providers remain in the codebase as an optional fallback.
- Borsdata is for historical research, EOD data, fundamentals, and earnings.
- Borsdata is not a live signal source.

## Watchlist Workflow

The user only fills ticker values in:

```text
data/mappings/user_watchlist.csv
```

Then run:

```powershell
python scripts/resolve_watchlist.py
```

The system writes internal mapping files:

- `data/mappings/resolved_listings.csv`
- `data/mappings/resolved_pairs.csv`

The system does not choose stocks, recommend stocks, scan the universe, or
auto-activate pairs. The user manually reviews `resolved_pairs.csv` and manually
sets `active=true` for approved rows. The observe script processes only rows
where `active=true`.

## IG API Setup

Create a local `.env` file from `.env.example`. Fill live credentials for market
data and demo credentials for paper/demo execution tests. Do not commit `.env`.

```powershell
copy .env.example .env
```

Required values for live market data:

```text
IG_LIVE_API_KEY=...
IG_LIVE_USERNAME=...
IG_LIVE_PASSWORD=...
IG_LIVE_ACCOUNT_ID=...
```

Required values for demo API connectivity:

```text
IG_DEMO_API_KEY=...
IG_DEMO_USERNAME=...
IG_DEMO_PASSWORD=...
IG_DEMO_ACCOUNT_ID=...
```

Legacy demo variables are still supported by older scripts:

```text
IG_API_KEY=...
IG_USERNAME=...
IG_PASSWORD=...
IG_ACCOUNT_ID=...
```

Test demo API login:

```powershell
python scripts/test_ig_connection.py
```

Search IG demo markets and inspect available epics:

```powershell
python scripts/test_ig_market_search.py AAPL EUR/USD
```

Test IG demo prices endpoint for known epics:

```powershell
python scripts/test_ig_prices.py CS.D.EURUSD.CEE.IP
python scripts/test_ig_prices.py UD.D.TSLA.CASH.IP
```

Test live-account market data only:

```powershell
python scripts/test_ig_live_prices.py UD.D.TSLA.CASH.IP
```

If equity epics return `unauthorised.access.to.equity.exception`, the API login
works but that IG account/environment is not entitled to equity price data.
Check that real-time exchange data is active for the same live account used by
the Web API.

## ProRealTime Setup

ProRealTime can be used to review results, trades, P&L, and equity curve. It is
not the primary source for automated live quotes in the intended architecture.
The project does not place ProRealTime orders and does not automate ProOrder in
the MVP.

## IBKR Setup

TWS or IB Gateway must be running, and the IBKR API must be enabled if using the
optional IBKR fallback. The default IBKR fallback configuration uses paper mode
with TWS paper port `7497`.

Live trading is not enabled in this MVP.

## Commands

```powershell
python scripts/resolve_watchlist.py
python scripts/test_ig_connection.py
python scripts/test_ig_market_search.py AAPL EUR/USD
python scripts/test_ig_prices.py CS.D.EURUSD.CEE.IP
python scripts/test_ig_live_prices.py UD.D.TSLA.CASH.IP
python scripts/observe_ibkr_spreads.py
```

Optional legacy/fallback diagnostics:

```powershell
python scripts/test_ibkr_connection.py
python scripts/test_ibkr_fx.py
python scripts/test_ibkr_equity_quote.py
python scripts/test_prorealtime_quotes.py
```

## Executable Spread Logic

Live spread calculation uses tradable prices:

- Buy leg uses ask.
- Sell leg uses bid.
- FX conversion uses bid/ask.
- Cost buffer is deducted from gross edge.
- Last and mid are diagnostics only, never live signal inputs.

## Safety

No orders are placed in the MVP. All signals are observations. Demo execution is
a future phase and must use IG demo API only. Live trading requires a separate
phase with paper trading, risk controls, reconciliation, and a kill switch.
