from pathlib import Path

import pandas as pd
import pytest

from src.backtest.historical_pair_data import (
    align_pair_bars,
    load_pair_history,
    resolve_timeframe_csv_file,
)
from src.backtest.simulated_broker import SimulatedBroker
from src.backtest.walk_forward_backtest import (
    WalkForwardBacktest,
    build_trade_bucket_report,
    export_backtest_run,
    generate_walk_forward_windows,
    resolve_effective_backtest_config,
    validate_train_test_split,
)
from src.backtest.walk_forward_model import Signal, WalkForwardSpreadModel
from src.data.historical.tradingview_csv_loader import load_tradingview_csv
from scripts.backtest_tradingview_walk_forward import (
    COST_PRESETS,
    apply_cli_overrides,
    cost_values_from_args,
    parse_hour_list,
)
from scripts.check_historical_csv_coverage import csv_coverage
from scripts.check_pair_coverage import pair_coverage
from scripts.research_tieto_30m_grid import robustness_grid, trade_concentration
from scripts.walk_forward_optimize_tieto import (
    apply_optimizer_cli_config,
    choose_parameters_on_training,
    fixed_baseline_params,
    skipped_window_selection_row,
    validation_parameter_grid,
)


def write_csv(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def sample_config(base_path: Path) -> dict:
    return {
        "historical_data": {
            "provider": "TRADINGVIEW_CSV",
            "base_path": str(base_path),
            "timeframe": "60m",
            "timestamp_timezone": "Europe/Stockholm",
            "price_column": "close",
            "allow_missing_bars": False,
            "forward_fill_fx": True,
            "forward_fill_equities": False,
        },
        "backtest": {
            "initial_capital_base_ccy": 1000000,
            "base_currency": "SEK",
            "train_start": "2000-01-01",
            "train_end": "2000-01-03",
            "test_start": "2000-01-04",
            "test_end": "2000-01-08",
            "lookback_bars": 3,
            "entry_zscore": 1.0,
            "exit_zscore": 0.2,
            "max_holding_bars": 3,
            "commission_bps_per_leg": 5,
            "estimated_half_spread_bps_per_leg": 5,
            "slippage_bps_per_leg": 5,
            "capital_fraction_per_trade": 1.0,
            "invert_signals": False,
            "min_expected_edge_bps": 0,
            "min_deviation_bps": 0,
            "min_expected_reversion_bps": 0,
            "allow_short": True,
        },
    }


def test_tradingview_loader_handles_title_case_format(tmp_path: Path) -> None:
    path = tmp_path / "title.csv"
    write_csv(
        path,
        "Date,Open,High,Low,Close,Change\n"
        "2000-01-02 10:00,2,3,1,2.5,1%\n"
        "2000-01-01 10:00,1,2,0.5,1.5,1%\n",
    )

    df = load_tradingview_csv(path, timezone="Europe/Stockholm")

    assert list(df.columns) == ["open", "high", "low", "close"]
    assert list(df["close"]) == [1.5, 2.5]
    assert df.index.is_monotonic_increasing


def test_tradingview_loader_handles_lowercase_ohlcv_format(tmp_path: Path) -> None:
    path = tmp_path / "lower.csv"
    write_csv(
        path,
        "time,open,high,low,close,volume\n"
        "2000-01-01 10:00,1,2,0.5,1.5,100\n",
    )

    df = load_tradingview_csv(path)

    assert df.iloc[0]["volume"] == 100
    assert df.iloc[0]["open"] == 1
    assert str(df.index.tz) == "UTC"


def test_tradingview_loader_parses_unix_seconds_as_utc(tmp_path: Path) -> None:
    path = tmp_path / "unix.csv"
    write_csv(
        path,
        "time,open,high,low,close,Volume\n"
        "1233561600,1,2,0.5,1.5,100\n",
    )

    df = load_tradingview_csv(path)

    assert df.index[0] == pd.Timestamp("2009-02-02 08:00:00+00:00")
    assert str(df.index.tz) == "UTC"


def test_tradingview_loader_parses_iso_timezone_as_utc(tmp_path: Path) -> None:
    path = tmp_path / "iso.csv"
    write_csv(
        path,
        "time,open,high,low,close,Volume\n"
        "2009-02-02T09:00:00+01:00,1,2,0.5,1.5,100\n",
    )

    df = load_tradingview_csv(path)

    assert df.index[0] == pd.Timestamp("2009-02-02 08:00:00+00:00")
    assert str(df.index.tz) == "UTC"


def test_loader_removes_duplicate_timestamps_and_sorts(tmp_path: Path) -> None:
    path = tmp_path / "dupes.csv"
    write_csv(
        path,
        "time,open,high,low,close\n"
        "2000-01-02 10:00,2,3,1,2.5\n"
        "2000-01-01 10:00,1,2,0.5,1.5\n"
        "2000-01-01 10:00,1,2,0.5,1.6\n",
    )

    df = load_tradingview_csv(path)

    assert len(df) == 2
    assert df.iloc[0]["close"] == 1.6
    assert df.index.is_monotonic_increasing


def test_pair_alignment_and_fx_conversion_work() -> None:
    index = pd.date_range("2000-01-01", periods=2, freq="h", tz="Europe/Stockholm")
    long_df = pd.DataFrame({"open": [10, 11], "high": [10, 11], "low": [10, 11], "close": [10, 11]}, index=index)
    short_df = pd.DataFrame({"open": [120, 121], "high": [120, 121], "low": [120, 121], "close": [120, 121]}, index=index)
    fx_df = pd.DataFrame({"open": [11, 11], "high": [11, 11], "low": [11, 11], "close": [11, 11]}, index=index)
    for df in (long_df, short_df, fx_df):
        df.index.name = "timestamp"

    aligned = align_pair_bars(
        long_df,
        short_df,
        fx_df,
        sample_config(Path(".")),
        {"long_currency": "EUR", "short_currency": "SEK"},
    )

    assert aligned.iloc[0]["fx_rate"] == 11
    assert aligned.iloc[0]["fair_price_sek"] == 110
    assert aligned.iloc[0]["long_price_base"] == 110
    assert aligned.iloc[0]["short_price_base"] == 120
    assert aligned.iloc[0]["spread_abs"] == 10
    assert aligned.iloc[0]["spread_pct"] == pytest.approx(10 / 110)


def test_same_currency_pair_uses_fx_rate_one() -> None:
    index = pd.date_range("2000-01-01", periods=1, freq="h")
    long_df = pd.DataFrame({"open": [10], "high": [10], "low": [10], "close": [10]}, index=index)
    short_df = pd.DataFrame({"open": [11], "high": [11], "low": [11], "close": [11]}, index=index)
    for df in (long_df, short_df):
        df.index.name = "timestamp"

    aligned = align_pair_bars(
        long_df,
        short_df,
        None,
        sample_config(Path(".")),
        {"long_currency": "SEK", "short_currency": "SEK"},
    )

    assert aligned.iloc[0]["fx_rate"] == 1.0


def test_missing_fx_for_cross_currency_pair_raises(tmp_path: Path) -> None:
    write_csv(tmp_path / "long.csv", "time,open,high,low,close\n2000-01-01,1,1,1,1\n")
    write_csv(tmp_path / "short.csv", "time,open,high,low,close\n2000-01-01,1,1,1,1\n")
    config = sample_config(tmp_path)
    row = {
        "long_csv_file": "long.csv",
        "short_csv_file": "short.csv",
        "fx_csv_file": "",
        "long_currency": "EUR",
        "short_currency": "SEK",
    }

    with pytest.raises(ValueError, match="fx_csv_file"):
        load_pair_history(row, config)


def test_train_test_split_does_not_overlap() -> None:
    train = pd.DataFrame({"spread_pct": [0.1]}, index=pd.to_datetime(["2000-01-02"]))
    test = pd.DataFrame({"spread_pct": [0.2]}, index=pd.to_datetime(["2000-01-02"]))

    with pytest.raises(ValueError, match="must not overlap"):
        validate_train_test_split(train, test)


def test_model_fit_only_sees_training_rows_and_predict_uses_current_history() -> None:
    train = pd.DataFrame({"spread_pct": [0.0, 0.1, -0.1]})
    history = pd.DataFrame({"spread_pct": [0.0, 0.1, -0.1, 0.4]})
    model = WalkForwardSpreadModel(entry_zscore=1.0, exit_zscore=0.2, lookback_bars=2)

    model.fit(train)
    prediction = model.predict_bar(history)

    assert model.fit_rows == 3
    assert prediction["zscore"] is not None
    assert prediction["signal"] in set(Signal)


def test_model_lookback_changes_rolling_input_and_zscore() -> None:
    train = pd.DataFrame({"spread_pct": [0.0, 0.1, -0.1, 0.2]})
    history = pd.DataFrame({"spread_pct": [0.0] * 15 + [0.01, 0.02, 0.03, 0.04, 0.5]})
    short_model = WalkForwardSpreadModel(entry_zscore=2.0, exit_zscore=0.5, lookback_bars=5)
    long_model = WalkForwardSpreadModel(entry_zscore=2.0, exit_zscore=0.5, lookback_bars=20)

    short_model.fit(train)
    long_model.fit(train)
    short_prediction = short_model.predict_bar(history)
    long_prediction = long_model.predict_bar(history)

    assert short_prediction["rolling_mean"] != long_prediction["rolling_mean"]
    assert short_prediction["rolling_std"] != long_prediction["rolling_std"]
    assert short_prediction["zscore"] != long_prediction["zscore"]


def test_backtest_processes_test_bars_sequentially_without_future_history() -> None:
    index = pd.date_range("2000-01-01", periods=8, freq="D", tz="Europe/Stockholm")
    pair_df = pd.DataFrame(
        {
            "long_price_base": [10, 10, 10, 10, 10, 10, 10, 10],
            "short_price_base": [11, 10, 9, 13, 10, 8, 10, 13],
            "spread_abs": [1, 0, -1, 3, 0, -2, 0, 3],
            "spread_pct": [0.1, 0.0, -0.1, 0.3, 0.0, -0.2, 0.0, 0.3],
        },
        index=index,
    )
    config = sample_config(Path("."))

    result = WalkForwardBacktest().run_pair("pair", pair_df, config)

    assert len(result.signals) == 5
    assert list(result.signals["history_rows_seen"]) == [4, 5, 6, 7, 8]


def test_walk_forward_windows_do_not_overlap() -> None:
    index = pd.date_range("2009-02-02", "2015-12-31", freq="D", tz="UTC")
    pair_df = pd.DataFrame({"spread_pct": 0.1}, index=index)

    windows = generate_walk_forward_windows(pair_df, train_years=4, test_years=1)

    assert windows[0]["train_start"] == pd.Timestamp("2009-02-02 00:00:00+00:00")
    assert windows[0]["train_end"] < windows[0]["test_start"]
    assert windows[0]["test_start"].year == 2013


def test_simulated_broker_uses_conservative_prices_and_costs() -> None:
    broker = SimulatedBroker("pair", 1000, 5, 5, 5, max_holding_bars=10)
    entry = pd.Series({"long_price_base": 100.0, "short_price_base": 110.0})
    exit_row = pd.Series({"long_price_base": 105.0, "short_price_base": 100.0})

    broker.on_bar(pd.Timestamp("2000-01-01"), entry, Signal.ENTER_LONG_SPREAD)
    broker.on_bar(pd.Timestamp("2000-01-02"), exit_row, Signal.EXIT)

    trade = broker.trades[0]
    assert trade["entry_long_price"] > 100.0
    assert trade["entry_short_price"] < 110.0
    assert trade["net_pnl"] < trade["gross_pnl"]


def test_simulated_broker_sizes_positions_from_capital_in_sek() -> None:
    broker = SimulatedBroker(
        "pair",
        initial_capital=1_000_000,
        commission_bps_per_leg=0,
        estimated_half_spread_bps_per_leg=0,
        slippage_bps_per_leg=0,
        max_holding_bars=10,
        capital_fraction_per_trade=0.5,
    )
    entry = pd.Series({"long_price_base": 100.0, "short_price_base": 200.0})
    exit_row = pd.Series({"long_price_base": 110.0, "short_price_base": 190.0})

    broker.on_bar(pd.Timestamp("2000-01-01"), entry, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-02"), exit_row, Signal.EXIT)

    trade = broker.trades[0]
    assert trade["capital_allocated_sek"] == 500_000
    assert trade["long_quantity"] == 2500
    assert trade["short_quantity"] == 1250
    assert trade["long_leg_gross_pnl"] == 25_000
    assert trade["short_leg_gross_pnl"] == 12_500
    assert trade["gross_pnl"] == 37_500
    assert trade["net_pnl"] == 37_500


def test_simulated_broker_outputs_leg_level_trade_details() -> None:
    broker = SimulatedBroker("pair", 1000, 5, 5, 5, max_holding_bars=10)
    entry = pd.Series({"long_price_base": 100.0, "short_price_base": 110.0})
    exit_row = pd.Series({"long_price_base": 105.0, "short_price_base": 100.0})

    broker.on_bar(pd.Timestamp("2000-01-01"), entry, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-02"), exit_row, Signal.EXIT)

    trade = broker.trades[0]
    for column in [
        "entry_long_close_sek",
        "entry_short_close_sek",
        "exit_long_close_sek",
        "exit_short_close_sek",
        "entry_long_notional_sek",
        "entry_short_notional_sek",
        "exit_long_notional_sek",
        "exit_short_notional_sek",
        "entry_commission_sek",
        "exit_commission_sek",
    ]:
        assert column in trade


def test_simulated_broker_can_invert_signals_for_research() -> None:
    broker = SimulatedBroker(
        "pair",
        initial_capital=1000,
        commission_bps_per_leg=0,
        estimated_half_spread_bps_per_leg=0,
        slippage_bps_per_leg=0,
        max_holding_bars=10,
        invert_signals=True,
    )
    entry = pd.Series({"long_price_base": 100.0, "short_price_base": 100.0})
    exit_row = pd.Series({"long_price_base": 90.0, "short_price_base": 110.0})

    broker.on_bar(pd.Timestamp("2000-01-01"), entry, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-02"), exit_row, Signal.EXIT)

    trade = broker.trades[0]
    assert trade["direction"] == "LONG_SWEDEN_SHORT_FINLAND"
    assert trade["net_pnl"] == 100


def test_entry_edge_bps_and_edge_filter_are_applied() -> None:
    broker = SimulatedBroker(
        "pair",
        initial_capital=1000,
        commission_bps_per_leg=0,
        estimated_half_spread_bps_per_leg=0,
        slippage_bps_per_leg=0,
        max_holding_bars=10,
        min_expected_edge_bps=20,
    )
    low_edge = pd.Series(
        {"long_price_base": 100.0, "short_price_base": 100.1, "spread_pct": 0.001}
    )
    high_edge = pd.Series(
        {"long_price_base": 100.0, "short_price_base": 101.0, "spread_pct": 0.01}
    )

    broker.on_bar(pd.Timestamp("2000-01-01"), low_edge, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND, zscore=2.0)
    assert broker.position is None
    broker.on_bar(pd.Timestamp("2000-01-02"), high_edge, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND, zscore=2.5)
    broker.on_bar(pd.Timestamp("2000-01-03"), high_edge, Signal.EXIT)

    trade = broker.trades[0]
    assert trade["entry_edge_bps"] == 100
    assert trade["entry_zscore"] == 2.5


def test_min_edge_filter_does_not_block_exits() -> None:
    broker = SimulatedBroker("pair", 1000, 0, 0, 0, 10, min_expected_edge_bps=50)
    entry = pd.Series({"long_price_base": 100.0, "short_price_base": 102.0, "spread_pct": 0.02})
    exit_row = pd.Series({"long_price_base": 100.0, "short_price_base": 100.1, "spread_pct": 0.001})

    broker.on_bar(pd.Timestamp("2000-01-01"), entry, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-02"), exit_row, Signal.EXIT)

    assert broker.position is None
    assert len(broker.trades) == 1


def test_allowed_direction_filters_trade_entries() -> None:
    broker = SimulatedBroker(
        "pair",
        1000,
        0,
        0,
        0,
        10,
        allowed_direction="SHORT_SWEDEN_LONG_FINLAND",
    )
    row = pd.Series({"long_price_base": 100.0, "short_price_base": 103.0, "spread_pct": 0.03})

    broker.on_bar(pd.Timestamp("2000-01-01 07:00", tz="UTC"), row, Signal.ENTER_LONG_SWEDEN_SHORT_FINLAND)
    assert broker.position is None
    broker.on_bar(pd.Timestamp("2000-01-01 08:00", tz="UTC"), row, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-01 09:00", tz="UTC"), row, Signal.EXIT)

    assert len(broker.trades) == 1
    assert broker.trades[0]["direction"] == "SHORT_SWEDEN_LONG_FINLAND"


def test_entry_hours_utc_filters_trade_entries() -> None:
    broker = SimulatedBroker("pair", 1000, 0, 0, 0, 10, entry_hours_utc=[7])
    row = pd.Series({"long_price_base": 100.0, "short_price_base": 103.0, "spread_pct": 0.03})

    broker.on_bar(pd.Timestamp("2000-01-01 06:00", tz="UTC"), row, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    assert broker.position is None
    broker.on_bar(pd.Timestamp("2000-01-01 07:00", tz="UTC"), row, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-01 08:00", tz="UTC"), row, Signal.EXIT)

    assert len(broker.trades) == 1
    assert pd.Timestamp(broker.trades[0]["entry_timestamp"]).hour == 7


def test_exclude_entry_hours_utc_filters_trade_entries() -> None:
    broker = SimulatedBroker("pair", 1000, 0, 0, 0, 10, exclude_entry_hours_utc=[7])
    row = pd.Series({"long_price_base": 100.0, "short_price_base": 103.0, "spread_pct": 0.03})

    broker.on_bar(pd.Timestamp("2000-01-01 07:00", tz="UTC"), row, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    assert broker.position is None
    broker.on_bar(pd.Timestamp("2000-01-01 08:00", tz="UTC"), row, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-01 09:00", tz="UTC"), row, Signal.EXIT)

    assert len(broker.trades) == 1
    assert pd.Timestamp(broker.trades[0]["entry_timestamp"]).hour == 8


def test_max_entry_edge_bps_excludes_extreme_edge_trades() -> None:
    broker = SimulatedBroker("pair", 1000, 0, 0, 0, 10, max_entry_edge_bps=200)
    extreme = pd.Series({"long_price_base": 100.0, "short_price_base": 105.0, "spread_pct": 0.05})
    capped = pd.Series({"long_price_base": 100.0, "short_price_base": 101.5, "spread_pct": 0.015})

    broker.on_bar(pd.Timestamp("2000-01-01 07:00", tz="UTC"), extreme, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    assert broker.position is None
    broker.on_bar(pd.Timestamp("2000-01-01 08:00", tz="UTC"), capped, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-01 09:00", tz="UTC"), capped, Signal.EXIT)

    assert len(broker.trades) == 1
    assert broker.trades[0]["entry_edge_bps"] == 150


def test_entry_filter_defaults_preserve_existing_behavior() -> None:
    broker = SimulatedBroker("pair", 1000, 0, 0, 0, 10)
    row = pd.Series({"long_price_base": 100.0, "short_price_base": 103.0, "spread_pct": 0.03})

    broker.on_bar(pd.Timestamp("2000-01-01 07:00", tz="UTC"), row, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    broker.on_bar(pd.Timestamp("2000-01-01 08:00", tz="UTC"), row, Signal.EXIT)

    assert len(broker.trades) == 1


def test_summary_contains_edge_and_cost_diagnostics() -> None:
    index = pd.date_range("2000-01-01", periods=8, freq="D", tz="UTC")
    pair_df = pd.DataFrame(
        {
            "long_price_base": [100] * 8,
            "short_price_base": [100, 101, 99, 103, 100, 98, 100, 103],
            "spread_abs": [0, 1, -1, 3, 0, -2, 0, 3],
            "spread_pct": [0, 0.01, -0.01, 0.03, 0, -0.02, 0, 0.03],
        },
        index=index,
    )
    result = WalkForwardBacktest().run_pair("pair", pair_df, sample_config(Path(".")))

    for key in [
        "average_entry_edge_bps",
        "median_entry_edge_bps",
        "average_cost_per_trade",
        "average_gross_pnl_per_trade",
        "average_edge_to_cost_ratio",
    ]:
        assert key in result.summary


def test_trade_bucket_report_groups_and_handles_empty() -> None:
    empty = build_trade_bucket_report(pd.DataFrame())
    assert empty.empty

    trades = pd.DataFrame(
        {
            "entry_zscore": [2.1, 3.2],
            "entry_edge_bps": [15, 55],
            "holding_bars": [2, 30],
            "entry_timestamp": ["2000-01-01 09:00:00+00:00", "2000-01-01 10:00:00+00:00"],
            "gross_pnl": [100, -50],
            "cost_total": [10, 10],
            "net_pnl": [90, -60],
        }
    )
    report = build_trade_bucket_report(trades)
    assert {"entry_zscore", "entry_edge_bps", "holding_bars", "entry_hour_utc"} <= set(
        report["bucket_type"]
    )


class Args:
    data_dir = "data/historical/tradingview"
    timeframe = "60m"
    lookback_bars = None
    entry_zscore = None
    exit_zscore = None
    max_holding_bars = None
    initial_capital_base_ccy = None
    capital_fraction_per_trade = None
    cost_preset = "high"
    commission_bps_per_leg = None
    half_spread_bps_per_leg = None
    slippage_bps_per_leg = None
    min_expected_edge_bps = None
    min_deviation_bps = None
    min_expected_reversion_bps = None
    allowed_direction = "any"
    entry_hours_utc = None
    exclude_entry_hours_utc = None
    max_entry_edge_bps = None
    invert_signals = False


def test_cost_presets_and_explicit_overrides() -> None:
    assert COST_PRESETS["zero"] == (0, 0, 0)
    assert COST_PRESETS["low"] == (1, 1, 1)
    assert COST_PRESETS["medium"] == (3, 3, 3)
    assert COST_PRESETS["high"] == (5, 5, 5)
    args = Args()
    args.cost_preset = "low"
    assert cost_values_from_args(args) == (1, 1, 1)
    args.commission_bps_per_leg = 7
    assert cost_values_from_args(args) == (7, 1, 1)


def test_pair_specific_parameters_override_defaults() -> None:
    config = sample_config(Path("."))
    config["pair_parameters"] = {"tieto_fi_se": {"entry_zscore": 3.0}}
    index = pd.date_range("2000-01-01", periods=8, freq="D", tz="UTC")
    pair_df = pd.DataFrame(
        {
            "long_price_base": [100] * 8,
            "short_price_base": [100, 101, 99, 103, 100, 98, 100, 103],
            "spread_abs": [0, 1, -1, 3, 0, -2, 0, 3],
            "spread_pct": [0, 0.01, -0.01, 0.03, 0, -0.02, 0, 0.03],
        },
        index=index,
    )
    result = WalkForwardBacktest().run_pair("tieto_fi_se", pair_df, config)
    assert result.summary["pair_id"] == "tieto_fi_se"
    assert result.summary["entry_zscore"] == 3.0
    assert result.effective_parameters["entry_zscore_source"] == "pair_config"


def test_cli_overrides_pair_specific_backtest_parameters() -> None:
    config = sample_config(Path("."))
    config["pair_parameters"] = {
        "tieto_fi_se": {
            "lookback_bars": 20,
            "entry_zscore": 3.0,
            "capital_fraction_per_trade": 0.5,
        }
    }
    args = Args()
    args.lookback_bars = 5
    args.entry_zscore = 2.0
    args.capital_fraction_per_trade = 0.25
    args.cost_preset = "low"
    args.commission_bps_per_leg = 9

    resolved, sources = resolve_effective_backtest_config(
        apply_cli_overrides(config, args),
        "tieto_fi_se",
    )

    assert resolved["lookback_bars"] == 5
    assert sources["lookback_bars"] == "cli"
    assert resolved["entry_zscore"] == 2.0
    assert sources["entry_zscore"] == "cli"
    assert resolved["capital_fraction_per_trade"] == 0.25
    assert sources["capital_fraction_per_trade"] == "cli"
    assert resolved["commission_bps_per_leg"] == 9
    assert sources["commission_bps_per_leg"] == "cli"
    assert resolved["estimated_half_spread_bps_per_leg"] == 1
    assert sources["estimated_half_spread_bps_per_leg"] == "cli"


def test_effective_config_uses_default_when_no_pair_or_cli_override() -> None:
    config = sample_config(Path("."))

    resolved, sources = resolve_effective_backtest_config(config, "unknown_pair")

    assert resolved["lookback_bars"] == 3
    assert sources["lookback_bars"] == "default"


def test_cli_entry_filters_are_explicit_overrides_only() -> None:
    args = Args()
    config = apply_cli_overrides(sample_config(Path(".")), args)

    assert "allowed_direction" not in config["cli_backtest_overrides"]
    assert "entry_hours_utc" not in config["cli_backtest_overrides"]
    assert "exclude_entry_hours_utc" not in config["cli_backtest_overrides"]
    assert "max_entry_edge_bps" not in config["cli_backtest_overrides"]

    args.allowed_direction = "SHORT_SWEDEN_LONG_FINLAND"
    args.entry_hours_utc = "7,8,15"
    args.exclude_entry_hours_utc = "9"
    args.max_entry_edge_bps = 200
    config = apply_cli_overrides(sample_config(Path(".")), args)

    assert config["cli_backtest_overrides"]["allowed_direction"] == "SHORT_SWEDEN_LONG_FINLAND"
    assert config["cli_backtest_overrides"]["entry_hours_utc"] == [7, 8, 15]
    assert config["cli_backtest_overrides"]["exclude_entry_hours_utc"] == [9]
    assert config["cli_backtest_overrides"]["max_entry_edge_bps"] == 200


def test_parse_hour_list_validates_hours() -> None:
    assert parse_hour_list("7,8,15") == [7, 8, 15]
    with pytest.raises(ValueError, match="between 0 and 23"):
        parse_hour_list("24")


def test_timeframe_60m_resolves_existing_mapping_files() -> None:
    row = {
        "long_csv_file": "OMXHEX_DLY_TIETO_60.csv",
        "long_csv_file_30m": "OMXHEX_DLY_TIETO_30m.csv",
        "short_csv_file": "OMXSTO_DLY_TIETOS_60.csv",
        "short_csv_file_30m": "OMXSTO_DLY_TIETOS_30m.csv",
        "fx_csv_file": "FX_EURSEK_1H_2008_2026.csv",
        "fx_csv_file_30m": "FX_EURSEK_30m.csv",
    }

    assert resolve_timeframe_csv_file(row, "long_csv_file", "60m") == "OMXHEX_DLY_TIETO_60.csv"
    assert resolve_timeframe_csv_file(row, "short_csv_file", "60m") == "OMXSTO_DLY_TIETOS_60.csv"
    assert resolve_timeframe_csv_file(row, "fx_csv_file", "60m") == "FX_EURSEK_1H_2008_2026.csv"


def test_timeframe_30m_resolves_new_tieto_mapping_files() -> None:
    row = {
        "long_csv_file": "OMXHEX_DLY_TIETO_60.csv",
        "long_csv_file_30m": "OMXHEX_DLY_TIETO_30m.csv",
        "short_csv_file": "OMXSTO_DLY_TIETOS_60.csv",
        "short_csv_file_30m": "OMXSTO_DLY_TIETOS_30m.csv",
        "fx_csv_file": "FX_EURSEK_1H_2008_2026.csv",
        "fx_csv_file_30m": "FX_EURSEK_30m.csv",
    }

    assert resolve_timeframe_csv_file(row, "long_csv_file", "30m") == "OMXHEX_DLY_TIETO_30m.csv"
    assert resolve_timeframe_csv_file(row, "short_csv_file", "30m") == "OMXSTO_DLY_TIETOS_30m.csv"
    assert resolve_timeframe_csv_file(row, "fx_csv_file", "30m") == "FX_EURSEK_30m.csv"


def test_cli_timeframe_sets_30m_base_path_and_preserves_lookback() -> None:
    args = Args()
    args.timeframe = "30m"
    args.lookback_bars = 200

    config = apply_cli_overrides(sample_config(Path(".")), args)

    assert config["historical_data"]["timeframe"] == "30m"
    assert config["historical_data"]["base_path"].endswith("data\\raw\\tradingview\\30m")
    assert config["cli_backtest_overrides"]["lookback_bars"] == 200


def test_timeframe_is_written_to_summary_and_run_config(tmp_path: Path) -> None:
    index = pd.date_range("2000-01-01", periods=8, freq="D", tz="UTC")
    pair_df = pd.DataFrame(
        {
            "long_price_base": [100] * 8,
            "short_price_base": [100, 101, 99, 103, 100, 98, 100, 103],
            "spread_abs": [0, 1, -1, 3, 0, -2, 0, 3],
            "spread_pct": [0, 0.01, -0.01, 0.03, 0, -0.02, 0, 0.03],
        },
        index=index,
    )
    config = sample_config(Path("."))
    config["historical_data"]["timeframe"] = "30m"
    config["cli_backtest_overrides"] = {"lookback_bars": 7}

    result = WalkForwardBacktest().run_pair("pair", pair_df, config)
    export_backtest_run([result], tmp_path, config)

    assert result.summary["timeframe"] == "30m"
    assert result.summary["lookback_bars"] == 7
    summary = pd.read_csv(tmp_path / "summary.csv")
    assert summary.iloc[0]["timeframe"] == "30m"
    run_config = (tmp_path / "run_config.yaml").read_text(encoding="utf-8")
    assert "effective_timeframe: 30m" in run_config


def test_min_deviation_and_reversion_filters_block_entries() -> None:
    broker = SimulatedBroker(
        "pair",
        initial_capital=1000,
        commission_bps_per_leg=0,
        estimated_half_spread_bps_per_leg=0,
        slippage_bps_per_leg=0,
        max_holding_bars=10,
        min_deviation_bps=80,
        min_expected_reversion_bps=90,
    )
    low_edge = pd.Series({"long_price_base": 100.0, "short_price_base": 100.5, "spread_pct": 0.005})
    high_edge = pd.Series({"long_price_base": 100.0, "short_price_base": 101.0, "spread_pct": 0.01})

    broker.on_bar(pd.Timestamp("2000-01-01"), low_edge, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)
    assert broker.position is None
    broker.on_bar(pd.Timestamp("2000-01-02"), high_edge, Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND)

    assert broker.position is not None


def test_optimizer_selects_parameters_using_training_period_only() -> None:
    config = sample_config(Path("."))
    index = pd.date_range("2000-01-01", periods=80, freq="D", tz="UTC")
    pair_df = pd.DataFrame(
        {
            "long_price_base": [100] * 80,
            "short_price_base": [100 + ((i % 6) - 3) for i in range(80)],
            "spread_abs": [((i % 6) - 3) for i in range(80)],
            "spread_pct": [((i % 6) - 3) / 100 for i in range(80)],
        },
        index=index,
    )

    params, stats = choose_parameters_on_training(
        "tieto_fi_se",
        pair_df,
        config,
        index[0],
        index[59],
        grid=[{
            "lookback_bars": 3,
            "entry_zscore": 0.1,
            "exit_zscore": 0.2,
            "min_expected_edge_bps": 0,
        }],
        min_training_trades=0,
        allow_non_positive_training_pnl=True,
    )

    assert "lookback_bars" in params
    assert "training_score" in stats


def test_tieto_validation_grid_is_narrow_and_centered_on_candidate() -> None:
    grid = validation_parameter_grid()

    assert len(grid) == 54
    assert {params["lookback_bars"] for params in grid} == {100, 200}
    assert {params["entry_zscore"] for params in grid} == {2.0, 2.1, 2.2}
    assert {params["exit_zscore"] for params in grid} == {0.25, 0.5, 0.75}
    assert {params["min_expected_edge_bps"] for params in grid} == {60, 65, 70}
    assert 0 not in {params["min_expected_edge_bps"] for params in grid}
    assert {
        "lookback_bars": 200,
        "entry_zscore": 2.0,
        "exit_zscore": 0.5,
        "min_expected_edge_bps": 65,
    } in grid


def test_optimizer_cli_applies_cost_preset_and_capital_fraction() -> None:
    class OptimizerArgs:
        cost_preset = "high"
        capital_fraction_per_trade = 0.25

    config = apply_optimizer_cli_config(sample_config(Path(".")), OptimizerArgs())

    assert config["backtest"]["commission_bps_per_leg"] == 5
    assert config["backtest"]["estimated_half_spread_bps_per_leg"] == 5
    assert config["backtest"]["slippage_bps_per_leg"] == 5
    assert config["backtest"]["capital_fraction_per_trade"] == 0.25


def test_min_training_trades_prevents_selecting_thin_candidates() -> None:
    config = sample_config(Path("."))
    index = pd.date_range("2000-01-01", periods=80, freq="D", tz="UTC")
    pair_df = pd.DataFrame(
        {
            "long_price_base": [100] * 80,
            "short_price_base": [100 + ((i % 6) - 3) for i in range(80)],
            "spread_abs": [((i % 6) - 3) for i in range(80)],
            "spread_pct": [((i % 6) - 3) / 100 for i in range(80)],
        },
        index=index,
    )

    params, stats = choose_parameters_on_training(
        "tieto_fi_se",
        pair_df,
        config,
        index[0],
        index[59],
        grid=[{
            "lookback_bars": 100,
            "entry_zscore": 2.0,
            "exit_zscore": 0.5,
            "min_expected_edge_bps": 60,
        }],
        min_training_trades=10_000,
    )

    assert params is None
    assert stats["fallback_used"] is True
    assert stats["training_number_of_trades"] == 0
    assert stats["candidates_evaluated"] == 1
    assert stats["candidates_passing_constraints"] == 0


def test_optimizer_does_not_silently_select_default_params_outside_grid() -> None:
    config = sample_config(Path("."))
    config["backtest"]["min_expected_edge_bps"] = 0
    index = pd.date_range("2000-01-01", periods=80, freq="D", tz="UTC")
    pair_df = pd.DataFrame(
        {
            "long_price_base": [100] * 80,
            "short_price_base": [100] * 80,
            "spread_abs": [0] * 80,
            "spread_pct": [0] * 80,
        },
        index=index,
    )

    params, stats = choose_parameters_on_training(
        "tieto_fi_se",
        pair_df,
        config,
        index[0],
        index[59],
        grid=[{
            "lookback_bars": 100,
            "entry_zscore": 2.0,
            "exit_zscore": 0.5,
            "min_expected_edge_bps": 60,
        }],
        min_training_trades=20,
    )

    assert params is None
    assert stats["fallback_used"] is True


def test_skip_window_fallback_row_is_explicit_and_flat() -> None:
    window = {
        "train_start": pd.Timestamp("2000-01-01", tz="UTC"),
        "train_end": pd.Timestamp("2000-01-10", tz="UTC"),
        "test_start": pd.Timestamp("2000-01-11", tz="UTC"),
        "test_end": pd.Timestamp("2000-01-20", tz="UTC"),
    }
    row = skipped_window_selection_row(
        window,
        {
            "training_score": 0.0,
            "training_net_pnl": 0.0,
            "training_max_drawdown": 0.0,
            "training_number_of_trades": 0,
            "fallback_reason": "no_candidate_passed_constraints",
            "candidates_evaluated": 54,
            "candidates_passing_constraints": 0,
        },
        "skip_window",
    )

    assert row["fallback_used"] is True
    assert row["fallback_policy"] == "skip_window"
    assert row["fallback_reason"] == "no_candidate_passed_constraints"
    assert row["test_net_pnl"] == 0.0
    assert row["test_number_of_trades"] == 0


def test_use_fixed_baseline_fallback_params_are_current_candidate() -> None:
    assert fixed_baseline_params() == {
        "lookback_bars": 200,
        "entry_zscore": 2.0,
        "exit_zscore": 0.5,
        "min_expected_edge_bps": 65,
    }


def test_tieto_30m_robustness_grid_is_small_and_exact() -> None:
    grid = robustness_grid()

    assert len(grid) == 27
    assert {params["lookback_bars"] for params in grid} == {300, 400, 600}
    assert {params["entry_zscore"] for params in grid} == {2.0}
    assert {params["exit_zscore"] for params in grid} == {0.5, 0.75, 1.0}
    assert {params["min_expected_edge_bps"] for params in grid} == {60, 65, 70}


def test_tieto_30m_trade_concentration_uses_largest_net_trades() -> None:
    class Result:
        trades = pd.DataFrame({"net_pnl": [100.0, 50.0, 25.0, -25.0]})

    concentration = trade_concentration([Result()])

    assert concentration["top_1_trade_share"] == pytest.approx(100 / 150)
    assert concentration["top_3_trade_share"] == pytest.approx(175 / 150)


def test_backtest_modules_do_not_import_ibkr_provider() -> None:
    backtest_dir = Path("src/backtest")

    for path in backtest_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "ibkr" not in text.lower()
        assert "placeOrder" not in text


def test_csv_coverage_detects_first_last_and_format(tmp_path: Path) -> None:
    path = tmp_path / "coverage.csv"
    write_csv(
        path,
        "time,open,high,low,close\n"
        "1233561600,1,1,1,1\n"
        "1233565200,2,2,2,2\n",
    )

    coverage = csv_coverage(path)

    assert coverage["first_timestamp_utc"] == pd.Timestamp("2009-02-02 08:00:00+00:00")
    assert coverage["last_timestamp_utc"] == pd.Timestamp("2009-02-02 09:00:00+00:00")
    assert coverage["detected_time_format"] == "unix_seconds"


def test_real_pair_coverage_uses_each_pair_start_date() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = sample_config(project_root / "data" / "historical" / "tradingview")
    pairs = pd.read_csv(project_root / "data" / "mappings" / "backtest_pairs.csv")

    coverage_by_pair = {
        row["pair_id"]: pair_coverage(row, config)
        for _, row in pairs.iterrows()
    }

    assert coverage_by_pair["tieto_fi_se"]["effective_common_start"].date().isoformat() == "2009-02-02"
    assert coverage_by_pair["stora_enso_fi_se"]["effective_common_start"].date().isoformat() == "2009-02-02"
    assert coverage_by_pair["nokia_fi_se"]["effective_common_start"].date().isoformat() == "2015-08-10"
