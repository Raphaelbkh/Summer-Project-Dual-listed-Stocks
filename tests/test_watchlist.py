from pathlib import Path

import pandas as pd
import pytest

from src.data.mappings.watchlist import (
    load_user_watchlist,
    normalize_ticker,
    validate_user_watchlist,
)


def write_watchlist(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_normalize_ticker_strips_and_uppercases() -> None:
    assert normalize_ticker("  abc  ") == "ABC"


def test_valid_ticker_only_watchlist_passes() -> None:
    df = pd.DataFrame({"ticker": ["ABC", "def"]})

    validate_user_watchlist(df)


def test_notes_column_is_optional() -> None:
    df = pd.DataFrame({"ticker": ["ABC"]})

    validate_user_watchlist(df)


def test_duplicate_ticker_after_normalization_fails() -> None:
    df = pd.DataFrame({"ticker": ["abc", " ABC "]})

    with pytest.raises(ValueError, match="duplicate tickers"):
        validate_user_watchlist(df)


def test_empty_ticker_fails() -> None:
    df = pd.DataFrame({"ticker": ["ABC", "   "]})

    with pytest.raises(ValueError, match="non-empty"):
        validate_user_watchlist(df)


def test_missing_ticker_column_fails() -> None:
    df = pd.DataFrame({"notes": ["no ticker here"]})

    with pytest.raises(ValueError, match="ticker column"):
        validate_user_watchlist(df)


def test_additional_columns_are_allowed_but_warned() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["ABC"],
            "exchange": ["NOT_REQUIRED"],
            "currency": ["NOT_REQUIRED"],
        }
    )

    with pytest.warns(UserWarning, match="Ignoring extra watchlist columns"):
        validate_user_watchlist(df)


def test_load_user_watchlist_does_not_auto_generate_tickers(tmp_path: Path) -> None:
    path = write_watchlist(
        tmp_path / "user_watchlist.csv",
        'ticker,notes\nABC,"user supplied"\n',
    )

    df = load_user_watchlist(path)

    assert list(df["ticker"]) == ["ABC"]
    assert len(df) == 1
