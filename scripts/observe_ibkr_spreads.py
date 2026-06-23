"""Observe-only live spread monitor for manually active pair rows."""

from pathlib import Path
from typing import Callable
import sys
import time

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ibkr_market_data import (  # noqa: E402
    IBKREquityMarketDataProvider,
    load_ibkr_connection_config,
    resolve_ibkr_port,
)
from src.data.live.quote_models import FXQuote, SpreadSnapshot  # noqa: E402
from src.data.mappings.listing_master import get_active_pairs, validate_resolved_pairs  # noqa: E402
from src.fx.ibkr_fx import IBKRFXProvider  # noqa: E402
from src.execution.entry_policy import (  # noqa: E402
    EXCLUDED_ENTRY_HOUR_REASON,
    build_excluded_entry_signal,
    execution_action_allowed,
    log_excluded_entry_signal,
    resolve_strategy_profile,
)
from src.logging.csv_logger import (  # noqa: E402
    log_equity_quote,
    log_fx_quote,
    log_spread_snapshot,
)
from src.signal.executable_spread import calculate_executable_spread  # noqa: E402


SETTINGS_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with SETTINGS_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def validate_observer_safety_config(config_dict: dict) -> None:
    execution = config_dict.get("execution", {})
    universe_selection = config_dict.get("universe_selection", {})
    if execution.get("observe_only") is not True:
        raise ValueError("observe_ibkr_spreads.py requires observe_only=true.")
    disabled_flags = [
        "allow_auto_discovery",
        "allow_auto_screening",
        "allow_ai_generated_tickers",
        "allow_auto_activation",
    ]
    for flag in disabled_flags:
        if universe_selection.get(flag) is not False:
            raise ValueError(f"observe_ibkr_spreads.py requires {flag}=false.")


def load_active_pair_rows(config_dict: dict) -> pd.DataFrame:
    universe_config = config_dict["universe_selection"]
    live_test_pairs_path = PROJECT_ROOT / universe_config["live_test_pairs_path"]
    resolved_pairs_path = PROJECT_ROOT / universe_config["resolved_pairs_path"]

    live_test_pairs = pd.read_csv(live_test_pairs_path, dtype=str, keep_default_na=False)
    validate_resolved_pairs(live_test_pairs)
    active_live_test_pairs = get_active_pairs(live_test_pairs)
    if not active_live_test_pairs.empty:
        return active_live_test_pairs

    resolved_pairs = pd.read_csv(resolved_pairs_path, dtype=str, keep_default_na=False)
    validate_resolved_pairs(resolved_pairs)
    return get_active_pairs(resolved_pairs)


def _float_from_row(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def observe_pair(
    row: pd.Series,
    equity_provider: IBKREquityMarketDataProvider,
    fx_provider: IBKRFXProvider,
    config_dict: dict,
    quote_output_dir: Path,
    spread_output_dir: Path,
    equity_logger: Callable = log_equity_quote,
    fx_logger: Callable = log_fx_quote,
    spread_logger: Callable = log_spread_snapshot,
    excluded_signal_logger: Callable = log_excluded_entry_signal,
) -> SpreadSnapshot:
    long_quote = equity_provider.get_equity_quote(
        row["long_symbol"],
        row["long_exchange"],
        row["long_currency"],
    )
    short_quote = equity_provider.get_equity_quote(
        row["short_symbol"],
        row["short_exchange"],
        row["short_currency"],
    )
    equity_logger(long_quote, quote_output_dir)
    equity_logger(short_quote, quote_output_dir)

    fx_quote: FXQuote | None = None
    if row["long_currency"].upper() != row["short_currency"].upper():
        fx_pair = row.get("fx_pair", "")
        if fx_pair:
            fx_quote = fx_provider.get_fx_quote(fx_pair)
            fx_logger(fx_quote, quote_output_dir)

    execution_config = config_dict["execution"]
    fx_config = config_dict["fx"]
    snapshot = calculate_executable_spread(
        pair_id=row["pair_id"],
        long_quote=long_quote,
        short_quote=short_quote,
        fx_quote=fx_quote,
        conversion_ratio=_float_from_row(row.get("conversion_ratio"), 1.0),
        cost_buffer_bps=float(execution_config["default_cost_buffer_bps"]),
        min_required_net_edge_bps=float(execution_config["min_required_net_edge_bps"]),
        max_equity_quote_age_seconds=float(fx_config["max_quote_age_seconds"]),
        max_fx_quote_age_seconds=float(fx_config["max_quote_age_seconds"]),
    )
    apply_entry_hour_gate(
        snapshot,
        row,
        long_quote,
        short_quote,
        fx_quote,
        config_dict,
        spread_output_dir,
        excluded_signal_logger,
    )
    spread_logger(snapshot, spread_output_dir)
    print_status(snapshot)
    return snapshot


def apply_entry_hour_gate(
    snapshot: SpreadSnapshot,
    row: pd.Series | dict,
    long_quote,
    short_quote,
    fx_quote: FXQuote | None,
    config_dict: dict,
    output_dir: Path,
    excluded_signal_logger: Callable = log_excluded_entry_signal,
) -> bool:
    """Return whether a new entry remains eligible after the paper-start gate."""
    profile = resolve_strategy_profile(config_dict, snapshot.pair_id)
    excluded_hours = profile.get("exclude_entry_hours_utc", [])
    if not snapshot.signal or execution_action_allowed(
        "ENTRY",
        snapshot.timestamp,
        excluded_hours,
    ):
        return bool(snapshot.signal)

    row_dict = dict(row)
    sweden_quote, finland_quote = _country_quotes(long_quote, short_quote)
    observed_signal = build_excluded_entry_signal(
        timestamp=snapshot.timestamp,
        pair_id=snapshot.pair_id,
        direction=_signal_direction(row_dict),
        zscore=_optional_float(row_dict.get("zscore")),
        spread_pct=snapshot.gross_edge,
        expected_edge_bps=(
            None if snapshot.net_edge is None else snapshot.net_edge * 10000
        ),
        sweden_quote=sweden_quote,
        finland_quote=finland_quote,
        eursek_quote=fx_quote,
    )
    excluded_signal_logger(observed_signal, output_dir)
    snapshot.signal = False
    snapshot.rejection_reason = EXCLUDED_ENTRY_HOUR_REASON
    return False


def _country_quotes(long_quote, short_quote):
    quotes = [long_quote, short_quote]
    sweden_quote = next(
        (quote for quote in quotes if quote.currency.upper() == "SEK"),
        None,
    )
    finland_quote = next(
        (quote for quote in quotes if quote.currency.upper() == "EUR"),
        None,
    )
    return sweden_quote, finland_quote


def _signal_direction(row: dict) -> str:
    long_currency = str(row.get("long_currency", "")).upper()
    short_currency = str(row.get("short_currency", "")).upper()
    if long_currency == "EUR" and short_currency == "SEK":
        return "SHORT_SWEDEN_LONG_FINLAND"
    if long_currency == "SEK" and short_currency == "EUR":
        return "LONG_SWEDEN_SHORT_FINLAND"
    return "LONG_LEG_BUY_SHORT_LEG_SELL"


def print_status(snapshot: SpreadSnapshot) -> None:
    reason = snapshot.rejection_reason or "OK"
    print(
        f"pair_id={snapshot.pair_id} signal={snapshot.signal} "
        f"net_edge={snapshot.net_edge} reason={reason}"
    )


def run_observer_once(
    active_pairs: pd.DataFrame,
    equity_provider: IBKREquityMarketDataProvider,
    fx_provider: IBKRFXProvider,
    config_dict: dict,
    quote_output_dir: Path,
    spread_output_dir: Path,
    equity_logger: Callable = log_equity_quote,
    fx_logger: Callable = log_fx_quote,
    spread_logger: Callable = log_spread_snapshot,
    excluded_signal_logger: Callable = log_excluded_entry_signal,
) -> list[SpreadSnapshot]:
    snapshots: list[SpreadSnapshot] = []
    for _, row in active_pairs.iterrows():
        try:
            snapshot = observe_pair(
                row,
                equity_provider,
                fx_provider,
                config_dict,
                quote_output_dir,
                spread_output_dir,
                equity_logger=equity_logger,
                fx_logger=fx_logger,
                spread_logger=spread_logger,
                excluded_signal_logger=excluded_signal_logger,
            )
            snapshots.append(snapshot)
        except Exception as exc:
            print(f"pair_id={row.get('pair_id', '')} error={exc}")
    return snapshots


def run_observer_loop(
    active_pairs: pd.DataFrame,
    equity_provider: IBKREquityMarketDataProvider,
    fx_provider: IBKRFXProvider,
    config_dict: dict,
    quote_output_dir: Path,
    spread_output_dir: Path,
    max_iterations: int | None = None,
) -> None:
    interval_seconds = float(config_dict["polling"]["interval_seconds"])
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        run_observer_once(
            active_pairs,
            equity_provider,
            fx_provider,
            config_dict,
            quote_output_dir,
            spread_output_dir,
        )
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        time.sleep(interval_seconds)


def build_quote_providers(config_dict: dict):
    connection_config = load_ibkr_connection_config(config_dict)
    port = resolve_ibkr_port(connection_config)
    equity_provider = IBKREquityMarketDataProvider(
        host=connection_config.host,
        port=port,
        client_id=connection_config.client_id_market_data,
    )
    fx_provider = IBKRFXProvider(
        host=connection_config.host,
        port=port,
        client_id=int(config_dict["ibkr"]["client_id_fx"]),
    )
    return equity_provider, fx_provider


def main() -> None:
    config_dict = load_config()
    validate_observer_safety_config(config_dict)
    active_pairs = load_active_pair_rows(config_dict)
    if active_pairs.empty:
        print("No active pairs found. Manually set active=true before running.")
        return

    quote_output_dir = PROJECT_ROOT / config_dict["logging"]["live_quotes_dir"]
    spread_output_dir = PROJECT_ROOT / config_dict["logging"]["live_spreads_dir"]
    equity_provider, fx_provider = build_quote_providers(config_dict)

    try:
        equity_provider.connect()
        fx_provider.connect()
        run_observer_loop(
            active_pairs,
            equity_provider,
            fx_provider,
            config_dict,
            quote_output_dir,
            spread_output_dir,
        )
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        if equity_provider.is_connected():
            equity_provider.disconnect()
        if fx_provider.is_connected():
            fx_provider.disconnect()


if __name__ == "__main__":
    main()
