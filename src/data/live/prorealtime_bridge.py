"""Helpers for building ProRealTime bridge inputs from the user watchlist."""

from pathlib import Path

import pandas as pd

from src.data.mappings.watchlist import load_user_watchlist, normalize_ticker


BRIDGE_WATCHLIST_COLUMNS = ["ticker", "notes"]


def build_prorealtime_bridge_watchlist(user_watchlist: pd.DataFrame) -> pd.DataFrame:
    """Build a ProRealTime bridge input without adding or suggesting tickers."""
    rows = []
    for _, row in user_watchlist.iterrows():
        ticker = normalize_ticker(row["ticker"])
        if ticker == "PLACEHOLDER_TICKER":
            continue
        rows.append(
            {
                "ticker": ticker,
                "notes": str(row.get("notes", "")),
            }
        )
    return pd.DataFrame(rows, columns=BRIDGE_WATCHLIST_COLUMNS)


def write_prorealtime_bridge_watchlist(
    user_watchlist_path: Path,
    output_path: Path,
) -> Path:
    """Write bridge watchlist rows from user-provided tickers only."""
    user_watchlist = load_user_watchlist(user_watchlist_path)
    bridge_watchlist = build_prorealtime_bridge_watchlist(user_watchlist)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_watchlist.to_csv(output_path, index=False)
    return output_path
