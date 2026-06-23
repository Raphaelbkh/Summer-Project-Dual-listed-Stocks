"""Print coverage metadata for TradingView CSV files."""

from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.historical.tradingview_csv_loader import (  # noqa: E402
    detect_time_format,
    load_tradingview_csv,
    normalize_tradingview_columns,
)


DATA_DIR = PROJECT_ROOT / "data" / "historical" / "tradingview"


def csv_coverage(path: Path) -> dict:
    raw = normalize_tradingview_columns(pd.read_csv(path))
    time_format = detect_time_format(raw["timestamp"])
    duplicate_count = int(raw["timestamp"].duplicated().sum())
    df = load_tradingview_csv(path)
    intervals = df.index.to_series().diff().dropna()
    median_interval = intervals.median() if not intervals.empty else None
    return {
        "filename": path.name,
        "first_timestamp_utc": df.index.min(),
        "last_timestamp_utc": df.index.max(),
        "row_count": len(df),
        "duplicate_timestamp_count": duplicate_count,
        "inferred_median_interval": median_interval,
        "detected_time_format": time_format,
    }


def main() -> None:
    for path in sorted(DATA_DIR.glob("*.csv")):
        coverage = csv_coverage(path)
        print(
            " | ".join(
                [
                    f"filename={coverage['filename']}",
                    f"first={coverage['first_timestamp_utc']}",
                    f"last={coverage['last_timestamp_utc']}",
                    f"rows={coverage['row_count']}",
                    f"duplicates={coverage['duplicate_timestamp_count']}",
                    f"median_interval={coverage['inferred_median_interval']}",
                    f"time_format={coverage['detected_time_format']}",
                ]
            )
        )


if __name__ == "__main__":
    main()
