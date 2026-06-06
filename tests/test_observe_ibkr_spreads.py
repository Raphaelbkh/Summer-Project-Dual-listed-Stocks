from pathlib import Path

import pandas as pd

from scripts import observe_ibkr_spreads as observer
from src.data.live.quote_models import EquityQuote, FXQuote
from src.data.mappings.listing_master import RESOLVED_PAIR_COLUMNS
from src.utils.time_utils import utc_now


def config_dict() -> dict:
    return {
        "execution": {
            "observe_only": True,
            "default_cost_buffer_bps": 20,
            "min_required_net_edge_bps": 30,
        },
        "universe_selection": {
            "allow_auto_discovery": False,
            "allow_auto_screening": False,
            "allow_ai_generated_tickers": False,
            "allow_auto_activation": False,
            "live_test_pairs_path": "data/mappings/ibkr_live_test_pairs.csv",
            "resolved_pairs_path": "data/mappings/resolved_pairs.csv",
        },
        "fx": {"max_quote_age_seconds": 99999999},
        "polling": {"interval_seconds": 0},
        "logging": {
            "live_quotes_dir": "data/live_quotes",
            "live_spreads_dir": "data/live_spreads",
        },
        "ibkr": {"client_id_fx": 2},
    }


def pair_row(pair_id: str, active: object = True, long_symbol: str = "AAA") -> dict:
    row = {column: "" for column in RESOLVED_PAIR_COLUMNS}
    row.update(
        {
            "pair_id": pair_id,
            "source_ticker": "USER",
            "company_name": "User Company",
            "long_symbol": long_symbol,
            "long_exchange": "NASDAQ STOCKHOLM",
            "long_currency": "SEK",
            "short_symbol": "BBB",
            "short_exchange": "NASDAQ HELSINKI",
            "short_currency": "EUR",
            "fx_pair": "EURSEK",
            "conversion_ratio": 1.0,
            "active": active,
            "resolved_status": "pending_user_review",
            "resolution_source": "test",
        }
    )
    return row


def write_pairs(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=RESOLVED_PAIR_COLUMNS).to_csv(path, index=False)


class FakeEquityProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def get_equity_quote(
        self,
        symbol: str,
        exchange: str,
        currency: str,
    ) -> EquityQuote:
        self.calls.append((symbol, exchange, currency))
        if symbol == "BAD":
            raise ValueError("qualification failed")
        if currency == "SEK":
            bid = 99.0
            ask = 100.0
        else:
            bid = 10.0
            ask = 10.1
        return EquityQuote(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            bid=bid,
            ask=ask,
            bid_size=10.0,
            ask_size=10.0,
            last=999999.0,
            timestamp=utc_now(),
        )


class FakeFXProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_fx_quote(self, pair: str) -> FXQuote:
        self.calls.append(pair)
        return FXQuote(
            pair=pair,
            base_currency="EUR",
            quote_currency="SEK",
            bid=11.0,
            ask=11.1,
            last=999999.0,
            timestamp=utc_now(),
        )


def noop_logger(obj, output_dir: Path) -> Path:
    return output_dir / "noop.csv"


def test_inactive_pairs_are_ignored(tmp_path: Path, monkeypatch) -> None:
    live_path = tmp_path / "data" / "mappings" / "ibkr_live_test_pairs.csv"
    resolved_path = tmp_path / "data" / "mappings" / "resolved_pairs.csv"
    write_pairs(live_path, [pair_row("inactive", active=False)])
    write_pairs(
        resolved_path,
        [pair_row("active", active="true"), pair_row("inactive2", active="false")],
    )
    monkeypatch.setattr(observer, "PROJECT_ROOT", tmp_path)

    active_pairs = observer.load_active_pair_rows(config_dict())

    assert list(active_pairs["pair_id"]) == ["active"]


def test_bad_pair_does_not_stop_another_pair(tmp_path: Path) -> None:
    active_pairs = pd.DataFrame(
        [
            pair_row("bad", active=True, long_symbol="BAD"),
            pair_row("good", active=True, long_symbol="AAA"),
        ]
    )
    equity_provider = FakeEquityProvider()
    fx_provider = FakeFXProvider()

    snapshots = observer.run_observer_once(
        active_pairs,
        equity_provider,
        fx_provider,
        config_dict(),
        tmp_path,
        tmp_path,
        equity_logger=noop_logger,
        fx_logger=noop_logger,
        spread_logger=noop_logger,
    )

    assert len(snapshots) == 1
    assert snapshots[0].pair_id == "good"


def test_no_pair_is_generated_or_activated(tmp_path: Path, monkeypatch) -> None:
    live_path = tmp_path / "data" / "mappings" / "ibkr_live_test_pairs.csv"
    resolved_path = tmp_path / "data" / "mappings" / "resolved_pairs.csv"
    write_pairs(live_path, [])
    write_pairs(resolved_path, [pair_row("inactive", active="false")])
    before = resolved_path.read_text(encoding="utf-8")
    monkeypatch.setattr(observer, "PROJECT_ROOT", tmp_path)

    active_pairs = observer.load_active_pair_rows(config_dict())

    after = resolved_path.read_text(encoding="utf-8")
    assert active_pairs.empty
    assert after == before


def test_max_iterations_stops(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run_observer_once(*args, **kwargs):
        calls.append("called")
        return []

    monkeypatch.setattr(observer, "run_observer_once", fake_run_observer_once)
    monkeypatch.setattr(observer.time, "sleep", lambda seconds: None)

    observer.run_observer_loop(
        pd.DataFrame([pair_row("active", active=True)]),
        object(),
        object(),
        config_dict(),
        tmp_path,
        tmp_path,
        max_iterations=2,
    )

    assert calls == ["called", "called"]
