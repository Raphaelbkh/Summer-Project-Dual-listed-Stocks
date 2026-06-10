"""Observe-only live spread monitor for manually active pair rows."""

from pathlib import Path
from typing import Callable
import os
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
from src.data.live.ig_api import (  # noqa: E402
    IGAPIClient,
    IGPricesQuoteProvider,
    ig_base_url_for_profile,
    load_ig_credentials_for_profile_from_env,
    load_ig_session_settings_for_profile_from_env,
)
from src.data.live.prorealtime_market_data import ProRealTimeCSVQuoteProvider  # noqa: E402
from src.data.live.quote_models import FXQuote, SpreadSnapshot  # noqa: E402
from src.data.mappings.listing_master import get_active_pairs, validate_resolved_pairs  # noqa: E402
from src.fx.ibkr_fx import IBKRFXProvider  # noqa: E402
from src.logging.csv_logger import (  # noqa: E402
    log_equity_quote,
    log_fx_quote,
    log_spread_snapshot,
)
from src.signal.executable_spread import calculate_executable_spread  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def load_dotenv_if_present() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


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
    spread_logger(snapshot, spread_output_dir)
    print_status(snapshot)
    return snapshot


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
    live_provider = config_dict.get("market_data", {}).get("live_provider", "IBKR")
    if live_provider == "IG_LIVE_API":
        credentials = load_ig_credentials_for_profile_from_env(config_dict, "ig_live_data")
        session_settings = load_ig_session_settings_for_profile_from_env(
            config_dict,
            "ig_live_data",
        )
        client = IGAPIClient(ig_base_url_for_profile(config_dict, "ig_live_data"), credentials)
        provider = IGPricesQuoteProvider(
            client=client,
            account_id=session_settings.account_id,
            fx_epics=config_dict["ig_live_data"].get("fx_epics", {}),
        )
        return provider, provider

    if live_provider == "PROREALTIME_DDE_CSV":
        quotes_path = PROJECT_ROOT / config_dict["market_data"]["prorealtime_quotes_path"]
        provider = ProRealTimeCSVQuoteProvider(quotes_path)
        return provider, provider

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
    load_dotenv_if_present()
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
