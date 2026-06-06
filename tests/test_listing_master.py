from pathlib import Path

import pandas as pd
import pytest

from src.data.live.ibkr_contract_resolver import ResolvedListingCandidate
from src.data.mappings.listing_master import (
    RESOLVED_PAIR_COLUMNS,
    generate_pair_candidates_from_resolved_listings,
    get_active_pairs,
    load_resolved_listings,
    validate_resolved_pairs,
    write_resolved_listings,
)


def listing(
    *,
    watchlist_ticker: str = "ABC",
    resolved_symbol: str = "ABC",
    exchange: str = "SMART",
    currency: str = "SEK",
    country: str = "Sweden",
    primary_exchange: str = "NASDAQ STOCKHOLM",
    conid: int = 1,
) -> dict[str, object]:
    return {
        "watchlist_ticker": watchlist_ticker,
        "resolved_symbol": resolved_symbol,
        "company_name": "ABC Company",
        "exchange": exchange,
        "currency": currency,
        "country": country,
        "primary_exchange": primary_exchange,
        "sec_type": "STK",
        "ibkr_conid": conid,
        "ibkr_local_symbol": resolved_symbol,
        "ibkr_trading_class": resolved_symbol,
        "resolution_source": "IBKR",
        "resolved_status": "resolved",
        "rejection_reason": "",
        "notes": "",
    }


def test_write_and_load_resolved_listings(tmp_path: Path) -> None:
    candidate = ResolvedListingCandidate(**listing())
    path = tmp_path / "resolved_listings.csv"

    write_resolved_listings([candidate], path)
    loaded = load_resolved_listings(path)

    assert list(loaded["watchlist_ticker"]) == ["ABC"]
    assert list(loaded["currency"]) == ["SEK"]


def test_pair_candidates_generated_from_two_listings_of_same_ticker() -> None:
    df = pd.DataFrame(
        [
            listing(currency="SEK", primary_exchange="NASDAQ STOCKHOLM", conid=1),
            listing(currency="EUR", country="Finland", primary_exchange="NASDAQ HELSINKI", conid=2),
        ]
    )

    pairs = generate_pair_candidates_from_resolved_listings(df)

    assert len(pairs) == 1
    assert pairs.iloc[0]["source_ticker"] == "ABC"
    assert pairs.iloc[0]["long_symbol"] == "ABC"
    assert pairs.iloc[0]["short_symbol"] == "ABC"


def test_no_pair_generated_from_only_one_listing() -> None:
    pairs = generate_pair_candidates_from_resolved_listings(pd.DataFrame([listing()]))

    assert pairs.empty
    assert list(pairs.columns) == RESOLVED_PAIR_COLUMNS


def test_generated_pairs_active_false_by_default() -> None:
    df = pd.DataFrame(
        [
            listing(currency="SEK", primary_exchange="NASDAQ STOCKHOLM", conid=1),
            listing(currency="EUR", country="Finland", primary_exchange="NASDAQ HELSINKI", conid=2),
        ]
    )

    pairs = generate_pair_candidates_from_resolved_listings(df)

    assert pairs.iloc[0]["active"] is False


def test_deterministic_pair_id() -> None:
    first = pd.DataFrame(
        [
            listing(currency="EUR", country="Finland", primary_exchange="NASDAQ HELSINKI", conid=2),
            listing(currency="SEK", primary_exchange="NASDAQ STOCKHOLM", conid=1),
        ]
    )
    second = first.iloc[::-1].reset_index(drop=True)

    first_pair_id = generate_pair_candidates_from_resolved_listings(first).iloc[0]["pair_id"]
    second_pair_id = generate_pair_candidates_from_resolved_listings(second).iloc[0]["pair_id"]

    assert first_pair_id == second_pair_id


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("SEK", "EUR", "EURSEK"),
        ("EUR", "SEK", "EURSEK"),
        ("EUR", "DKK", "EURDKK"),
        ("DKK", "EUR", "EURDKK"),
        ("SEK", "DKK", "DKKSEK"),
        ("DKK", "SEK", "DKKSEK"),
    ],
)
def test_fx_pair_inferred_correctly(left: str, right: str, expected: str) -> None:
    df = pd.DataFrame(
        [
            listing(currency=left, conid=1),
            listing(currency=right, country="Finland", primary_exchange="NASDAQ HELSINKI", conid=2),
        ]
    )

    pairs = generate_pair_candidates_from_resolved_listings(df)

    assert pairs.iloc[0]["fx_pair"] == expected


def test_same_currency_requires_no_fx_pair() -> None:
    df = pd.DataFrame(
        [
            listing(currency="SEK", primary_exchange="NASDAQ STOCKHOLM", conid=1),
            listing(currency="SEK", primary_exchange="NASDAQ COPENHAGEN", country="Denmark", conid=2),
        ]
    )

    pairs = generate_pair_candidates_from_resolved_listings(df)

    assert pairs.iloc[0]["fx_pair"] == ""


def test_conversion_ratio_defaults_to_one() -> None:
    df = pd.DataFrame(
        [
            listing(currency="SEK", conid=1),
            listing(currency="EUR", country="Finland", primary_exchange="NASDAQ HELSINKI", conid=2),
        ]
    )

    pairs = generate_pair_candidates_from_resolved_listings(df)

    assert pairs.iloc[0]["conversion_ratio"] == 1.0


def test_notes_mention_manual_verification() -> None:
    df = pd.DataFrame(
        [
            listing(currency="SEK", conid=1),
            listing(currency="EUR", country="Finland", primary_exchange="NASDAQ HELSINKI", conid=2),
        ]
    )

    pairs = generate_pair_candidates_from_resolved_listings(df)

    assert "manually verified" in pairs.iloc[0]["notes"]


def test_get_active_pairs_only_returns_manually_active_rows() -> None:
    df = pd.DataFrame(
        [
            {"pair_id": "inactive", "active": False},
            {"pair_id": "active", "active": "true"},
        ]
    )

    active = get_active_pairs(df)

    assert list(active["pair_id"]) == ["active"]
    assert list(df["active"]) == [False, "true"]


def test_validation_rejects_nok() -> None:
    df = pd.DataFrame(
        [
            {
                **{column: "" for column in RESOLVED_PAIR_COLUMNS},
                "long_currency": "NOK",
                "short_currency": "SEK",
                "active": False,
            }
        ]
    )

    with pytest.raises(ValueError, match="NOK"):
        validate_resolved_pairs(df)


def test_validation_rejects_oslo() -> None:
    df = pd.DataFrame(
        [
            {
                **{column: "" for column in RESOLVED_PAIR_COLUMNS},
                "long_exchange": "EURONEXT OSLO",
                "short_exchange": "NASDAQ STOCKHOLM",
                "long_currency": "EUR",
                "short_currency": "SEK",
                "active": False,
            }
        ]
    )

    with pytest.raises(ValueError, match="Oslo"):
        validate_resolved_pairs(df)


def test_code_does_not_create_new_ticker_symbols() -> None:
    df = pd.DataFrame(
        [
            listing(watchlist_ticker="USER", resolved_symbol="AAA", currency="SEK", conid=1),
            listing(
                watchlist_ticker="USER",
                resolved_symbol="BBB",
                currency="EUR",
                country="Finland",
                primary_exchange="NASDAQ HELSINKI",
                conid=2,
            ),
        ]
    )

    pairs = generate_pair_candidates_from_resolved_listings(df)

    output_symbols = set(pairs["long_symbol"]) | set(pairs["short_symbol"])
    assert output_symbols == {"AAA", "BBB"}
    assert set(pairs["source_ticker"]) == {"USER"}
