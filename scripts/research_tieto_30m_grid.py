"""Run a small, fixed Tieto 30m robustness grid on offline CSV data."""

from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_tradingview_walk_forward import COST_PRESETS  # noqa: E402
from src.backtest.historical_pair_data import load_pair_history  # noqa: E402
from src.backtest.research_tools import (  # noqa: E402
    aggregate_results,
    apply_backtest_params,
    load_active_backtest_pairs,
    load_yaml_config,
)
from src.backtest.walk_forward_backtest import BacktestResult, WalkForwardBacktest  # noqa: E402


PAIR_ID = "tieto_fi_se"
TIMEFRAME = "30m"
COST_PRESET = "high"
CAPITAL_FRACTION_PER_TRADE = 0.25
GRID = {
    "lookback_bars": [300, 400, 600],
    "entry_zscore": [2.0],
    "exit_zscore": [0.5, 0.75, 1.0],
    "min_expected_edge_bps": [60, 65, 70],
}


def robustness_grid() -> list[dict]:
    keys = list(GRID)
    return [dict(zip(keys, values)) for values in product(*(GRID[key] for key in keys))]


def trade_concentration(results: list[BacktestResult]) -> dict[str, float | None]:
    trade_frames = [result.trades for result in results if not result.trades.empty]
    if not trade_frames:
        return {"top_1_trade_share": None, "top_3_trade_share": None}

    net_pnl = pd.concat(trade_frames, ignore_index=True)["net_pnl"].astype(float)
    total_net_pnl = float(net_pnl.sum())
    if total_net_pnl <= 0:
        return {"top_1_trade_share": None, "top_3_trade_share": None}

    ranked = net_pnl.sort_values(ascending=False)
    return {
        "top_1_trade_share": float(ranked.head(1).sum() / total_net_pnl),
        "top_3_trade_share": float(ranked.head(3).sum() / total_net_pnl),
    }


def candidate_row(params: dict, results: list[BacktestResult]) -> dict:
    aggregate = aggregate_results(results)
    return {
        "pair_id": PAIR_ID,
        "timeframe": TIMEFRAME,
        "cost_preset": COST_PRESET,
        "capital_fraction_per_trade": CAPITAL_FRACTION_PER_TRADE,
        **params,
        "total_net_pnl": aggregate["total_net_pnl"],
        "number_of_trades": aggregate["number_of_trades"],
        "average_trade_pnl": aggregate["average_trade_pnl"],
        "positive_windows": aggregate["positive_windows"],
        "total_windows": aggregate["total_windows"],
        "max_drawdown": aggregate["max_drawdown"],
        **trade_concentration(results),
    }


def main() -> None:
    config = load_yaml_config(PROJECT_ROOT / "config" / "config.yaml")
    config["historical_data"]["timeframe"] = TIMEFRAME
    config["historical_data"]["base_path"] = str(
        PROJECT_ROOT / "data" / "raw" / "tradingview" / "30m"
    )
    pair_row = load_active_backtest_pairs(
        PROJECT_ROOT / "data" / "mappings" / "backtest_pairs.csv",
        PAIR_ID,
    ).iloc[0]
    pair_df = load_pair_history(pair_row, config)
    engine = WalkForwardBacktest()
    commission, half_spread, slippage = COST_PRESETS[COST_PRESET]

    rows = []
    grid = robustness_grid()
    for index, params in enumerate(grid, start=1):
        candidate_config = apply_backtest_params(
            config,
            {
                **params,
                "capital_fraction_per_trade": CAPITAL_FRACTION_PER_TRADE,
                "commission_bps_per_leg": commission,
                "estimated_half_spread_bps_per_leg": half_spread,
                "slippage_bps_per_leg": slippage,
            },
        )
        results = engine.run_pair_walk_forward(PAIR_ID, pair_df, candidate_config)
        rows.append(candidate_row(params, results))
        print(f"candidate: {index}/{len(grid)}")

    output_path = (
        PROJECT_ROOT
        / "data"
        / "backtests"
        / f"tieto_30m_grid_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values("total_net_pnl", ascending=False).to_csv(
        output_path,
        index=False,
    )
    print(f"tieto_30m_grid_output: {output_path}")


if __name__ == "__main__":
    main()
