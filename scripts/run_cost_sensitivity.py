"""Run offline walk-forward cost sensitivity research."""

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_tradingview_walk_forward import COST_PRESETS  # noqa: E402
from src.backtest.research_tools import (  # noqa: E402
    aggregate_results,
    apply_backtest_params,
    load_active_backtest_pairs,
    load_yaml_config,
    run_walk_forward_for_pairs,
)


def parse_args():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--pair-id", default=None)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--mapping", default="data/mappings/backtest_pairs.csv")
    parser.add_argument("--data-dir", default="data/historical/tradingview")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_yaml_config(PROJECT_ROOT / args.config)
    config["historical_data"]["base_path"] = str(PROJECT_ROOT / args.data_dir)
    pairs = load_active_backtest_pairs(PROJECT_ROOT / args.mapping, args.pair_id)

    rows = []
    for preset_name, (commission, half_spread, slippage) in COST_PRESETS.items():
        preset_config = apply_backtest_params(
            config,
            {
                "commission_bps_per_leg": commission,
                "estimated_half_spread_bps_per_leg": half_spread,
                "slippage_bps_per_leg": slippage,
            },
        )
        results = run_walk_forward_for_pairs(pairs, preset_config)
        by_pair = {}
        for result in results:
            by_pair.setdefault(result.pair_id, []).append(result)
        for pair_id, pair_results in by_pair.items():
            row = aggregate_results(pair_results)
            row.update(
                {
                    "cost_preset": preset_name,
                    "commission_bps_per_leg": commission,
                    "half_spread_bps_per_leg": half_spread,
                    "slippage_bps_per_leg": slippage,
                    "pair_id": pair_id,
                }
            )
            rows.append(row)

    output_path = (
        PROJECT_ROOT
        / "data"
        / "backtests"
        / f"cost_sensitivity_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)
    print(f"cost_sensitivity_output: {output_path}")


if __name__ == "__main__":
    main()
