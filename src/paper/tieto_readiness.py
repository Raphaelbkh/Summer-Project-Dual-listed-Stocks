"""Tieto paper-readiness calculations and CSV reporting without order submission."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.live.quote_models import EquityQuote, FXQuote
from src.execution.entry_policy import (
    EXCLUDED_ENTRY_HOUR_REASON,
    execution_action_allowed,
)
from src.logging.csv_logger import append_dataframe_to_csv


PAIR_ID = "tieto_fi_se"


@dataclass
class ContractValidation:
    instrument: str
    conId: int | None
    symbol: str
    exchange: str
    currency: str
    trading_class: str
    local_symbol: str


@dataclass
class PaperSignal:
    timestamp_utc: datetime
    pair_id: str
    profile_name: str
    action: str
    direction: str
    zscore: float | None
    spread_pct: float | None
    expected_edge_bps: float | None
    mid_spread_bps: float | None
    executable_spread_bps: float | None
    sweden_bid: float | None
    sweden_ask: float | None
    sweden_mid: float | None
    finland_bid: float | None
    finland_ask: float | None
    finland_mid: float | None
    eursek_bid: float | None
    eursek_ask: float | None
    eursek_mid: float | None
    allowed_by_entry_policy: bool
    block_reason: str
    would_trade_boolean: bool
    dry_run: bool = True


def require_dry_run(dry_run: bool = True) -> None:
    if dry_run is not True:
        raise RuntimeError("Tieto paper-readiness workflow requires dry_run=True.")


def validate_stock_contract(provider: Any, instrument: str, spec: dict) -> ContractValidation:
    try:
        contract = provider.qualify_stock_contract(
            spec["symbol"],
            spec["exchange"],
            spec["currency"],
        )
    except Exception as exc:
        raise ValueError(f"Unable to resolve {instrument} contract: {exc}") from exc
    return _contract_validation(instrument, contract, spec)


def validate_fx_contract(provider: Any, pair: str) -> ContractValidation:
    try:
        contract = provider.qualify_fx_contract(pair)
    except Exception as exc:
        raise ValueError(f"Unable to resolve {pair} FX contract: {exc}") from exc
    return _contract_validation(pair, contract, {"symbol": pair, "currency": pair[3:]})


def market_snapshot_rows(
    sweden: EquityQuote,
    finland: EquityQuote,
    eursek: FXQuote,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _quote_snapshot_row("sweden", sweden),
            _quote_snapshot_row("finland", finland),
            _quote_snapshot_row("eursek", eursek),
        ]
    )


def executable_spread_metrics(
    sweden: EquityQuote,
    finland: EquityQuote,
    eursek: FXQuote,
) -> dict[str, float | None]:
    if sweden.mid is None or finland.mid is None or eursek.mid is None:
        return _empty_spread_metrics()

    fair_sweden_mid = finland.mid * eursek.mid
    mid_spread_bps = (sweden.mid - fair_sweden_mid) / fair_sweden_mid * 10000
    short_sweden_edge = None
    long_sweden_edge = None
    if sweden.bid is not None and finland.ask is not None and eursek.ask is not None:
        finland_buy_cost_sek = finland.ask * eursek.ask
        short_sweden_edge = (
            (sweden.bid - finland_buy_cost_sek) / finland_buy_cost_sek * 10000
        )
    if sweden.ask is not None and finland.bid is not None and eursek.bid is not None:
        finland_sell_value_sek = finland.bid * eursek.bid
        long_sweden_edge = (
            (finland_sell_value_sek - sweden.ask) / sweden.ask * 10000
        )
    return {
        "fair_sweden_mid_sek": fair_sweden_mid,
        "mid_spread_bps": mid_spread_bps,
        "short_sweden_long_finland_executable_spread_bps": short_sweden_edge,
        "long_sweden_short_finland_executable_spread_bps": long_sweden_edge,
    }


def build_paper_signal(
    *,
    timestamp: datetime,
    profile_name: str,
    profile: dict,
    action: str,
    direction: str,
    zscore: float | None,
    sweden: EquityQuote,
    finland: EquityQuote,
    eursek: FXQuote,
    dry_run: bool = True,
) -> PaperSignal:
    require_dry_run(dry_run)
    timestamp_utc = _utc_datetime(timestamp)
    metrics = executable_spread_metrics(sweden, finland, eursek)
    expected_edge_bps = _direction_edge(metrics, direction)
    allowed = execution_action_allowed(
        action,
        timestamp_utc,
        profile.get("exclude_entry_hours_utc", []),
    )
    block_reason = "" if allowed else EXCLUDED_ENTRY_HOUR_REASON
    return PaperSignal(
        timestamp_utc=timestamp_utc,
        pair_id=profile.get("pair_id", PAIR_ID),
        profile_name=profile_name,
        action=action.upper(),
        direction=direction,
        zscore=zscore,
        spread_pct=(
            None if metrics["mid_spread_bps"] is None else metrics["mid_spread_bps"] / 10000
        ),
        expected_edge_bps=expected_edge_bps,
        mid_spread_bps=metrics["mid_spread_bps"],
        executable_spread_bps=expected_edge_bps,
        sweden_bid=sweden.bid,
        sweden_ask=sweden.ask,
        sweden_mid=sweden.mid,
        finland_bid=finland.bid,
        finland_ask=finland.ask,
        finland_mid=finland.mid,
        eursek_bid=eursek.bid,
        eursek_ask=eursek.ask,
        eursek_mid=eursek.mid,
        allowed_by_entry_policy=allowed,
        block_reason=block_reason,
        would_trade_boolean=allowed,
        dry_run=True,
    )


def log_market_snapshot(snapshot: pd.DataFrame, output_dir: Path, timestamp: datetime) -> Path:
    day = _utc_datetime(timestamp).date()
    return append_dataframe_to_csv(snapshot, output_dir / f"market_snapshot_{day:%Y%m%d}.csv")


def log_paper_signal(signal: PaperSignal, output_dir: Path) -> Path:
    path = output_dir / f"paper_signals_{signal.timestamp_utc:%Y%m%d}.csv"
    return append_dataframe_to_csv(pd.DataFrame([asdict(signal)]), path)


def generate_daily_report(signals: pd.DataFrame, report_date: date) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame([_empty_report(report_date)])
    missing_columns = [
        "sweden_bid",
        "sweden_ask",
        "finland_bid",
        "finland_ask",
        "eursek_bid",
        "eursek_ask",
    ]
    missing_market_data = signals[missing_columns].isna().any(axis=1)
    action = signals["action"].astype(str).str.upper()
    blocked = ~signals["allowed_by_entry_policy"].map(_as_bool)
    excluded = signals["block_reason"].eq(EXCLUDED_ENTRY_HOUR_REASON)
    return pd.DataFrame(
        [
            {
                "report_date": report_date.isoformat(),
                "total_signals": len(signals),
                "allowed_signals": int((~blocked).sum()),
                "blocked_observe_only_signals": int(blocked.sum()),
                "average_mid_spread_bps": _mean(signals, "mid_spread_bps"),
                "average_executable_spread_bps": _mean(
                    signals, "executable_spread_bps"
                ),
                "average_sweden_bid_ask_spread_bps": _average_quote_spread_bps(
                    signals, "sweden"
                ),
                "average_finland_bid_ask_spread_bps": _average_quote_spread_bps(
                    signals, "finland"
                ),
                "average_eursek_bid_ask_spread_bps": _average_quote_spread_bps(
                    signals, "eursek"
                ),
                "missing_market_data_count": int(missing_market_data.sum()),
                "excluded_hour_signal_count": int((excluded & action.eq("ENTRY")).sum()),
            }
        ]
    )


def write_daily_report(report: pd.DataFrame, output_dir: Path, report_date: date) -> Path:
    path = output_dir / f"tieto_paper_report_{report_date:%Y%m%d}.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    report.to_csv(path, index=False)
    return path


def _contract_validation(instrument: str, contract: Any, spec: dict) -> ContractValidation:
    if contract is None:
        raise ValueError(f"Unable to resolve {instrument} contract: empty qualification result")
    return ContractValidation(
        instrument=instrument,
        conId=getattr(contract, "conId", None),
        symbol=str(getattr(contract, "symbol", spec.get("symbol", ""))),
        exchange=str(getattr(contract, "exchange", spec.get("exchange", ""))),
        currency=str(getattr(contract, "currency", spec.get("currency", ""))),
        trading_class=str(getattr(contract, "tradingClass", "")),
        local_symbol=str(getattr(contract, "localSymbol", "")),
    )


def _quote_snapshot_row(instrument: str, quote: EquityQuote | FXQuote) -> dict:
    return {
        "timestamp_utc": _utc_datetime(quote.timestamp),
        "instrument": instrument,
        "symbol": getattr(quote, "symbol", getattr(quote, "pair", "")),
        "bid": quote.bid,
        "ask": quote.ask,
        "mid": quote.mid,
        "last": quote.last,
        "currency": getattr(quote, "currency", getattr(quote, "quote_currency", "")),
        "exchange": getattr(quote, "exchange", "IDEALPRO"),
    }


def _direction_edge(metrics: dict, direction: str) -> float | None:
    if direction == "SHORT_SWEDEN_LONG_FINLAND":
        return metrics["short_sweden_long_finland_executable_spread_bps"]
    if direction == "LONG_SWEDEN_SHORT_FINLAND":
        return metrics["long_sweden_short_finland_executable_spread_bps"]
    raise ValueError(f"Unsupported direction: {direction}")


def _empty_spread_metrics() -> dict[str, None]:
    return {
        "fair_sweden_mid_sek": None,
        "mid_spread_bps": None,
        "short_sweden_long_finland_executable_spread_bps": None,
        "long_sweden_short_finland_executable_spread_bps": None,
    }


def _utc_datetime(value: datetime) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime().astimezone(timezone.utc)


def _mean(df: pd.DataFrame, column: str) -> float | None:
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return None if values.empty else float(values.mean())


def _average_quote_spread_bps(df: pd.DataFrame, prefix: str) -> float | None:
    bid = pd.to_numeric(df[f"{prefix}_bid"], errors="coerce")
    ask = pd.to_numeric(df[f"{prefix}_ask"], errors="coerce")
    mid = (bid + ask) / 2
    spread = ((ask - bid) / mid * 10000).replace([float("inf"), -float("inf")], pd.NA)
    spread = spread.dropna()
    return None if spread.empty else float(spread.mean())


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _empty_report(report_date: date) -> dict:
    return {
        "report_date": report_date.isoformat(),
        "total_signals": 0,
        "allowed_signals": 0,
        "blocked_observe_only_signals": 0,
        "average_mid_spread_bps": None,
        "average_executable_spread_bps": None,
        "average_sweden_bid_ask_spread_bps": None,
        "average_finland_bid_ask_spread_bps": None,
        "average_eursek_bid_ask_spread_bps": None,
        "missing_market_data_count": 0,
        "excluded_hour_signal_count": 0,
    }
