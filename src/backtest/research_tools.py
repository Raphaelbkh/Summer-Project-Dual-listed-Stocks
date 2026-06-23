"""Shared helpers for offline backtest research scripts."""

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.backtest.historical_pair_data import load_pair_history
from src.backtest.walk_forward_backtest import BacktestResult, WalkForwardBacktest
from src.data.mappings.listing_master import get_active_pairs


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def load_active_backtest_pairs(mapping_path: Path, pair_id: str | None = None) -> pd.DataFrame:
    pairs = pd.read_csv(mapping_path, dtype=str, keep_default_na=False)
    active_pairs = get_active_pairs(pairs)
    if pair_id is not None:
        active_pairs = active_pairs.loc[active_pairs["pair_id"] == pair_id].copy()
    if active_pairs.empty:
        raise ValueError("No active historical pairs matched the request.")
    return active_pairs


def load_pair_data(pairs: pd.DataFrame, config: dict) -> dict[str, pd.DataFrame]:
    return {row["pair_id"]: load_pair_history(row, config) for _, row in pairs.iterrows()}


def run_walk_forward_for_pairs(
    pairs: pd.DataFrame,
    config: dict,
    train_years: int = 4,
    test_years: int = 1,
) -> list[BacktestResult]:
    pair_data = load_pair_data(pairs, config)
    return WalkForwardBacktest().run_all_pairs(pair_data, config, train_years, test_years)


def aggregate_results(results: list[BacktestResult]) -> dict[str, Any]:
    summaries = pd.DataFrame([result.summary for result in results])
    trades = pd.concat([result.trades for result in results if not result.trades.empty], ignore_index=True) if results else pd.DataFrame()
    if summaries.empty:
        return {
            "total_net_pnl": 0.0,
            "total_gross_pnl": 0.0,
            "total_cost": 0.0,
            "number_of_trades": 0,
            "win_rate": 0.0,
            "average_trade_pnl": 0.0,
            "max_drawdown": 0.0,
            "positive_windows": 0,
            "total_windows": 0,
        }
    total_trades = int(summaries["number_of_trades"].sum())
    return {
        "total_net_pnl": float(summaries["net_pnl"].sum()),
        "total_gross_pnl": float(summaries["gross_pnl"].sum()),
        "total_cost": float(summaries["cost_total"].sum()),
        "number_of_trades": total_trades,
        "win_rate": float((trades["net_pnl"] > 0).mean()) if not trades.empty else 0.0,
        "average_trade_pnl": float(trades["net_pnl"].mean()) if not trades.empty else 0.0,
        "max_drawdown": float(summaries["max_drawdown"].min()),
        "positive_windows": int((summaries["net_pnl"] > 0).sum()),
        "total_windows": len(summaries),
    }


def apply_backtest_params(config: dict, params: dict[str, Any]) -> dict:
    output = dict(config)
    output["historical_data"] = dict(config["historical_data"])
    output["backtest"] = dict(config["backtest"])
    output["backtest"].update(params)
    return output
