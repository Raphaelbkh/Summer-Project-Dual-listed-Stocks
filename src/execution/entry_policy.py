"""Research-to-paper entry-hour safety gate and observe-only logging."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.live.quote_models import EquityQuote, FXQuote
from src.logging.csv_logger import append_dataframe_to_csv


EXCLUDED_ENTRY_HOUR_REASON = "excluded_entry_hour_observe_only"


@dataclass
class ExcludedEntrySignal:
    timestamp_utc: datetime
    pair_id: str
    direction: str
    zscore: float | None
    spread_pct: float | None
    expected_edge_bps: float | None
    sweden_bid: float | None
    sweden_ask: float | None
    sweden_mid: float | None
    finland_bid: float | None
    finland_ask: float | None
    finland_mid: float | None
    eursek_bid: float | None
    eursek_ask: float | None
    eursek_mid: float | None
    reason: str = EXCLUDED_ENTRY_HOUR_REASON


def resolve_strategy_profile(config: dict, pair_id: str) -> dict:
    profile_name = config.get("execution", {}).get("active_strategy_profile")
    profile = config.get("strategy_profiles", {}).get(profile_name, {})
    if profile.get("pair_id") != pair_id:
        return {}
    return dict(profile)


def execution_action_allowed(
    action: str,
    timestamp: datetime,
    excluded_entry_hours_utc: list[int] | tuple[int, ...] | set[int],
) -> bool:
    if action.upper() == "EXIT":
        return True
    if action.upper() != "ENTRY":
        raise ValueError("action must be ENTRY or EXIT")
    return _utc_timestamp(timestamp).hour not in {int(hour) for hour in excluded_entry_hours_utc}


def build_excluded_entry_signal(
    *,
    timestamp: datetime,
    pair_id: str,
    direction: str,
    zscore: float | None,
    spread_pct: float | None,
    expected_edge_bps: float | None,
    sweden_quote: EquityQuote | None,
    finland_quote: EquityQuote | None,
    eursek_quote: FXQuote | None,
) -> ExcludedEntrySignal:
    return ExcludedEntrySignal(
        timestamp_utc=_utc_timestamp(timestamp),
        pair_id=pair_id,
        direction=direction,
        zscore=zscore,
        spread_pct=spread_pct,
        expected_edge_bps=expected_edge_bps,
        sweden_bid=_quote_value(sweden_quote, "bid"),
        sweden_ask=_quote_value(sweden_quote, "ask"),
        sweden_mid=_quote_value(sweden_quote, "mid"),
        finland_bid=_quote_value(finland_quote, "bid"),
        finland_ask=_quote_value(finland_quote, "ask"),
        finland_mid=_quote_value(finland_quote, "mid"),
        eursek_bid=_quote_value(eursek_quote, "bid"),
        eursek_ask=_quote_value(eursek_quote, "ask"),
        eursek_mid=_quote_value(eursek_quote, "mid"),
    )


def log_excluded_entry_signal(signal: ExcludedEntrySignal, output_dir: Path) -> Path:
    path = output_dir / f"excluded_entry_signals_{signal.timestamp_utc:%Y%m%d}.csv"
    return append_dataframe_to_csv(pd.DataFrame([asdict(signal)]), path)


def _utc_timestamp(timestamp: datetime) -> datetime:
    value = pd.Timestamp(timestamp)
    if value.tzinfo is None:
        value = value.tz_localize("UTC")
    else:
        value = value.tz_convert("UTC")
    return value.to_pydatetime().astimezone(timezone.utc)


def _quote_value(quote: Any | None, name: str) -> float | None:
    if quote is None:
        return None
    value = getattr(quote, name, None)
    return None if value is None else float(value)
