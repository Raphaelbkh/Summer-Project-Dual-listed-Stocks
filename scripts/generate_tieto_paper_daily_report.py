"""Generate one dry-run Tieto paper-readiness daily CSV report."""

from argparse import ArgumentParser
from datetime import date
from pathlib import Path
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.paper.tieto_readiness import generate_daily_report, write_daily_report  # noqa: E402


def parse_args():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_date = date.fromisoformat(args.date)
    with (PROJECT_ROOT / "config" / "config.yaml").open(
        "r", encoding="utf-8"
    ) as config_file:
        config = yaml.safe_load(config_file)
    readiness = config["paper_readiness"]
    signal_path = (
        PROJECT_ROOT
        / readiness["signals_dir"]
        / f"paper_signals_{report_date:%Y%m%d}.csv"
    )
    signals = pd.read_csv(signal_path) if signal_path.exists() else pd.DataFrame()
    report = generate_daily_report(signals, report_date)
    output_path = write_daily_report(
        report,
        PROJECT_ROOT / readiness["reports_dir"],
        report_date,
    )
    print(f"paper_daily_report: {output_path}")


if __name__ == "__main__":
    main()
