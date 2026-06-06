from datetime import datetime, timezone

import pandas as pd

from src.data.live.quote_models import EquityQuote, FXQuote, SpreadSnapshot
from src.logging.csv_logger import (
    append_dataclass_to_daily_csv,
    append_dataframe_to_csv,
    log_equity_quote,
    log_fx_quote,
    log_spread_snapshot,
)


NOW = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def equity_quote(symbol: str = "ABC") -> EquityQuote:
    return EquityQuote(
        symbol=symbol,
        exchange="NASDAQ STOCKHOLM",
        currency="SEK",
        bid=100.0,
        ask=101.0,
        bid_size=10.0,
        ask_size=12.0,
        last=100.5,
        timestamp=NOW,
        contract_id=123,
    )


def fx_quote() -> FXQuote:
    return FXQuote(
        pair="EURSEK",
        base_currency="EUR",
        quote_currency="SEK",
        bid=11.0,
        ask=11.1,
        last=11.05,
        timestamp=NOW,
    )


def spread_snapshot() -> SpreadSnapshot:
    return SpreadSnapshot(
        timestamp=NOW,
        pair_id="PAIR",
        long_leg_symbol="ABC",
        short_leg_symbol="ABC",
        long_leg_exchange="NASDAQ STOCKHOLM",
        short_leg_exchange="NASDAQ HELSINKI",
        long_leg_currency="SEK",
        short_leg_currency="EUR",
        long_leg_ask=101.0,
        short_leg_bid=9.2,
        fx_pair="EURSEK",
        fx_bid=11.0,
        fx_ask=11.1,
        gross_edge=0.001,
        cost_buffer_bps=20.0,
        net_edge=-0.001,
        signal=False,
        rejection_reason="NET_EDGE_BELOW_THRESHOLD",
    )


def test_file_is_created(tmp_path) -> None:
    path = append_dataclass_to_daily_csv(equity_quote(), tmp_path, "quotes")

    assert path.exists()
    assert path.name == "quotes_20260102.csv"


def test_header_is_written_once(tmp_path) -> None:
    append_dataclass_to_daily_csv(equity_quote("ABC"), tmp_path, "quotes")
    path = append_dataclass_to_daily_csv(equity_quote("DEF"), tmp_path, "quotes")

    lines = path.read_text(encoding="utf-8").splitlines()

    assert lines[0].startswith("symbol,exchange,currency")
    assert sum(line.startswith("symbol,exchange,currency") for line in lines) == 1


def test_appending_two_objects_creates_two_data_rows_and_one_header(tmp_path) -> None:
    append_dataclass_to_daily_csv(equity_quote("ABC"), tmp_path, "quotes")
    path = append_dataclass_to_daily_csv(equity_quote("DEF"), tmp_path, "quotes")

    df = pd.read_csv(path)

    assert list(df["symbol"]) == ["ABC", "DEF"]
    assert len(df) == 2


def test_output_directory_is_created_if_missing(tmp_path) -> None:
    output_dir = tmp_path / "missing" / "nested"

    path = log_equity_quote(equity_quote(), output_dir)

    assert output_dir.exists()
    assert path.exists()


def test_works_for_equity_quote(tmp_path) -> None:
    path = log_equity_quote(equity_quote(), tmp_path)
    df = pd.read_csv(path)

    assert path.name == "equity_quotes_20260102.csv"
    assert df.iloc[0]["source"] == "IBKR"
    assert df.iloc[0]["timestamp"] == NOW.isoformat()


def test_works_for_fx_quote(tmp_path) -> None:
    path = log_fx_quote(fx_quote(), tmp_path)
    df = pd.read_csv(path)

    assert path.name == "fx_quotes_20260102.csv"
    assert df.iloc[0]["source"] == "IBKR_IDEALPRO"
    assert df.iloc[0]["timestamp"] == NOW.isoformat()


def test_works_for_spread_snapshot(tmp_path) -> None:
    path = log_spread_snapshot(spread_snapshot(), tmp_path)
    df = pd.read_csv(path)

    assert path.name == "spread_snapshots_20260102.csv"
    assert df.iloc[0]["pair_id"] == "PAIR"
    assert df.iloc[0]["timestamp"] == NOW.isoformat()


def test_dataframe_append_works(tmp_path) -> None:
    path = tmp_path / "manual.csv"
    append_dataframe_to_csv(pd.DataFrame([{"timestamp": NOW, "value": 1}]), path)
    append_dataframe_to_csv(pd.DataFrame([{"timestamp": NOW, "value": 2}]), path)

    df = pd.read_csv(path)

    assert list(df["value"]) == [1, 2]
    assert list(df["timestamp"]) == [NOW.isoformat(), NOW.isoformat()]
