"""Resolved listing and pair mapping helpers."""

from dataclasses import asdict, is_dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd


RESOLVED_LISTING_COLUMNS = [
    "watchlist_ticker",
    "resolved_symbol",
    "company_name",
    "exchange",
    "currency",
    "country",
    "primary_exchange",
    "sec_type",
    "ibkr_conid",
    "ibkr_local_symbol",
    "ibkr_trading_class",
    "resolution_source",
    "resolved_status",
    "rejection_reason",
    "notes",
]

RESOLVED_PAIR_COLUMNS = [
    "pair_id",
    "source_ticker",
    "company_name",
    "long_symbol",
    "long_exchange",
    "long_currency",
    "short_symbol",
    "short_exchange",
    "short_currency",
    "fx_pair",
    "conversion_ratio",
    "active",
    "resolved_status",
    "resolution_source",
    "rejection_reason",
    "notes",
]

SUPPORTED_CURRENCIES = {"SEK", "EUR", "DKK"}
UNSUPPORTED_CURRENCIES = {"NOK"}
UNSUPPORTED_MARKET_MARKERS = {"NORWAY", "OSLO", "OSLO BORS", "OSLO BØRS", "EURONEXT OSLO"}


def _candidate_to_dict(candidate: Any) -> dict[str, Any]:
    if is_dataclass(candidate):
        return asdict(candidate)
    return dict(candidate)


def _normalized(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def write_resolved_listings(candidates: list[Any], path: Path) -> None:
    """Write resolved listing candidates using the canonical CSV schema."""
    rows = [_candidate_to_dict(candidate) for candidate in candidates]
    df = pd.DataFrame(rows, columns=RESOLVED_LISTING_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def load_resolved_listings(path: Path) -> pd.DataFrame:
    """Load resolved listings from disk without changing their contents."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _infer_fx_pair(long_currency: str, short_currency: str) -> str:
    currencies = {_normalized(long_currency), _normalized(short_currency)}
    if len(currencies) == 1:
        return ""
    if currencies == {"SEK", "EUR"}:
        return "EURSEK"
    if currencies == {"EUR", "DKK"}:
        return "EURDKK"
    if currencies == {"SEK", "DKK"}:
        return "DKKSEK"
    return ""


def _deterministic_pair_id(source_ticker: str, long_row: pd.Series, short_row: pd.Series) -> str:
    parts = [
        source_ticker,
        _normalized(long_row["resolved_symbol"]),
        _normalized(long_row["primary_exchange"] or long_row["exchange"]),
        _normalized(long_row["currency"]),
        _normalized(short_row["resolved_symbol"]),
        _normalized(short_row["primary_exchange"] or short_row["exchange"]),
        _normalized(short_row["currency"]),
    ]
    return "|".join(parts)


def _is_supported_resolved_listing(row: pd.Series) -> bool:
    if _normalized(row.get("resolved_status")) != "RESOLVED":
        return False
    currency = _normalized(row.get("currency"))
    if currency in UNSUPPORTED_CURRENCIES or currency not in SUPPORTED_CURRENCIES:
        return False
    market_text = " ".join(
        [
            str(row.get("country", "")),
            str(row.get("exchange", "")),
            str(row.get("primary_exchange", "")),
        ]
    )
    market_upper = _normalized(market_text)
    return not any(marker in market_upper for marker in UNSUPPORTED_MARKET_MARKERS)


def generate_pair_candidates_from_resolved_listings(
    resolved_listings: pd.DataFrame,
) -> pd.DataFrame:
    """Generate inactive pair candidates from listings for the same user ticker."""
    if resolved_listings.empty:
        return pd.DataFrame(columns=RESOLVED_PAIR_COLUMNS)

    rows: list[dict[str, Any]] = []
    supported = resolved_listings[
        resolved_listings.apply(_is_supported_resolved_listing, axis=1)
    ].copy()
    if supported.empty:
        return pd.DataFrame(columns=RESOLVED_PAIR_COLUMNS)

    sort_columns = [
        "watchlist_ticker",
        "resolved_symbol",
        "primary_exchange",
        "exchange",
        "currency",
        "ibkr_conid",
    ]
    supported = supported.sort_values(sort_columns, kind="stable")

    for source_ticker, group in supported.groupby("watchlist_ticker", sort=True):
        if len(group) < 2:
            continue

        for _, pair_rows in enumerate(combinations(group.to_dict("records"), 2)):
            long_row = pd.Series(pair_rows[0])
            short_row = pd.Series(pair_rows[1])
            long_exchange = long_row["primary_exchange"] or long_row["exchange"]
            short_exchange = short_row["primary_exchange"] or short_row["exchange"]

            rows.append(
                {
                    "pair_id": _deterministic_pair_id(source_ticker, long_row, short_row),
                    "source_ticker": source_ticker,
                    "company_name": long_row.get("company_name", ""),
                    "long_symbol": long_row["resolved_symbol"],
                    "long_exchange": long_exchange,
                    "long_currency": long_row["currency"],
                    "short_symbol": short_row["resolved_symbol"],
                    "short_exchange": short_exchange,
                    "short_currency": short_row["currency"],
                    "fx_pair": _infer_fx_pair(
                        long_row["currency"],
                        short_row["currency"],
                    ),
                    "conversion_ratio": 1.0,
                    "active": False,
                    "resolved_status": "pending_user_review",
                    "resolution_source": "system_generated_from_resolved_listings",
                    "rejection_reason": "",
                    "notes": "conversion_ratio should be manually verified before activation",
                }
            )

    pairs = pd.DataFrame(rows, columns=RESOLVED_PAIR_COLUMNS)
    if not pairs.empty:
        pairs["active"] = pairs["active"].astype(object)
    return pairs


def validate_resolved_pairs(df: pd.DataFrame) -> None:
    """Validate resolved pair rows for MVP market and activation safety rules."""
    missing_columns = set(RESOLVED_PAIR_COLUMNS) - set(df.columns)
    if missing_columns:
        raise ValueError(
            "resolved_pairs.csv missing required columns: "
            + ", ".join(sorted(missing_columns))
        )

    for _, row in df.iterrows():
        currencies = {
            _normalized(row["long_currency"]),
            _normalized(row["short_currency"]),
        }
        if currencies & UNSUPPORTED_CURRENCIES:
            raise ValueError("resolved pairs must not include NOK in MVP.")

        market_text = " ".join(
            [
                str(row["long_exchange"]),
                str(row["short_exchange"]),
                str(row.get("notes", "")),
            ]
        )
        market_upper = _normalized(market_text)
        if any(marker in market_upper for marker in UNSUPPORTED_MARKET_MARKERS):
            raise ValueError("resolved pairs must not include Norway/Oslo markets in MVP.")


def get_active_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """Return only pairs manually marked active=true without mutating input."""
    active_values = df["active"].map(lambda value: _normalized(value) == "TRUE")
    return df.loc[active_values].copy()
