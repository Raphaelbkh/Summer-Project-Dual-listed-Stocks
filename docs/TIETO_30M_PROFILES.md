# Tieto 30m Profiles

## Research baseline: all hours

The offline research baseline uses `tieto_fi_se`, 30-minute bars, lookback 400,
entry z-score 2.0, exit z-score 1.0, minimum expected edge 65 bps, and capital
fraction 0.25. All UTC entry hours remain available for research.

## Paper-start baseline: exclude 15/16 UTC

The initial paper profile uses the same parameters but blocks new entries at
15:00 and 16:00 UTC. Exits remain allowed at every hour.

Signals during the excluded hours are observations, not execution candidates.
They are logged with available equity and EURSEK bid/ask data for comparison
against later paper fills and IBKR market-data observations.

The exclusion is deliberately conservative. Research indicates that hours 15
and 16 contribute a large share of total PnL, but that concentration may include
closing-bar, auction, stale-print, or candle-close effects. The all-hours profile
therefore remains available for research while paper-start uses the exclusion.

No profile enables live order placement.
