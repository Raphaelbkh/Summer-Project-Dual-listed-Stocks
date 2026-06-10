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
- Oslo / Oslo Børs / Euronext Oslo
- TradingView as a backend
- Nordnet as the primary live source
- Nasdaq direct feed

## Data Sources

- IG API is now the preferred backend integration for demo/paper launch.
- ProRealTime DDE/CSV is now the preferred paper-launch quote bridge.
- ProRealTime exports live quotes through DDE into external software such as
  Excel or LibreOffice; this project reads those exported rows from
  `data/prorealtime/live_quotes.csv`.
- IBKR providers remain in the codebase as an optional fallback.
- IBKR Nordic Equity L1 can be used as a live equity quote source.
- IBKR IDEALPRO can be used as a live FX quote source.
- Börsdata (Borsdata) is for historical research, EOD data, fundamentals, and earnings.
- Börsdata is not a live signal source.

Expected ProRealTime bridge CSV columns:

```csv
kind,symbol,exchange,currency,pair,bid,ask,bid_size,ask_size,last,timestamp
```

Equity rows use `kind=equity` plus `symbol`, `exchange`, and `currency`. FX
rows use `kind=fx` plus `pair`, for example `EURSEK`.

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

## ProRealTime Setup

ProRealTime must be open with the relevant instruments displayed in lists. Use
the ProRealTime DDE data export window to export bid/ask, last, and related
fields into a spreadsheet or local bridge that updates
`data/prorealtime/live_quotes.csv`.

The project does not place ProRealTime orders and does not automate ProOrder in
the MVP.

## IG API Setup

Create a local `.env` file from `.env.example` and fill in the demo Web API
credentials. Do not commit `.env`.

```powershell
copy .env.example .env
```

Required values:

```text
IG_API_KEY=...
IG_USERNAME=...
IG_PASSWORD=...
IG_ACCOUNT_ID=...   # optional; use when selecting a specific CFD account

IG_LIVE_API_KEY=...
IG_LIVE_USERNAME=...
IG_LIVE_PASSWORD=...
IG_LIVE_ACCOUNT_ID=...   # optional live market-data account

IG_DEMO_API_KEY=...
IG_DEMO_USERNAME=...
IG_DEMO_PASSWORD=...
IG_DEMO_ACCOUNT_ID=...   # optional demo/paper account
```

Then test demo API login:

```powershell
python scripts/test_ig_connection.py
```

Search IG demo markets and inspect available epics:

```powershell
python scripts/test_ig_market_search.py AAPL EUR/USD
```

Test IG's prices endpoint for known epics:

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
Make sure the real-time share data subscription is active on the same account
that the API session uses. The connection script prints visible API accounts.

The intended next-phase architecture is split by environment:

- IG live API: market data only, observe-only, no orders.
- IG demo API: future paper execution only, disabled in the current codebase.
- Live order placement is not implemented.

## IBKR Setup

TWS or IB Gateway must be running, and the IBKR API must be enabled. The default
IBKR fallback configuration uses paper mode with TWS paper port `7497`.

Live trading is not enabled in this MVP.

## Commands

```powershell
python scripts/resolve_watchlist.py
python scripts/test_ibkr_connection.py
python scripts/test_ibkr_fx.py
python scripts/test_ibkr_equity_quote.py
python scripts/test_ig_connection.py
python scripts/test_ig_market_search.py AAPL EUR/USD
python scripts/test_ig_prices.py CS.D.EURUSD.CEE.IP
python scripts/test_ig_live_prices.py UD.D.TSLA.CASH.IP
python scripts/observe_ibkr_spreads.py
```

## Executable Spread Logic

Live spread calculation uses tradable prices:

- Buy leg uses ask.
- Sell leg uses bid.
- FX conversion uses the configured live FX provider bid/ask.
- Cost buffer is deducted from gross edge.
- Last and mid are diagnostics only, never live signal inputs.

## Safety

No orders are placed in the MVP. All signals are observations. Live trading
requires a separate phase with paper trading, risk controls, reconciliation, and
a kill switch.
