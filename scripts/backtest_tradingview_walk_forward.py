"""Run offline walk-forward backtests from TradingView CSV exports."""

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest.historical_pair_data import load_pair_history  # noqa: E402
from src.backtest.walk_forward_backtest import (  # noqa: E402
    WalkForwardBacktest,
    export_backtest_run,
)
from src.data.mappings.listing_master import get_active_pairs  # noqa: E402


COST_PRESETS = {
    "zero": (0, 0, 0),
    "low": (1, 1, 1),
    "medium": (3, 3, 3),
    "high": (5, 5, 5),
}


def parse_args():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--pair-id", default=None)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--mapping", default="data/mappings/backtest_pairs.csv")
    parser.add_argument("--data-dir", default="data/historical/tradingview")
    parser.add_argument("--timeframe", choices=["60m", "30m"], default="60m")
    parser.add_argument("--output-dir", default="data/backtests")
    parser.add_argument("--train-years", type=int, default=4)
    parser.add_argument("--test-years", type=int, default=1)
    parser.add_argument("--lookback-bars", type=int, default=None)
    parser.add_argument("--entry-zscore", type=float, default=None)
    parser.add_argument("--exit-zscore", type=float, default=None)
    parser.add_argument("--max-holding-bars", type=int, default=None)
    parser.add_argument("--initial-capital-base-ccy", type=float, default=None)
    parser.add_argument("--capital-fraction-per-trade", type=float, default=None)
    parser.add_argument("--cost-preset", choices=sorted(COST_PRESETS), default=None)
    parser.add_argument("--commission-bps-per-leg", type=float, default=None)
    parser.add_argument("--half-spread-bps-per-leg", type=float, default=None)
    parser.add_argument("--slippage-bps-per-leg", type=float, default=None)
    parser.add_argument("--min-expected-edge-bps", type=float, default=None)
    parser.add_argument("--min-deviation-bps", type=float, default=None)
    parser.add_argument("--min-expected-reversion-bps", type=float, default=None)
    parser.add_argument(
        "--allowed-direction",
        choices=["any", "LONG_SWEDEN_SHORT_FINLAND", "SHORT_SWEDEN_LONG_FINLAND"],
        default="any",
    )
    parser.add_argument("--entry-hours-utc", default=None)
    parser.add_argument("--exclude-entry-hours-utc", default=None)
    parser.add_argument("--max-entry-edge-bps", type=float, default=None)
    parser.add_argument("--invert-signals", action="store_true")
    return parser.parse_args()


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def apply_cli_overrides(config: dict, args) -> dict:
    config["historical_data"]["timeframe"] = args.timeframe
    data_dir = args.data_dir
    if args.timeframe == "30m" and data_dir == "data/historical/tradingview":
        data_dir = "data/raw/tradingview/30m"
    config["historical_data"]["base_path"] = str(PROJECT_ROOT / data_dir)
    cli_overrides = {}
    for arg_name, config_name in [
        ("lookback_bars", "lookback_bars"),
        ("entry_zscore", "entry_zscore"),
        ("exit_zscore", "exit_zscore"),
        ("max_holding_bars", "max_holding_bars"),
        ("initial_capital_base_ccy", "initial_capital_base_ccy"),
        ("capital_fraction_per_trade", "capital_fraction_per_trade"),
        ("min_expected_edge_bps", "min_expected_edge_bps"),
        ("min_deviation_bps", "min_deviation_bps"),
        ("min_expected_reversion_bps", "min_expected_reversion_bps"),
        ("max_entry_edge_bps", "max_entry_edge_bps"),
    ]:
        value = getattr(args, arg_name)
        if value is not None:
            cli_overrides[config_name] = value
    if args.allowed_direction != "any":
        cli_overrides["allowed_direction"] = args.allowed_direction
    entry_hours = parse_hour_list(args.entry_hours_utc)
    if entry_hours is not None:
        cli_overrides["entry_hours_utc"] = entry_hours
    excluded_hours = parse_hour_list(args.exclude_entry_hours_utc)
    if excluded_hours is not None:
        cli_overrides["exclude_entry_hours_utc"] = excluded_hours
    if args.cost_preset is not None:
        commission, half_spread, slippage = COST_PRESETS[args.cost_preset]
        cli_overrides["commission_bps_per_leg"] = commission
        cli_overrides["estimated_half_spread_bps_per_leg"] = half_spread
        cli_overrides["slippage_bps_per_leg"] = slippage
    for arg_name, config_name in [
        ("commission_bps_per_leg", "commission_bps_per_leg"),
        ("half_spread_bps_per_leg", "estimated_half_spread_bps_per_leg"),
        ("slippage_bps_per_leg", "slippage_bps_per_leg"),
    ]:
        value = getattr(args, arg_name)
        if value is not None:
            cli_overrides[config_name] = value
    if args.invert_signals:
        cli_overrides["invert_signals"] = True
    config["cli_backtest_overrides"] = cli_overrides
    return config


def parse_hour_list(value: str | None) -> list[int] | None:
    if value is None or value.strip() == "":
        return None
    hours = [int(part.strip()) for part in value.split(",") if part.strip()]
    invalid = [hour for hour in hours if hour < 0 or hour > 23]
    if invalid:
        raise ValueError("Entry hour filters must use UTC hours between 0 and 23.")
    return hours


def cost_values_from_args(args) -> tuple[float, float, float]:
    preset = args.cost_preset or "high"
    preset_commission, preset_half_spread, preset_slippage = COST_PRESETS[preset]
    return (
        preset_commission
        if args.commission_bps_per_leg is None
        else args.commission_bps_per_leg,
        preset_half_spread
        if args.half_spread_bps_per_leg is None
        else args.half_spread_bps_per_leg,
        preset_slippage if args.slippage_bps_per_leg is None else args.slippage_bps_per_leg,
    )


def load_mapping(path: Path, pair_id: str | None) -> pd.DataFrame:
    pairs = pd.read_csv(path, dtype=str, keep_default_na=False)
    active_pairs = get_active_pairs(pairs)
    if pair_id is not None:
        active_pairs = active_pairs.loc[active_pairs["pair_id"] == pair_id].copy()
    required_columns = {"long_csv_file", "short_csv_file", "fx_csv_file"}
    missing = required_columns - set(active_pairs.columns)
    if missing:
        raise ValueError("Mapping file missing CSV columns: " + ", ".join(sorted(missing)))
    if active_pairs.empty:
        raise ValueError("No active historical pairs matched the request.")
    return active_pairs


def main() -> None:
    args = parse_args()
    config = apply_cli_overrides(load_config(PROJECT_ROOT / args.config), args)
    pairs = load_mapping(PROJECT_ROOT / args.mapping, args.pair_id)

    pair_data = {}
    for _, row in pairs.iterrows():
        pair_data[row["pair_id"]] = load_pair_history(row, config)

    engine = WalkForwardBacktest()
    results = engine.run_all_pairs(
        pair_data,
        config,
        train_years=args.train_years,
        test_years=args.test_years,
    )
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / args.output_dir / run_timestamp
    export_backtest_run(results, output_dir, config)
    print(f"backtest_output_dir: {output_dir}")
    for result in results:
        print(f"pair_id: {result.pair_id}")
        print(f"net_pnl: {result.summary['net_pnl']}")
        print(f"number_of_trades: {result.summary['number_of_trades']}")


if __name__ == "__main__":
    main()
