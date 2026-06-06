# Next Phase Risk And Execution Plan

This document describes possible future phases after the observe-only MVP. It
does not implement order placement, order construction, live trading, or
automatic pair selection.

## Phase Principles

The user-selected universe remains the default workflow. The system should
continue to start from tickers supplied by the user and should process only rows
that the user has manually approved.

Optional future research screening may suggest candidate tickers, but suggested
candidates must never be auto-activated. Any future candidate must be manually
reviewed before `active=true` is set.

## Future Phases

1. Stabilize the observe-only monitor.
2. Add paper trading mode behind explicit configuration.
3. Add pre-trade risk checks.
4. Add position sizing rules.
5. Add borrow and short availability checks.
6. Design order construction separately from the observe-only monitor.
7. Add simulated fills for paper trading.
8. Add broker reconciliation.
9. Add a kill switch.
10. Define a live order enablement process.

## Safety Gates

- The observe-only monitor must run reliably before any execution work begins.
- Paper trading must run before live trading.
- All live trading requires explicit configuration confirmation.
- A kill switch is required before live trading.
- Broker reconciliation is required before live trading.
- Max loss controls are required before live trading.
- Max exposure controls are required before live trading.
- User approval is required before any new pair becomes active.

## Non-Goals For The MVP

- No order placement.
- No order construction.
- No live trading enablement.
- No automatic pair activation.
- No automatic stock selection.
