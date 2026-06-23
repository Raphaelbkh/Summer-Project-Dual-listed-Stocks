from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from scripts.observe_ibkr_spreads import apply_entry_hour_gate
from src.data.live.quote_models import EquityQuote, FXQuote, SpreadSnapshot
from src.execution.entry_policy import (
    EXCLUDED_ENTRY_HOUR_REASON,
    build_excluded_entry_signal,
    execution_action_allowed,
    log_excluded_entry_signal,
)


def equity_quote(symbol: str, currency: str, bid: float, ask: float) -> EquityQuote:
    return EquityQuote(
        symbol=symbol,
        exchange="TEST",
        currency=currency,
        bid=bid,
        ask=ask,
        bid_size=10,
        ask_size=10,
        last=None,
        timestamp=datetime(2026, 6, 18, 15, 0, tzinfo=timezone.utc),
    )


def fx_quote() -> FXQuote:
    return FXQuote(
        pair="EURSEK",
        base_currency="EUR",
        quote_currency="SEK",
        bid=11.0,
        ask=11.1,
        last=None,
        timestamp=datetime(2026, 6, 18, 15, 0, tzinfo=timezone.utc),
    )


def paper_profile_config() -> dict:
    return {
        "execution": {"active_strategy_profile": "tieto_30m_paper_start"},
        "strategy_profiles": {
            "tieto_30m_paper_start": {
                "pair_id": "tieto_fi_se",
                "exclude_entry_hours_utc": [15, 16],
            }
        },
    }


def spread_snapshot(hour: int = 15) -> SpreadSnapshot:
    return SpreadSnapshot(
        timestamp=datetime(2026, 6, 18, hour, 0, tzinfo=timezone.utc),
        pair_id="tieto_fi_se",
        long_leg_symbol="TIETO",
        short_leg_symbol="TIETOS",
        long_leg_exchange="HEX",
        short_leg_exchange="SFB",
        long_leg_currency="EUR",
        short_leg_currency="SEK",
        long_leg_ask=20.1,
        short_leg_bid=222.0,
        fx_pair="EURSEK",
        fx_bid=11.0,
        fx_ask=11.1,
        gross_edge=0.008,
        cost_buffer_bps=20,
        net_edge=0.006,
        signal=True,
        rejection_reason=None,
    )


def test_new_entries_are_blocked_during_15_and_16_utc() -> None:
    excluded = [15, 16]

    assert not execution_action_allowed(
        "ENTRY", datetime(2026, 6, 18, 15, tzinfo=timezone.utc), excluded
    )
    assert not execution_action_allowed(
        "ENTRY", datetime(2026, 6, 18, 16, tzinfo=timezone.utc), excluded
    )
    assert execution_action_allowed(
        "ENTRY", datetime(2026, 6, 18, 14, tzinfo=timezone.utc), excluded
    )


def test_exits_remain_allowed_during_excluded_hours() -> None:
    assert execution_action_allowed(
        "EXIT",
        datetime(2026, 6, 18, 15, tzinfo=timezone.utc),
        [15, 16],
    )
    assert execution_action_allowed(
        "EXIT",
        datetime(2026, 6, 18, 16, tzinfo=timezone.utc),
        [15, 16],
    )


def test_excluded_entry_signal_is_logged_with_quotes(tmp_path: Path) -> None:
    signal = build_excluded_entry_signal(
        timestamp=datetime(2026, 6, 18, 15, tzinfo=timezone.utc),
        pair_id="tieto_fi_se",
        direction="SHORT_SWEDEN_LONG_FINLAND",
        zscore=2.2,
        spread_pct=0.008,
        expected_edge_bps=60,
        sweden_quote=equity_quote("TIETOS", "SEK", 221, 222),
        finland_quote=equity_quote("TIETO", "EUR", 20, 20.1),
        eursek_quote=fx_quote(),
    )

    path = log_excluded_entry_signal(signal, tmp_path)
    logged = pd.read_csv(path).iloc[0]

    assert logged["pair_id"] == "tieto_fi_se"
    assert logged["reason"] == EXCLUDED_ENTRY_HOUR_REASON
    assert logged["sweden_mid"] == 221.5
    assert logged["finland_mid"] == 20.05
    assert logged["eursek_mid"] == 11.05


def test_observer_gate_logs_and_suppresses_excluded_entry_signal() -> None:
    snapshot = spread_snapshot(15)
    logged = []

    allowed = apply_entry_hour_gate(
        snapshot,
        {
            "pair_id": "tieto_fi_se",
            "long_currency": "EUR",
            "short_currency": "SEK",
            "zscore": 2.2,
        },
        equity_quote("TIETO", "EUR", 20, 20.1),
        equity_quote("TIETOS", "SEK", 221, 222),
        fx_quote(),
        paper_profile_config(),
        Path("."),
        excluded_signal_logger=lambda signal, output_dir: logged.append(signal),
    )

    assert allowed is False
    assert snapshot.signal is False
    assert snapshot.rejection_reason == EXCLUDED_ENTRY_HOUR_REASON
    assert len(logged) == 1
    assert logged[0].zscore == 2.2
    assert logged[0].direction == "SHORT_SWEDEN_LONG_FINLAND"


def test_all_hours_research_and_paper_start_profiles_remain_available() -> None:
    with Path("config/config.yaml").open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    research = config["strategy_profiles"]["tieto_30m_research_all_hours"]
    paper = config["strategy_profiles"]["tieto_30m_paper_start"]

    assert research["exclude_entry_hours_utc"] == []
    assert paper["exclude_entry_hours_utc"] == [15, 16]
    for profile in (research, paper):
        assert profile["pair_id"] == "tieto_fi_se"
        assert profile["timeframe"] == "30m"
        assert profile["lookback_bars"] == 400
        assert profile["entry_zscore"] == 2.0
        assert profile["exit_zscore"] == 1.0
        assert profile["min_expected_edge_bps"] == 65
        assert profile["capital_fraction_per_trade"] == 0.25
