"""Load and align offline historical pair data."""

from pathlib import Path
from typing import Any

import pandas as pd

from src.data.historical.tradingview_csv_loader import load_tradingview_csv


def load_pair_history(pair_row: pd.Series | dict[str, Any], config: dict) -> pd.DataFrame:
    """Load CSV history for one pair mapping row and return aligned pair bars."""
    row = dict(pair_row)
    historical_config = config["historical_data"]
    base_path = Path(historical_config["base_path"])
    timezone = historical_config.get("timestamp_timezone")
    timeframe = historical_config.get("timeframe", "60m")

    long_df = load_tradingview_csv(
        base_path / resolve_timeframe_csv_file(row, "long_csv_file", timeframe),
        timezone=timezone,
    )
    short_df = load_tradingview_csv(
        base_path / resolve_timeframe_csv_file(row, "short_csv_file", timeframe),
        timezone=timezone,
    )

    fx_df = None
    fx_csv_file = resolve_timeframe_csv_file(row, "fx_csv_file", timeframe)
    if fx_csv_file:
        fx_df = load_tradingview_csv(base_path / fx_csv_file, timezone=timezone)
    elif _currency(row, "long_currency") != _currency(row, "short_currency"):
        raise ValueError("Cross-currency pair requires fx_csv_file.")

    aligned = align_pair_bars(long_df, short_df, fx_df, config, row)
    effective_start = effective_common_start(long_df, short_df, fx_df, row)
    return aligned.loc[aligned.index >= effective_start].copy()


def align_pair_bars(
    long_df: pd.DataFrame,
    short_df: pd.DataFrame,
    fx_df: pd.DataFrame | None,
    config: dict,
    pair_row: pd.Series | dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Align long, short, and optional FX bars on timestamp intersection."""
    row = _row_to_dict(pair_row)
    historical_config = config["historical_data"]
    price_column = historical_config.get("price_column", "close")

    long_prefixed = _prefix_ohlcv(long_df, "long")
    short_prefixed = _prefix_ohlcv(short_df, "short")
    aligned = long_prefixed.join(short_prefixed, how="inner")

    if fx_df is None:
        aligned["fx_rate"] = 1.0
    else:
        aligned = _align_fx_rates(aligned, fx_df, price_column, historical_config)

    if not historical_config.get("allow_missing_bars", False):
        aligned = aligned.dropna()

    long_currency = _currency(row, "long_currency")
    short_currency = _currency(row, "short_currency")
    base_currency = str(config.get("backtest", {}).get("base_currency", short_currency)).upper()
    aligned["fair_price_sek"] = _convert_to_base(
        aligned[f"long_{price_column}"],
        long_currency,
        base_currency,
        aligned["fx_rate"],
    )
    aligned["short_price_base"] = _convert_to_base(
        aligned[f"short_{price_column}"],
        short_currency,
        base_currency,
        aligned["fx_rate"],
    )
    aligned["long_price_base"] = aligned["fair_price_sek"]
    aligned["spread_abs"] = aligned["short_price_base"] - aligned["fair_price_sek"]
    aligned["spread_pct"] = aligned["spread_abs"] / aligned["fair_price_sek"]
    aligned.index.name = "timestamp"
    return aligned


def true_common_start(
    long_df: pd.DataFrame,
    short_df: pd.DataFrame,
    fx_df: pd.DataFrame | None,
) -> pd.Timestamp:
    starts = [long_df.index.min(), short_df.index.min()]
    if fx_df is not None:
        starts.append(fx_df.index.min())
    return max(starts)


def true_common_end(
    long_df: pd.DataFrame,
    short_df: pd.DataFrame,
    fx_df: pd.DataFrame | None,
) -> pd.Timestamp:
    ends = [long_df.index.max(), short_df.index.max()]
    if fx_df is not None:
        ends.append(fx_df.index.max())
    return min(ends)


def resolve_timeframe_csv_file(row: dict[str, Any], column: str, timeframe: str) -> str:
    """Resolve timeframe-specific CSV file mapping while preserving 60m defaults."""
    timeframe_column = f"{column}_{timeframe}"
    if timeframe != "60m":
        timeframe_value = str(row.get(timeframe_column, "")).strip()
        if timeframe_value:
            return timeframe_value
    return str(row.get(column, "")).strip()


def effective_common_start(
    long_df: pd.DataFrame,
    short_df: pd.DataFrame,
    fx_df: pd.DataFrame | None,
    pair_row: pd.Series | dict[str, Any],
) -> pd.Timestamp:
    common_start = true_common_start(long_df, short_df, fx_df)
    override_value = _row_to_dict(pair_row).get("backtest_start_override", "")
    if pd.isna(override_value):
        return common_start
    override = str(override_value).strip()
    if not override:
        return common_start
    override_ts = _timestamp_like_index(override, common_start)
    return max(common_start, override_ts)


def _prefix_ohlcv(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    columns = [column for column in ["open", "high", "low", "close", "volume"] if column in df]
    return df[columns].rename(columns={column: f"{prefix}_{column}" for column in columns})


def _align_fx_rates(
    aligned: pd.DataFrame,
    fx_df: pd.DataFrame,
    price_column: str,
    historical_config: dict,
) -> pd.DataFrame:
    fx_rates = fx_df[[price_column]].rename(columns={price_column: "fx_rate"})
    if historical_config.get("timeframe", "60m") != "30m":
        return aligned.join(fx_rates, how="inner")

    tolerance = pd.Timedelta(minutes=30)
    left = aligned.sort_index().reset_index()
    right = fx_rates.sort_index().reset_index()
    merged = pd.merge_asof(
        left,
        right,
        on="timestamp",
        direction="backward",
        tolerance=tolerance,
    )
    return merged.set_index("timestamp")


def _currency(row: dict[str, Any], key: str) -> str:
    return str(row.get(key, "")).upper()


def _row_to_dict(pair_row: pd.Series | dict[str, Any] | None) -> dict[str, Any]:
    if pair_row is None:
        return {}
    return dict(pair_row)


def _convert_to_base(
    price: pd.Series,
    currency: str,
    base_currency: str,
    fx_rate: pd.Series,
) -> pd.Series:
    if not currency or currency == base_currency:
        return price
    return price * fx_rate


def _timestamp_like_index(value: str, reference: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if reference.tzinfo is not None and timestamp.tzinfo is None:
        return timestamp.tz_localize(reference.tzinfo)
    if reference.tzinfo is not None:
        return timestamp.tz_convert(reference.tzinfo)
    if reference.tzinfo is None and timestamp.tzinfo is not None:
        return timestamp.tz_convert(None)
    return timestamp
