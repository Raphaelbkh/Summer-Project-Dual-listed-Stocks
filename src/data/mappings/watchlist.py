"""User-maintained ticker watchlist loading and validation."""

from pathlib import Path
import warnings

import pandas as pd


REQUIRED_COLUMNS = {"ticker"}
OPTIONAL_COLUMNS = {"notes"}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS


def normalize_ticker(ticker: str) -> str:
    """Normalize a user-provided ticker for validation and matching."""
    if not isinstance(ticker, str):
        return ""
    return ticker.strip().upper()


def load_user_watchlist(path: Path) -> pd.DataFrame:
    """Load and validate the user watchlist CSV."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    validate_user_watchlist(df)
    return df


def validate_user_watchlist(df: pd.DataFrame) -> None:
    """Validate the watchlist without enriching or adding tickers."""
    if "ticker" not in df.columns:
        raise ValueError("user_watchlist.csv must contain a ticker column.")

    extra_columns = set(df.columns) - ALLOWED_COLUMNS
    if extra_columns:
        warnings.warn(
            "Ignoring extra watchlist columns: "
            + ", ".join(sorted(extra_columns)),
            UserWarning,
            stacklevel=2,
        )

    normalized_tickers = df["ticker"].map(normalize_ticker)
    if normalized_tickers.eq("").any():
        raise ValueError("ticker values must be non-empty.")

    duplicate_mask = normalized_tickers.duplicated(keep=False)
    if duplicate_mask.any():
        duplicates = sorted(set(normalized_tickers[duplicate_mask]))
        raise ValueError(
            "duplicate tickers after normalization are not allowed: "
            + ", ".join(duplicates)
        )
