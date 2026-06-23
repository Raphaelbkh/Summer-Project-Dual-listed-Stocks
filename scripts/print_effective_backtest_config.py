"""Print effective offline backtest parameters without running a backtest."""

from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest_tradingview_walk_forward import apply_cli_overrides, parse_args  # noqa: E402
from src.backtest.walk_forward_backtest import (  # noqa: E402
    _effective_parameter_report,
    resolve_effective_backtest_config,
)


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def main() -> None:
    args = parse_args()
    if args.pair_id is None:
        raise SystemExit("--pair-id is required for effective config diagnostics.")
    config = apply_cli_overrides(load_config(PROJECT_ROOT / args.config), args)
    effective, sources = resolve_effective_backtest_config(config, args.pair_id)
    report = _effective_parameter_report(args.pair_id, effective, sources)
    print(yaml.safe_dump(report, sort_keys=False))


if __name__ == "__main__":
    main()
