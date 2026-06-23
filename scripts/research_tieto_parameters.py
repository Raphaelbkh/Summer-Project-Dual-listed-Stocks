"""Research-only parameter grid for Tieto offline walk-forward backtests."""

from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest.research_tools import (  # noqa: E402
    aggregate_results,
    apply_backtest_params,
    load_active_backtest_pairs,
    load_yaml_config,
    run_walk_forward_for_pairs,
)


GRID = {
    "lookback_bars": [50, 100, 200, 400],
    "entry_zscore": [2.0, 2.25, 2.5, 2.75, 3.0],
    "exit_zscore": [0.0, 0.25, 0.5, 0.75],
    "max_holding_bars": [10, 25, 50, 100],
    "min_expected_edge_bps": [0, 10, 20, 30, 40],
}


def parameter_grid() -> list[dict]:
    keys = list(GRID)
    return [dict(zip(keys, values)) for values in product(*(GRID[key] for key in keys))]


def main() -> None:
    config = load_yaml_config(PROJECT_ROOT / "config" / "config.yaml")
    config["historical_data"]["base_path"] = str(PROJECT_ROOT / "data" / "historical" / "tradingview")
    pairs = load_active_backtest_pairs(
        PROJECT_ROOT / "data" / "mappings" / "backtest_pairs.csv",
        "tieto_fi_se",
    )

    rows = []
    for params in parameter_grid():
        results = run_walk_forward_for_pairs(pairs, apply_backtest_params(config, params))
        row = aggregate_results(results)
        row.update(params)
        rows.append(row)

    output_path = (
        PROJECT_ROOT
        / "data"
        / "backtests"
        / f"tieto_parameter_research_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    pd.DataFrame(rows).to_csv(output_path, index=False)
    print(f"tieto_parameter_research_output: {output_path}")


if __name__ == "__main__":
    main()
