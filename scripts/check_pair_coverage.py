"""Print per-pair historical CSV coverage for offline backtests."""

from pathlib import Path
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest.historical_pair_data import (  # noqa: E402
    align_pair_bars,
    effective_common_start,
    true_common_end,
    true_common_start,
)
from src.data.historical.tradingview_csv_loader import load_tradingview_csv  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
MAPPING_PATH = PROJECT_ROOT / "data" / "mappings" / "backtest_pairs.csv"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def pair_coverage(row: pd.Series, config: dict) -> dict:
    base_path = Path(config["historical_data"]["base_path"])
    if not base_path.is_absolute():
        base_path = PROJECT_ROOT / base_path

    long_df = load_tradingview_csv(base_path / row["long_csv_file"])
    short_df = load_tradingview_csv(base_path / row["short_csv_file"])
    fx_df = None
    if str(row.get("fx_csv_file", "")).strip():
        fx_df = load_tradingview_csv(base_path / row["fx_csv_file"])

    aligned = align_pair_bars(long_df, short_df, fx_df, config, row)
    effective_start = effective_common_start(long_df, short_df, fx_df, row)
    aligned_after_start = aligned.loc[aligned.index >= effective_start]
    return {
        "pair_id": row["pair_id"],
        "long_first": long_df.index.min(),
        "long_last": long_df.index.max(),
        "short_first": short_df.index.min(),
        "short_last": short_df.index.max(),
        "fx_first": fx_df.index.min() if fx_df is not None else None,
        "fx_last": fx_df.index.max() if fx_df is not None else None,
        "true_common_start": true_common_start(long_df, short_df, fx_df),
        "effective_common_start": effective_start,
        "true_common_end": true_common_end(long_df, short_df, fx_df),
        "aligned_bars": len(aligned_after_start),
        "active": row["active"],
    }


def main() -> None:
    config = load_config()
    pairs = pd.read_csv(MAPPING_PATH, dtype=str, keep_default_na=False)
    for _, row in pairs.iterrows():
        coverage = pair_coverage(row, config)
        print(
            " | ".join(
                [
                    f"pair_id={coverage['pair_id']}",
                    f"long={coverage['long_first']}..{coverage['long_last']}",
                    f"short={coverage['short_first']}..{coverage['short_last']}",
                    f"fx={coverage['fx_first']}..{coverage['fx_last']}",
                    f"true_common_start={coverage['true_common_start']}",
                    f"effective_common_start={coverage['effective_common_start']}",
                    f"true_common_end={coverage['true_common_end']}",
                    f"aligned_bars={coverage['aligned_bars']}",
                    f"active={coverage['active']}",
                ]
            )
        )
    data_path = Path(config["historical_data"]["base_path"])
    if not data_path.is_absolute():
        data_path = PROJECT_ROOT / data_path
    expected_sampo = [
        data_path / "OMXHEX_DLY_SAMPO_60.csv",
        data_path / "OMXSTO_DLY_SAMPO_SEK_60.csv",
    ]
    missing_sampo = [path.name for path in expected_sampo if not path.exists()]
    if missing_sampo:
        print("warning: sampo_fi_se skipped because files are missing: " + ", ".join(missing_sampo))


if __name__ == "__main__":
    main()
