"""Validate Tieto contracts, quotes, spreads, and dry-run paper signals."""

from argparse import ArgumentParser
from dataclasses import asdict
from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ibkr_market_data import (  # noqa: E402
    IBKREquityMarketDataProvider,
    assert_no_live_trading_enabled,
    load_ibkr_connection_config,
    resolve_ibkr_port,
)
from src.fx.ibkr_fx import IBKRFXProvider  # noqa: E402
from src.paper.tieto_readiness import (  # noqa: E402
    build_paper_signal,
    executable_spread_metrics,
    log_market_snapshot,
    log_paper_signal,
    market_snapshot_rows,
    require_dry_run,
    validate_fx_contract,
    validate_stock_contract,
)
from src.utils.time_utils import utc_now  # noqa: E402


def parse_args():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step",
        choices=["contracts", "snapshot", "monitor", "all"],
        default="all",
    )
    parser.add_argument(
        "--direction",
        choices=["SHORT_SWEDEN_LONG_FINLAND", "LONG_SWEDEN_SHORT_FINLAND"],
        default="SHORT_SWEDEN_LONG_FINLAND",
    )
    parser.add_argument("--action", choices=["ENTRY", "EXIT"], default="ENTRY")
    parser.add_argument("--zscore", type=float, default=None)
    parser.add_argument(
        "--market-data-type",
        type=int,
        choices=[1, 3, 4],
        default=1,
        help="IBKR market data type: 1 live, 3 delayed, 4 delayed-frozen.",
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args()


def load_config() -> dict:
    with (PROJECT_ROOT / "config" / "config.yaml").open(
        "r", encoding="utf-8"
    ) as config_file:
        return yaml.safe_load(config_file)


def main() -> None:
    args = parse_args()
    require_dry_run(args.dry_run)
    assert_no_live_trading_enabled()
    config = load_config()
    readiness = config["paper_readiness"]
    if readiness.get("dry_run") is not True:
        raise RuntimeError("paper_readiness.dry_run must remain true")
    profile_name = readiness["profile_name"]
    profile = config["strategy_profiles"][profile_name]
    connection = load_ibkr_connection_config(config)
    if connection.mode != "paper":
        raise RuntimeError("Tieto readiness validation requires IBKR mode=paper.")
    port = resolve_ibkr_port(connection)
    equity = IBKREquityMarketDataProvider(
        connection.host,
        port,
        connection.client_id_market_data,
    )
    fx = IBKRFXProvider(
        connection.host,
        port,
        int(connection.client_id_fx or 2),
    )

    try:
        equity.connect()
        fx.connect()
        _set_market_data_type(equity.ib, args.market_data_type)
        _set_market_data_type(fx.ib, args.market_data_type)
        contracts = readiness["contracts"]
        if args.step in {"contracts", "all"}:
            validations = [
                validate_stock_contract(equity, "Tieto Finland", contracts["finland"]),
                validate_stock_contract(equity, "Tieto Sweden", contracts["sweden"]),
                validate_fx_contract(fx, contracts["fx_pair"]),
            ]
            for validation in validations:
                print(asdict(validation))
        if args.step in {"snapshot", "monitor", "all"}:
            finland_quote = equity.get_equity_quote(**contracts["finland"])
            sweden_quote = equity.get_equity_quote(**contracts["sweden"])
            eursek_quote = fx.get_fx_quote(contracts["fx_pair"])
            now = utc_now()
            snapshot = market_snapshot_rows(sweden_quote, finland_quote, eursek_quote)
            snapshot_path = log_market_snapshot(
                snapshot,
                PROJECT_ROOT / readiness["snapshots_dir"],
                now,
            )
            print(f"market_snapshot: {snapshot_path}")
            metrics = executable_spread_metrics(
                sweden_quote,
                finland_quote,
                eursek_quote,
            )
            print(metrics)
            if args.step in {"monitor", "all"}:
                signal = build_paper_signal(
                    timestamp=now,
                    profile_name=profile_name,
                    profile=profile,
                    action=args.action,
                    direction=args.direction,
                    zscore=args.zscore,
                    sweden=sweden_quote,
                    finland=finland_quote,
                    eursek=eursek_quote,
                    dry_run=True,
                )
                signal_path = log_paper_signal(
                    signal,
                    PROJECT_ROOT / readiness["signals_dir"],
                )
                print(f"paper_signal: {signal_path}")
                print(asdict(signal))
    finally:
        if equity.is_connected():
            equity.disconnect()
        if fx.is_connected():
            fx.disconnect()


def _set_market_data_type(client, market_data_type: int) -> None:
    request = getattr(client, "reqMarketDataType", None)
    if callable(request):
        request(market_data_type)


if __name__ == "__main__":
    main()
