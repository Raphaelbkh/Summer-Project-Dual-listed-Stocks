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

## Temporary Live Market Data Diagnostic

Normal development uses IB Gateway Paper on port `4002`.

If IBKR returns Error `10197` (`No market data during competing live session`)
in paper mode, you can temporarily test whether live-account market data works
through IB Gateway Live on port `4001`.

This diagnostic mode is only for market data. It must not be used for live
order placement. Keep `ENABLE_LIVE_TRADING=false`, and do not run any future
order/execution scripts while diagnosing data access.

PowerShell live diagnostic:

```powershell
$env:IBKR_MODE="live"
$env:IBKR_USE_GATEWAY="true"
$env:IBKR_PORT="4001"
$env:ENABLE_LIVE_TRADING="false"
python scripts/test_ibkr_connection.py
python scripts/test_ibkr_live_data_diagnostic.py
```

After testing, switch back to paper:

```powershell
$env:IBKR_MODE="paper"
$env:IBKR_USE_GATEWAY="true"
$env:IBKR_PORT="4002"
$env:ENABLE_LIVE_TRADING="false"
python scripts/test_ibkr_connection.py
python scripts/test_ibkr_equity_quote.py
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

## Offline Walk-Forward Backtesting With TradingView CSV

TradingView CSV backtesting is offline research only. It does not connect to
IBKR and does not place orders. IBKR remains the live market data and future
paper/live broker backend.

Use TradingView CSV exports to validate historical strategy behavior before any
paper execution work. Each pair uses its own true common start date:

```text
max(long_leg_first_timestamp, short_leg_first_timestamp, fx_first_timestamp)
```

If `backtest_start_override` is present in `data/mappings/backtest_pairs.csv`,
the later of that override and the true common start is used. This lets Tieto
and Stora Enso start in 2009, while Nokia starts in 2015 because the Swedish
NOKIA SEK data begins on `2015-08-10`. EURSEK starts in 2008 and is no longer
the limiting file for these pairs.

Training and test periods must be separated. The engine fits parameters on the
training period, freezes them, and then processes the test period bar by bar
using only data available up to each timestamp.

TradingView OHLCV bars are not executable bid/ask data. Backtest results must
therefore include conservative assumptions for half-spread, slippage, and
commission.

The simulated broker sizes each pair trade from `initial_capital_base_ccy` and
`capital_fraction_per_trade`. PnL is reported in the configured base currency
(`SEK` by default), with trade output broken down by leg: quantities, entry/exit
prices, notional, gross PnL, commission, and net PnL. For research sanity checks,
`--invert-signals` flips long/short pair entries without changing the model.

Example workflow:

1. Export 1h TradingView CSV files for both pair legs and FX if needed.
2. Save files in `data/historical/tradingview`.
3. Add rows to `data/mappings/backtest_pairs.csv` with `long_csv_file`,
   `short_csv_file`, optional `fx_csv_file`, `active`, and optional
   `backtest_start_override`.
4. Check CSV and pair coverage.
5. Run the walk-forward backtest.
6. Inspect `summary.csv`, `windows.csv`, trades, signals, spread, and equity curve in
   `data/backtests/<timestamp>/`.

Example command:

```powershell
python scripts/check_historical_csv_coverage.py
python scripts/check_pair_coverage.py
python scripts/backtest_tradingview_walk_forward.py --pair-id nokia_fi_se
python scripts/backtest_tradingview_walk_forward.py --pair-id nokia_fi_se --invert-signals
```

Research diagnostics:

```powershell
python scripts/backtest_tradingview_walk_forward.py --pair-id tieto_fi_se --min-expected-edge-bps 20
python scripts/run_cost_sensitivity.py --pair-id tieto_fi_se
python scripts/research_tieto_parameters.py
python scripts/walk_forward_optimize_tieto.py
```

`research_tieto_parameters.py` is research only. Choosing the best parameter
set using all out-of-sample years can overfit. Final validation should use
walk-forward optimization, where parameters are selected using only training
data and locked before each test year.

The normal backtest exports edge and cost diagnostics in `summary.csv`, adds
entry edge/cost fields to signals and trades, and writes
`<pair_id>_trade_buckets.csv` so trades can be grouped by entry z-score, entry
edge, holding period, and UTC entry hour.

## Future Paper Execution

Future execution can use the same IBKR TWS API architecture through a paper
account. It must remain separate from observe scripts and must be guarded by
configuration flags. Tests must never place paper or live orders.
