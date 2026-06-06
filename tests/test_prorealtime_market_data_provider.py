from datetime import datetime, timezone
from pathlib import Path

from src.data.live.prorealtime_market_data import (
    SOURCE,
    ProRealTimeCSVQuoteProvider,
)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def write_quotes(path: Path, rows: list[str]) -> None:
    path.write_text(
        "kind,symbol,exchange,currency,pair,bid,ask,bid_size,ask_size,last,timestamp\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def test_provider_connect_disconnect_is_file_backed(tmp_path: Path) -> None:
    provider = ProRealTimeCSVQuoteProvider(tmp_path / "quotes.csv")

    provider.connect()
    assert provider.is_connected() is True

    provider.disconnect()
    assert provider.is_connected() is False


def test_equity_quote_loaded_from_prorealtime_csv(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    write_quotes(
        path,
        ["equity,ABC,NASDAQ STOCKHOLM,SEK,,100.0,101.0,10,12,100.5,2026-01-01T12:00:00+00:00"],
    )
    provider = ProRealTimeCSVQuoteProvider(path)

    quote = provider.get_equity_quote("ABC", "NASDAQ STOCKHOLM", "SEK")

    assert quote.bid == 100.0
    assert quote.ask == 101.0
    assert quote.bid_size == 10.0
    assert quote.ask_size == 12.0
    assert quote.last == 100.5
    assert quote.source == SOURCE
    assert quote.is_valid is True


def test_fx_quote_loaded_from_prorealtime_csv(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    write_quotes(
        path,
        ["fx,,,,EURSEK,11.0,11.1,,,11.05,2026-01-01T12:00:00+00:00"],
    )
    provider = ProRealTimeCSVQuoteProvider(path)

    quote = provider.get_fx_quote("EURSEK")

    assert quote.pair == "EURSEK"
    assert quote.base_currency == "EUR"
    assert quote.quote_currency == "SEK"
    assert quote.bid == 11.0
    assert quote.ask == 11.1
    assert quote.source == SOURCE
    assert quote.is_valid is True


def test_missing_quote_returns_invalid_quote_without_crashing(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    write_quotes(path, [])
    provider = ProRealTimeCSVQuoteProvider(path)

    quote = provider.get_equity_quote("MISSING", "NASDAQ STOCKHOLM", "SEK")

    assert quote.bid is None
    assert quote.ask is None
    assert quote.is_valid is False


def test_latest_timestamp_row_wins(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    write_quotes(
        path,
        [
            "fx,,,,EURSEK,10.0,10.1,,,10.05,2026-01-01T12:00:00+00:00",
            "fx,,,,EURSEK,11.0,11.1,,,11.05,2026-01-01T12:00:05+00:00",
        ],
    )
    provider = ProRealTimeCSVQuoteProvider(path)

    quote = provider.get_fx_quote("EURSEK")

    assert quote.bid == 11.0
    assert quote.ask == 11.1
