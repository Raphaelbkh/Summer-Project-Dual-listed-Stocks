"""TradingView CSV loader for offline historical research."""

from pathlib import Path

import pandas as pd


TIMESTAMP_COLUMNS = {"date", "time", "timestamp", "datetime"}
COLUMN_ALIASES = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
}
REQUIRED_COLUMNS = ["open", "high", "low", "close"]


def normalize_tradingview_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common TradingView OHLCV column names."""
    rename_map: dict[str, str] = {}
    timestamp_column = None
    for column in df.columns:
        normalized = str(column).strip().lower()
        if normalized in TIMESTAMP_COLUMNS and timestamp_column is None:
            timestamp_column = column
            rename_map[column] = "timestamp"
        elif normalized in COLUMN_ALIASES:
            rename_map[column] = COLUMN_ALIASES[normalized]

    normalized_df = df.rename(columns=rename_map).copy()
    keep_columns = ["timestamp", *REQUIRED_COLUMNS]
    if "volume" in normalized_df.columns:
        keep_columns.append("volume")
    return normalized_df[[column for column in keep_columns if column in normalized_df.columns]]


def load_tradingview_csv(path: Path, timezone: str | None = None) -> pd.DataFrame:
    """Load a TradingView CSV as timestamp-indexed OHLCV data."""
    df = normalize_tradingview_columns(pd.read_csv(path))
    if "timestamp" not in df.columns:
        raise ValueError("TradingView CSV must include Date, time, timestamp, or datetime.")

    df["timestamp"] = _parse_timestamps(df["timestamp"], timezone)
    for column in REQUIRED_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    df = df.dropna(subset=["timestamp", *REQUIRED_COLUMNS])
    df = df.sort_values("timestamp", kind="stable")
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    df = df.set_index("timestamp")
    validate_ohlcv(df)
    return df


def detect_time_format(values: pd.Series) -> str:
    """Infer whether a TradingView time column is Unix seconds or ISO datetime."""
    non_empty = values.dropna().astype(str).str.strip()
    if non_empty.empty:
        return "unknown"
    return "unix_seconds" if non_empty.str.fullmatch(r"\d+(\.0+)?").all() else "iso_datetime"


def validate_ohlcv(df: pd.DataFrame) -> None:
    """Validate normalized OHLCV data."""
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError("OHLCV data missing columns: " + ", ".join(missing_columns))
    if df.index.name != "timestamp":
        raise ValueError("OHLCV dataframe index must be named timestamp.")
    if df.index.has_duplicates:
        raise ValueError("OHLCV timestamps must be unique.")
    if not df.index.is_monotonic_increasing:
        raise ValueError("OHLCV timestamps must be sorted ascending.")
    if df[REQUIRED_COLUMNS].isna().any().any():
        raise ValueError("OHLCV data contains missing numeric prices.")


def _parse_timestamps(values: pd.Series, timezone: str | None) -> pd.Series:
    if detect_time_format(values) == "unix_seconds":
        return pd.to_datetime(values, unit="s", utc=True, errors="coerce")

    timestamps = pd.to_datetime(values, utc=True, errors="coerce")
    if timezone is not None:
        return timestamps.dt.tz_convert("UTC")
    return timestamps
