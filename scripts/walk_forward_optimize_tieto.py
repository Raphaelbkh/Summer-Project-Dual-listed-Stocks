"""Walk-forward optimize Tieto parameters using training data only."""

from argparse import ArgumentParser
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research_tieto_parameters import parameter_grid  # noqa: E402
from scripts.backtest_tradingview_walk_forward import COST_PRESETS  # noqa: E402
from src.backtest.historical_pair_data import load_pair_history  # noqa: E402
from src.backtest.research_tools import apply_backtest_params, load_active_backtest_pairs, load_yaml_config  # noqa: E402
from src.backtest.walk_forward_backtest import (  # noqa: E402
    WalkForwardBacktest,
    export_backtest_run,
    generate_walk_forward_windows,
)


MIN_TRAINING_TRADES = 10
FIXED_BASELINE_PARAMS = {
    "lookback_bars": 200,
    "entry_zscore": 2.0,
    "exit_zscore": 0.5,
    "min_expected_edge_bps": 65,
}
VALIDATION_GRID = {
    "lookback_bars": [100, 200],
    "entry_zscore": [2.0, 2.1, 2.2],
    "exit_zscore": [0.25, 0.5, 0.75],
    "min_expected_edge_bps": [60, 65, 70],
}


def parse_args():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--validation-grid", action="store_true")
    parser.add_argument("--cost-preset", choices=sorted(COST_PRESETS), default=None)
    parser.add_argument("--capital-fraction-per-trade", type=float, default=None)
    parser.add_argument("--min-training-trades", type=int, default=MIN_TRAINING_TRADES)
    parser.add_argument(
        "--fallback-policy",
        choices=["skip_window", "use_fixed_baseline"],
        default="skip_window",
    )
    parser.add_argument("--allow-non-positive-training-pnl", action="store_true")
    parser.add_argument("--pair-id", default="tieto_fi_se")
    return parser.parse_args()


def validation_parameter_grid() -> list[dict]:
    keys = list(VALIDATION_GRID)
    return [dict(zip(keys, values)) for values in product(*(VALIDATION_GRID[key] for key in keys))]


def optimizer_grid(use_validation_grid: bool) -> list[dict]:
    return validation_parameter_grid() if use_validation_grid else parameter_grid()


def apply_optimizer_cli_config(config: dict, args) -> dict:
    output = dict(config)
    output["historical_data"] = dict(config["historical_data"])
    output["backtest"] = dict(config["backtest"])
    output["cli_backtest_overrides"] = {}
    output["historical_data"]["base_path"] = str(
        PROJECT_ROOT / "data" / "historical" / "tradingview"
    )
    if args.cost_preset is not None:
        commission, half_spread, slippage = COST_PRESETS[args.cost_preset]
        output["backtest"]["commission_bps_per_leg"] = commission
        output["backtest"]["estimated_half_spread_bps_per_leg"] = half_spread
        output["backtest"]["slippage_bps_per_leg"] = slippage
        output["cli_backtest_overrides"]["commission_bps_per_leg"] = commission
        output["cli_backtest_overrides"]["estimated_half_spread_bps_per_leg"] = half_spread
        output["cli_backtest_overrides"]["slippage_bps_per_leg"] = slippage
    if args.capital_fraction_per_trade is not None:
        output["backtest"]["capital_fraction_per_trade"] = args.capital_fraction_per_trade
        output["cli_backtest_overrides"]["capital_fraction_per_trade"] = (
            args.capital_fraction_per_trade
        )
    return output


def split_training_period(train_df: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    split_index = max(int(len(train_df) * 0.75), 1)
    calibration = train_df.iloc[:split_index]
    evaluation = train_df.iloc[split_index:]
    if evaluation.empty:
        evaluation = train_df.iloc[-1:]
        calibration = train_df.iloc[:-1]
    return (
        calibration.index.min(),
        calibration.index.max(),
        evaluation.index.min(),
        evaluation.index.max(),
    )


def choose_parameters_on_training(
    pair_id: str,
    pair_df: pd.DataFrame,
    config: dict,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    grid: list[dict] | None = None,
    min_training_trades: int = MIN_TRAINING_TRADES,
    allow_non_positive_training_pnl: bool = False,
) -> tuple[dict | None, dict]:
    training_df = pair_df.loc[(pair_df.index >= train_start) & (pair_df.index <= train_end)]
    cal_start, cal_end, eval_start, eval_end = split_training_period(training_df)
    engine = WalkForwardBacktest()
    best_params = None
    best_summary = None
    best_score = None
    candidates_evaluated = 0
    candidates_passing_constraints = 0
    for params in grid if grid is not None else parameter_grid():
        candidates_evaluated += 1
        candidate_config = apply_backtest_params(config, params)
        try:
            result = engine.run_pair_window(
                pair_id,
                pair_df,
                candidate_config,
                cal_start,
                cal_end,
                eval_start,
                eval_end,
            )
        except ValueError:
            continue
        summary = result.summary
        if summary["number_of_trades"] < min_training_trades:
            continue
        if summary["net_pnl"] <= 0 and not allow_non_positive_training_pnl:
            continue
        candidates_passing_constraints += 1
        score = summary["net_pnl"] - 2 * abs(summary["max_drawdown"])
        if best_score is None or score > best_score:
            best_score = score
            best_params = params
            best_summary = summary

    if best_params is None or best_summary is None:
        best_summary = {
            "net_pnl": 0.0,
            "max_drawdown": 0.0,
            "number_of_trades": 0,
        }
        best_score = 0.0

    return best_params, {
        "training_score": best_score,
        "training_net_pnl": best_summary["net_pnl"],
        "training_max_drawdown": best_summary["max_drawdown"],
        "training_number_of_trades": best_summary["number_of_trades"],
        "fallback_used": best_params is None,
        "fallback_reason": "no_candidate_passed_constraints" if best_params is None else "",
        "candidates_evaluated": candidates_evaluated,
        "candidates_passing_constraints": candidates_passing_constraints,
    }


def fixed_baseline_params() -> dict:
    return dict(FIXED_BASELINE_PARAMS)


def skipped_window_selection_row(
    window: dict,
    training_stats: dict,
    fallback_policy: str,
) -> dict:
    return {
        "window_id": f"{window['train_start'].date()}_{window['test_start'].date()}",
        "train_start": window["train_start"],
        "train_end": window["train_end"],
        "test_start": window["test_start"],
        "test_end": window["test_end"],
        "selected_lookback_bars": None,
        "selected_entry_zscore": None,
        "selected_exit_zscore": None,
        "selected_min_expected_edge_bps": None,
        "fallback_used": True,
        "fallback_policy": fallback_policy,
        "fallback_reason": training_stats["fallback_reason"],
        "candidates_evaluated": training_stats["candidates_evaluated"],
        "candidates_passing_constraints": training_stats["candidates_passing_constraints"],
        "training_score": training_stats["training_score"],
        "training_net_pnl": training_stats["training_net_pnl"],
        "training_max_drawdown": training_stats["training_max_drawdown"],
        "training_number_of_trades": training_stats["training_number_of_trades"],
        "test_net_pnl": 0.0,
        "test_number_of_trades": 0,
    }


def main() -> None:
    args = parse_args()
    config = apply_optimizer_cli_config(
        load_yaml_config(PROJECT_ROOT / "config" / "config.yaml"),
        args,
    )
    grid = optimizer_grid(args.validation_grid)
    pair_row = load_active_backtest_pairs(
        PROJECT_ROOT / "data" / "mappings" / "backtest_pairs.csv",
        args.pair_id,
    ).iloc[0]
    pair_df = load_pair_history(pair_row, config)
    engine = WalkForwardBacktest()
    selected_rows = []
    results = []

    for window in generate_walk_forward_windows(pair_df, train_years=4, test_years=1):
        params, training_stats = choose_parameters_on_training(
            args.pair_id,
            pair_df,
            config,
            window["train_start"],
            window["train_end"],
            grid=grid,
            min_training_trades=args.min_training_trades,
            allow_non_positive_training_pnl=args.allow_non_positive_training_pnl,
        )
        fallback_used = bool(training_stats["fallback_used"])
        fallback_reason = training_stats["fallback_reason"]
        if params is None and args.fallback_policy == "skip_window":
            selected_rows.append(
                skipped_window_selection_row(window, training_stats, args.fallback_policy)
            )
            continue
        if params is None and args.fallback_policy == "use_fixed_baseline":
            params = fixed_baseline_params()
            fallback_used = True
            fallback_reason = "no_candidate_passed_constraints"
        test_config = apply_backtest_params(config, params)
        result = engine.run_pair_window(
            args.pair_id,
            pair_df,
            test_config,
            window["train_start"],
            window["train_end"],
            window["test_start"],
            window["test_end"],
        )
        results.append(result)
        selected_rows.append(
            {
                "window_id": result.window_id,
                "train_start": result.summary["train_start"],
                "train_end": result.summary["train_end"],
                "test_start": result.summary["test_start"],
                "test_end": result.summary["test_end"],
                "selected_lookback_bars": params["lookback_bars"],
                "selected_entry_zscore": params["entry_zscore"],
                "selected_exit_zscore": params["exit_zscore"],
                "selected_min_expected_edge_bps": params["min_expected_edge_bps"],
                "fallback_used": fallback_used,
                "fallback_policy": args.fallback_policy,
                "fallback_reason": fallback_reason,
                "candidates_evaluated": training_stats["candidates_evaluated"],
                "candidates_passing_constraints": training_stats[
                    "candidates_passing_constraints"
                ],
                **training_stats,
                "test_net_pnl": result.summary["net_pnl"],
                "test_number_of_trades": result.summary["number_of_trades"],
            }
        )

    output_dir = (
        PROJECT_ROOT
        / "data"
        / "backtests"
        / f"tieto_walk_forward_optimized_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    )
    export_backtest_run(results, output_dir, config)
    pd.DataFrame([result.summary for result in results]).to_csv(
        output_dir / "optimized_summary.csv",
        index=False,
    )
    pd.DataFrame(selected_rows).to_csv(output_dir / "selected_parameters.csv", index=False)
    trade_frames = [result.trades for result in results if not result.trades.empty]
    pd.concat(trade_frames, ignore_index=True).to_csv(
        output_dir / "optimized_trades.csv",
        index=False,
    ) if trade_frames else pd.DataFrame().to_csv(output_dir / "optimized_trades.csv", index=False)
    equity_frames = [result.equity_curve for result in results if not result.equity_curve.empty]
    pd.concat(equity_frames, ignore_index=True).to_csv(
        output_dir / "optimized_equity_curve.csv",
        index=False,
    ) if equity_frames else pd.DataFrame().to_csv(
        output_dir / "optimized_equity_curve.csv",
        index=False,
    )
    config["optimizer"] = {
        "pair_id": args.pair_id,
        "validation_grid": args.validation_grid,
        "grid_size": len(grid),
        "cost_preset": args.cost_preset,
        "capital_fraction_per_trade": args.capital_fraction_per_trade,
        "min_training_trades": args.min_training_trades,
        "fallback_policy": args.fallback_policy,
        "allow_non_positive_training_pnl": args.allow_non_positive_training_pnl,
    }
    config["effective_backtest_parameters"] = [
        result.effective_parameters for result in results
    ]
    with (output_dir / "run_config.yaml").open("w", encoding="utf-8") as config_file:
        yaml.safe_dump(config, config_file, sort_keys=False)
    print(f"optimized_output_dir: {output_dir}")


if __name__ == "__main__":
    main()
