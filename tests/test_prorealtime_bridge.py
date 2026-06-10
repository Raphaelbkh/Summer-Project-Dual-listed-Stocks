from pathlib import Path

import pandas as pd

from src.data.live.prorealtime_bridge import (
    build_prorealtime_bridge_watchlist,
    write_prorealtime_bridge_watchlist,
)


def test_build_bridge_watchlist_uses_user_tickers_only() -> None:
    df = pd.DataFrame(
        {
            "ticker": [" noki ", "NOVO-B"],
            "notes": ["Sweden/Finland", "Denmark"],
        }
    )

    bridge_df = build_prorealtime_bridge_watchlist(df)

    assert bridge_df["ticker"].tolist() == ["NOKI", "NOVO-B"]
    assert set(bridge_df.columns) == {"ticker", "notes"}


def test_build_bridge_watchlist_skips_placeholder() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["PLACEHOLDER_TICKER"],
            "notes": ["User fills tickers only"],
        }
    )

    bridge_df = build_prorealtime_bridge_watchlist(df)

    assert bridge_df.empty


def test_write_bridge_watchlist_creates_output(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "user_watchlist.csv"
    output_path = tmp_path / "data" / "prorealtime" / "watchlist_import.csv"
    watchlist_path.write_text("ticker,notes\nNOKI,test\n", encoding="utf-8")

    written_path = write_prorealtime_bridge_watchlist(watchlist_path, output_path)

    assert written_path == output_path
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "ticker,notes",
        "NOKI,test",
    ]
