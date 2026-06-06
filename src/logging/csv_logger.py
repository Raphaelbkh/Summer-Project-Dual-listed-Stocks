"""CSV append helpers for quote and spread snapshot logs."""

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.live.quote_models import EquityQuote, FXQuote, SpreadSnapshot


def _format_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _format_dataframe_datetimes(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for column in formatted.columns:
        formatted[column] = formatted[column].map(_format_value)
    return formatted


def append_dataframe_to_csv(df: pd.DataFrame, path: Path) -> Path:
    """Append a DataFrame to a CSV, creating parent directories and header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    formatted = _format_dataframe_datetimes(df)
    formatted.to_csv(
        path,
        mode="a",
        index=False,
        header=not path.exists(),
    )
    return path


def append_dataclass_to_daily_csv(obj: Any, output_dir: Path, prefix: str) -> Path:
    """Append one dataclass object to a daily CSV named with the given prefix."""
    if not is_dataclass(obj):
        raise TypeError("append_dataclass_to_daily_csv requires a dataclass object.")

    row = asdict(obj)
    timestamp = row.get("timestamp")
    if isinstance(timestamp, datetime):
        day = timestamp.date()
    else:
        day = date.today()

    path = output_dir / f"{prefix}_{day:%Y%m%d}.csv"
    return append_dataframe_to_csv(pd.DataFrame([row]), path)


def log_equity_quote(quote: EquityQuote, output_dir: Path) -> Path:
    """Append an equity quote to the daily equity quote CSV."""
    return append_dataclass_to_daily_csv(quote, output_dir, "equity_quotes")


def log_fx_quote(quote: FXQuote, output_dir: Path) -> Path:
    """Append an FX quote to the daily FX quote CSV."""
    return append_dataclass_to_daily_csv(quote, output_dir, "fx_quotes")


def log_spread_snapshot(snapshot: SpreadSnapshot, output_dir: Path) -> Path:
    """Append a spread snapshot to the daily spread snapshot CSV."""
    return append_dataclass_to_daily_csv(snapshot, output_dir, "spread_snapshots")
