"""Resolve user-provided watchlist tickers into internal mapping CSV files."""

from pathlib import Path
import asyncio
import sys

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.ibkr_contract_resolver import (  # noqa: E402
    ResolvedListingCandidate,
    resolve_watchlist_ticker_with_ibkr,
)
from src.data.live.ibkr_market_data import (  # noqa: E402
    load_ibkr_connection_config,
    resolve_ibkr_port,
)
from src.data.mappings.listing_master import (  # noqa: E402
    RESOLVED_PAIR_COLUMNS,
    generate_pair_candidates_from_resolved_listings,
    load_resolved_listings,
    validate_resolved_pairs,
    write_resolved_listings,
)
from src.data.mappings.watchlist import load_user_watchlist, normalize_ticker  # noqa: E402


SETTINGS_PATH = PROJECT_ROOT / "config" / "config.yaml"


class IBKRWatchlistContractClient:
    """Small adapter that requests contract details for one user ticker at a time."""

    def __init__(self, ib_client) -> None:
        self.ib = ib_client

    def reqContractDetails(self, ticker: str):
        from ib_async import Stock

        contract = Stock(ticker, "SMART", "")
        return self.ib.reqContractDetails(contract)


def load_config() -> dict:
    with SETTINGS_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def rejected_rows_from_candidates(
    candidates: list[ResolvedListingCandidate],
) -> list[dict[str, str]]:
    rows = []
    for candidate in candidates:
        if candidate.resolved_status in {"resolved", "ambiguous", "pending_user_review"}:
            continue
        rows.append(
            {
                "ticker": candidate.watchlist_ticker,
                "rejection_reason": candidate.rejection_reason
                or candidate.resolved_status,
                "notes": candidate.notes,
            }
        )
    return rows


def write_rejected_rows(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["ticker", "rejection_reason", "notes"]).to_csv(
        path,
        index=False,
    )


def main() -> None:
    config_dict = load_config()
    connection_config = load_ibkr_connection_config(config_dict)
    port = resolve_ibkr_port(connection_config)
    universe_config = config_dict["universe_selection"]

    watchlist_path = PROJECT_ROOT / universe_config["user_watchlist_path"]
    resolved_listings_path = PROJECT_ROOT / universe_config["resolved_listings_path"]
    resolved_pairs_path = PROJECT_ROOT / universe_config["resolved_pairs_path"]
    rejected_watchlist_path = PROJECT_ROOT / universe_config["rejected_watchlist_path"]

    watchlist = load_user_watchlist(watchlist_path)
    tickers = [normalize_ticker(ticker) for ticker in watchlist["ticker"]]

    ensure_event_loop()
    from ib_async import IB

    ib = IB()
    all_candidates: list[ResolvedListingCandidate] = []
    rejected_rows: list[dict[str, str]] = []

    try:
        ib.connect(
            connection_config.host,
            port,
            clientId=connection_config.client_id_market_data,
        )
        resolver_client = IBKRWatchlistContractClient(ib)

        for ticker in tickers:
            candidates = resolve_watchlist_ticker_with_ibkr(resolver_client, ticker)
            all_candidates.extend(candidates)
            rejected_rows.extend(rejected_rows_from_candidates(candidates))

        write_resolved_listings(all_candidates, resolved_listings_path)
        write_rejected_rows(rejected_rows, rejected_watchlist_path)

        resolved_listings = load_resolved_listings(resolved_listings_path)
        resolved_pairs = generate_pair_candidates_from_resolved_listings(
            resolved_listings,
        )
        if resolved_pairs.empty:
            resolved_pairs = pd.DataFrame(columns=RESOLVED_PAIR_COLUMNS)
        validate_resolved_pairs(resolved_pairs)
        resolved_pairs.to_csv(resolved_pairs_path, index=False)

        print(f"watchlist_tickers: {len(tickers)}")
        print(f"resolved_listing_rows: {len(all_candidates)}")
        print(f"rejected_watchlist_rows: {len(rejected_rows)}")
        print(f"resolved_pair_rows: {len(resolved_pairs)}")
        print(f"wrote: {resolved_listings_path}")
        print(f"wrote: {rejected_watchlist_path}")
        print(f"wrote: {resolved_pairs_path}")
    finally:
        if ib.isConnected():
            ib.disconnect()


if __name__ == "__main__":
    main()
