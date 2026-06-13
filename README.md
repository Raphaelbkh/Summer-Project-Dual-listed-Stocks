# Dual-Listed Arbitrage Monitor

Observe-only monitor for user-selected dual-listed or triple-listed Nordic
equities. The MVP watches manually approved pairs, fetches executable bid/ask
quotes from Interactive Brokers, calculates spread snapshots, and logs
observations to CSV.

## Architecture

IBKR is the sole backend provider for the project.

- Real-time Nordic equity data: IBKR TWS API through IB Gateway or TWS.
- FX quotes: IBKR IDEALPRO through the same TWS API architecture.
- Future paper execution: IBKR paper account through TWS API.
- IB Gateway paper mode is recommended for a continuously running local monitor.

The project does not use a web API backend for IBKR. Authentication is handled
by logging in to TWS or IB Gateway locally.

## MVP Scope

Included markets:

- Sweden / Nasdaq Stockholm / SEK
- Finland / Nasdaq Helsinki / EUR
- Denmark / Nasdaq Copenhagen / DKK

Excluded from the MVP:

- Automatic stock discovery
- Automatic screening
- AI-generated tickers
- Automatic pair activation
- Live order placement

Real-time Nordic market data requires active IBKR market data subscriptions for
the relevant exchanges. Delayed data should not be assumed sufficient for live
spread monitoring.

## Safety

The MVP is observe-only.

- `execution.observe_only` defaults to `true`.
- Paper mode is the default IBKR mode.
- The observe script does not place orders.
- Future order support must be paper-first and guarded behind explicit live
  trading flags.
- Live trading requires a separate phase with risk controls, reconciliation,
  kill switch, and explicit configuration.

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

Run either TWS or IB Gateway locally.

Recommended:

- IB Gateway
- Paper trading mode
- API access enabled
- Socket clients enabled
- Read-only API is acceptable for the observe-only MVP

Default ports:

- TWS paper: `7497`
- TWS live: `7496`
- IB Gateway paper: `4002`
- IB Gateway live: `4001`

Create a local `.env` file from `.env.example` if you want environment notes for
your local setup. The application does not need IBKR username/password/API keys
in `.env`; those belong in TWS or IB Gateway login.

```powershell
copy .env.example .env
```

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Commands

Run tests:

```powershell
python -m pytest
```

Check local paper connection:

```powershell
python scripts/test_ibkr_connection.py
```

Resolve user watchlist:

```powershell
python scripts/resolve_watchlist.py
```

Test FX quote:

```powershell
python scripts/test_ibkr_fx.py
```

Test equity quote:

```powershell
python scripts/test_ibkr_equity_quote.py
```

Run observe-only monitor:

```powershell
python scripts/observe_ibkr_spreads.py
```

## Executable Spread Logic

Live spread calculation uses tradable prices:

- Buy leg uses ask.
- Sell leg uses bid.
- FX conversion uses bid/ask.
- Cost buffer is deducted from gross edge.
- Last and mid are diagnostics only, never live signal inputs.

## Future Paper Execution

Future execution can use the same IBKR TWS API architecture through a paper
account. It must remain separate from observe scripts and must be guarded by
configuration flags. Tests must never place paper or live orders.
