# Dual-Listed Arbitrage Monitor

Observe-only monitor for user-selected dual-listed or triple-listed Nordic
equities. The MVP watches manually approved pairs, fetches executable bid/ask
quotes from IBKR, calculates spread snapshots, and logs observations to CSV.

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

- IBKR Nordic Equity L1 is the live equity quote source.
- IBKR IDEALPRO is the live FX quote source.
- Börsdata (Borsdata) is for historical research, EOD data, fundamentals, and earnings.
- Börsdata is not a live signal source.

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

## IBKR Setup

TWS or IB Gateway must be running, and the IBKR API must be enabled. The default
configuration uses paper mode with TWS paper port `7497`.

Live trading is not enabled in this MVP.

## Commands

```powershell
python scripts/resolve_watchlist.py
python scripts/test_ibkr_connection.py
python scripts/test_ibkr_fx.py
python scripts/test_ibkr_equity_quote.py
python scripts/observe_ibkr_spreads.py
```

## Executable Spread Logic

Live spread calculation uses tradable prices:

- Buy leg uses ask.
- Sell leg uses bid.
- FX conversion uses IBKR IDEALPRO bid/ask.
- Cost buffer is deducted from gross edge.
- Last and mid are diagnostics only, never live signal inputs.

## Safety

No orders are placed in the MVP. All signals are observations. Live trading
requires a separate phase with paper trading, risk controls, reconciliation, and
a kill switch.
