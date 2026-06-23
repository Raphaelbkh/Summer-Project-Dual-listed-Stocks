# Tieto 30m Paper-Readiness Checklist

This workflow is market-data validation and dry-run signal logging only. It does
not construct or submit orders.

## Preconditions

- TWS or IB Gateway is logged into the paper account.
- API access is enabled and `ibkr.mode` remains `paper`.
- `execution.observe_only` and `paper_readiness.dry_run` remain `true`.
- `ENABLE_LIVE_TRADING` is unset or false.
- Tieto Stockholm, Tieto Helsinki, and EURSEK market-data permissions are valid.

## 1. Validate contracts

```powershell
python scripts/validate_tieto_paper_readiness.py --step contracts
```

Confirm a non-empty result for Tieto Finland, Tieto Sweden, and EURSEK. Review
conId, exchange, currency, trading class, and local symbol. Stop if any contract
fails qualification or identifies the wrong listing.

## 2. Validate market data

Live subscriptions:

```powershell
python scripts/validate_tieto_paper_readiness.py --step snapshot --market-data-type 1
```

Delayed fallback for diagnostics:

```powershell
python scripts/validate_tieto_paper_readiness.py --step snapshot --market-data-type 3
```

Snapshots are written to `data/paper/snapshots/`. Confirm positive bid/ask,
correct currencies, current UTC timestamps, and plausible mids for all legs.

## 3. Validate spread and policy

```powershell
python scripts/validate_tieto_paper_readiness.py --step monitor --direction SHORT_SWEDEN_LONG_FINLAND --action ENTRY --zscore 2.0
```

The output reports Finland mid converted to SEK, mid spread, and conservative
bid/ask executable spread in both directions. Signals at 15:00 or 16:00 UTC are
logged but blocked. Exit actions remain allowed at every hour.

Signal logs are written to `data/paper/signals/`. `would_trade_boolean` is a
dry-run decision marker; it never submits an order.

## 4. Produce daily report

```powershell
python scripts/generate_tieto_paper_daily_report.py --date YYYY-MM-DD
```

Reports are written to `data/paper/reports/` and summarize signal counts,
policy blocks, spread levels, quote spreads, and missing market data.

## Readiness gates

- Contracts resolve consistently across restarts.
- No missing or stale market data during the intended session.
- Executable bid/ask spreads agree with manual TWS inspection.
- Excluded-hour entries are always blocked and logged.
- Exit decisions are never blocked by the entry-hour policy.
- Daily reports are reviewed for at least several paper sessions.
- Any future order path must remain paper-only, separately reviewed, and guarded
  by reconciliation, exposure limits, max-loss controls, and a kill switch.
