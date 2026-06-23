"""Offline walk-forward backtest engine."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.backtest.simulated_broker import (
    SimulatedBroker,
    edge_to_cost_ratio,
    entry_edge_bps,
    estimated_roundtrip_cost_bps,
)
from src.backtest.walk_forward_model import Signal, WalkForwardSpreadModel


@dataclass
class BacktestResult:
    pair_id: str
    window_id: str
    effective_parameters: dict[str, Any]
    summary: dict[str, Any]
    signals: pd.DataFrame
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    spread: pd.DataFrame


class WalkForwardBacktest:
    """Run out-of-sample bar-by-bar pair backtests."""

    def run_pair(self, pair_id: str, pair_df: pd.DataFrame, config: dict) -> BacktestResult:
        backtest_config, _ = resolve_effective_backtest_config(config, pair_id)
        return self.run_pair_window(
            pair_id,
            pair_df,
            config,
            backtest_config["train_start"],
            backtest_config["train_end"],
            backtest_config["test_start"],
            backtest_config["test_end"],
        )

    def run_pair_window(
        self,
        pair_id: str,
        pair_df: pd.DataFrame,
        config: dict,
        train_start: str | pd.Timestamp,
        train_end: str | pd.Timestamp,
        test_start: str | pd.Timestamp,
        test_end: str | pd.Timestamp,
    ) -> BacktestResult:
        backtest_config, parameter_sources = resolve_effective_backtest_config(config, pair_id)
        train_df = pair_df.loc[_period_mask(pair_df, train_start, train_end)]
        test_df = pair_df.loc[_period_mask(pair_df, test_start, test_end)]
        validate_train_test_split(train_df, test_df)

        model = WalkForwardSpreadModel(
            entry_zscore=float(backtest_config["entry_zscore"]),
            exit_zscore=float(backtest_config["exit_zscore"]),
            lookback_bars=int(backtest_config["lookback_bars"]),
        )
        model.fit(train_df)

        broker = SimulatedBroker(
            pair_id=pair_id,
            initial_capital=float(backtest_config["initial_capital_base_ccy"]),
            commission_bps_per_leg=float(backtest_config["commission_bps_per_leg"]),
            estimated_half_spread_bps_per_leg=float(
                backtest_config["estimated_half_spread_bps_per_leg"]
            ),
            slippage_bps_per_leg=float(backtest_config["slippage_bps_per_leg"]),
            max_holding_bars=int(backtest_config["max_holding_bars"]),
            capital_fraction_per_trade=float(
                backtest_config.get("capital_fraction_per_trade", 1.0)
            ),
            invert_signals=bool(backtest_config.get("invert_signals", False)),
            min_expected_edge_bps=float(backtest_config.get("min_expected_edge_bps", 0)),
            min_deviation_bps=float(backtest_config.get("min_deviation_bps", 0)),
            min_expected_reversion_bps=float(
                backtest_config.get("min_expected_reversion_bps", 0)
            ),
            allowed_direction=backtest_config.get("allowed_direction", "any"),
            entry_hours_utc=backtest_config.get("entry_hours_utc"),
            exclude_entry_hours_utc=backtest_config.get("exclude_entry_hours_utc"),
            max_entry_edge_bps=backtest_config.get("max_entry_edge_bps"),
        )
        roundtrip_cost_bps = estimated_roundtrip_cost_bps(
            backtest_config["commission_bps_per_leg"],
            backtest_config["estimated_half_spread_bps_per_leg"],
            backtest_config["slippage_bps_per_leg"],
        )

        signal_rows: list[dict[str, Any]] = []
        combined_history = pd.concat([train_df, test_df])
        rolling_stats = _rolling_signal_stats(
            combined_history["spread_pct"],
            int(backtest_config["lookback_bars"]),
        )
        train_rows = len(train_df)
        for offset, (timestamp, row) in enumerate(test_df.iterrows()):
            history_rows_seen = train_rows + offset + 1
            stats_row = rolling_stats.iloc[history_rows_seen - 1]
            zscore = None if pd.isna(stats_row["zscore"]) else float(stats_row["zscore"])
            signal = Signal.HOLD if zscore is None else model.generate_signal_from_zscore(zscore)
            edge_bps = entry_edge_bps(row)
            broker.on_bar(timestamp, row, signal, zscore=zscore)
            signal_rows.append(
                {
                    "timestamp": timestamp,
                    "signal": signal.value if isinstance(signal, Signal) else str(signal),
                    "zscore": zscore,
                    "rolling_mean": stats_row["rolling_mean"],
                    "rolling_std": stats_row["rolling_std"],
                    "entry_spread_pct": float(row["spread_pct"]),
                    "entry_edge_bps": edge_bps,
                    "entry_zscore": zscore,
                    "estimated_roundtrip_cost_bps": roundtrip_cost_bps,
                    "edge_to_cost_ratio": edge_to_cost_ratio(edge_bps, roundtrip_cost_bps),
                    "history_rows_seen": history_rows_seen,
                }
            )

        if not test_df.empty:
            broker.close_open_position(test_df.index[-1], test_df.iloc[-1])

        signals = pd.DataFrame(signal_rows)
        trades = pd.DataFrame(broker.trades)
        equity_curve = pd.DataFrame(broker.equity_curve)
        summary = _calculate_summary(
            initial_capital=float(backtest_config["initial_capital_base_ccy"]),
            trades=trades,
            equity_curve=equity_curve,
            test_rows=len(test_df),
            signal_rows=signals,
        )
        summary["pair_id"] = pair_id
        summary.update(_summary_parameter_fields(backtest_config))
        summary["timeframe"] = config.get("historical_data", {}).get("timeframe", "60m")
        window_id = _window_id(train_df, test_df)
        summary["window_id"] = window_id
        summary["train_start"] = train_df.index.min()
        summary["train_end"] = train_df.index.max()
        summary["test_start"] = test_df.index.min()
        summary["test_end"] = test_df.index.max()
        summary["train_rows"] = len(train_df)
        summary["test_rows"] = len(test_df)

        return BacktestResult(
            pair_id=pair_id,
            window_id=window_id,
            effective_parameters=_effective_parameter_report(
                pair_id,
                backtest_config,
                parameter_sources,
            ),
            summary=summary,
            signals=signals,
            trades=trades,
            equity_curve=equity_curve,
            spread=pair_df[["spread_abs", "spread_pct"]].copy(),
        )

    def run_pair_walk_forward(
        self,
        pair_id: str,
        pair_df: pd.DataFrame,
        config: dict,
        train_years: int = 4,
        test_years: int = 1,
    ) -> list[BacktestResult]:
        results: list[BacktestResult] = []
        for window in generate_walk_forward_windows(pair_df, train_years, test_years):
            try:
                results.append(
                    self.run_pair_window(
                        pair_id,
                        pair_df,
                        config,
                        window["train_start"],
                        window["train_end"],
                        window["test_start"],
                        window["test_end"],
                    )
                )
            except ValueError:
                continue
        return results

    def run_all_pairs(
        self,
        pair_data: dict[str, pd.DataFrame],
        config: dict,
        train_years: int = 4,
        test_years: int = 1,
    ) -> list[BacktestResult]:
        results: list[BacktestResult] = []
        for pair_id, pair_df in pair_data.items():
            results.extend(
                self.run_pair_walk_forward(pair_id, pair_df, config, train_years, test_years)
            )
        return results


def generate_walk_forward_windows(
    pair_df: pd.DataFrame,
    train_years: int = 4,
    test_years: int = 1,
) -> list[dict[str, pd.Timestamp]]:
    if pair_df.empty:
        return []
    first = pair_df.index.min()
    last = pair_df.index.max()
    timezone = getattr(pair_df.index, "tz", None)
    first_year = first.year
    windows: list[dict[str, pd.Timestamp]] = []

    train_start = first
    while True:
        train_end = _year_end(first_year + train_years - 1, timezone)
        test_start = _year_start(first_year + train_years, timezone)
        test_end = _year_end(first_year + train_years + test_years - 1, timezone)
        if test_start > last:
            break
        if train_end > first and test_end <= last:
            windows.append(
                {
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                }
            )
        first_year += 1
        train_start = max(first, _year_start(first_year, timezone))
    return windows


def validate_train_test_split(train_df: pd.DataFrame, test_df: pd.DataFrame) -> None:
    if train_df.empty:
        raise ValueError("Training period contains no rows.")
    if test_df.empty:
        raise ValueError("Test period contains no rows.")
    if train_df.index.max() >= test_df.index.min():
        raise ValueError("Training and test periods must not overlap.")


def export_backtest_result(result: BacktestResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{result.pair_id}_{result.window_id}"
    result.signals.to_csv(output_dir / f"{prefix}_signals.csv", index=False)
    result.trades.to_csv(output_dir / f"{prefix}_trades.csv", index=False)
    result.equity_curve.to_csv(output_dir / f"{prefix}_equity_curve.csv", index=False)
    result.spread.to_csv(output_dir / f"{result.pair_id}_spread.csv")


def export_backtest_run(results: list[BacktestResult], output_dir: Path, config: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not results:
        pd.DataFrame().to_csv(output_dir / "summary.csv", index=False)
        pd.DataFrame().to_csv(output_dir / "windows.csv", index=False)
        pd.DataFrame().to_csv(output_dir / "all_trades.csv", index=False)
        pd.DataFrame().to_csv(output_dir / "all_equity_curves.csv", index=False)
        run_config = dict(config)
        run_config["effective_timeframe"] = config.get("historical_data", {}).get(
            "timeframe",
            "60m",
        )
        with (output_dir / "run_config.yaml").open("w", encoding="utf-8") as config_file:
            yaml.safe_dump(run_config, config_file, sort_keys=False)
        return

    pd.DataFrame([result.summary for result in results]).to_csv(
        output_dir / "summary.csv",
        index=False,
    )
    pd.DataFrame([_window_row(result) for result in results]).to_csv(
        output_dir / "windows.csv",
        index=False,
    )
    pd.concat(
        [_with_pair_window(result.trades, result) for result in results],
        ignore_index=True,
    ).to_csv(output_dir / "all_trades.csv", index=False)
    pd.concat(
        [_with_pair_window(result.equity_curve, result) for result in results],
        ignore_index=True,
    ).to_csv(output_dir / "all_equity_curves.csv", index=False)
    for pair_id in sorted({result.pair_id for result in results}):
        pair_results = [result for result in results if result.pair_id == pair_id]
        _concat_result_frames(pair_results, "signals").to_csv(
            output_dir / f"{pair_id}_signals.csv",
            index=False,
        )
        _concat_result_frames(pair_results, "trades").to_csv(
            output_dir / f"{pair_id}_trades.csv",
            index=False,
        )
        build_trade_bucket_report(_concat_result_frames(pair_results, "trades")).to_csv(
            output_dir / f"{pair_id}_trade_buckets.csv",
            index=False,
        )
        _concat_result_frames(pair_results, "equity_curve").to_csv(
            output_dir / f"{pair_id}_equity_curve.csv",
            index=False,
        )
        pair_results[0].spread.to_csv(output_dir / f"{pair_id}_spread.csv")
    for result in results:
        export_backtest_result(result, output_dir)
    run_config = dict(config)
    run_config["effective_timeframe"] = config.get("historical_data", {}).get(
        "timeframe",
        "60m",
    )
    run_config["effective_backtest_parameters"] = [
        result.effective_parameters for result in results
    ]
    with (output_dir / "run_config.yaml").open("w", encoding="utf-8") as config_file:
        yaml.safe_dump(run_config, config_file, sort_keys=False)


def _period_mask(df: pd.DataFrame, start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.Series:
    start_ts = _timestamp_like_index(start, df.index)
    end_ts = _timestamp_like_index(end, df.index)
    return (df.index >= start_ts) & (df.index <= end_ts)


def _rolling_signal_stats(spreads: pd.Series, lookback_bars: int) -> pd.DataFrame:
    rolling = spreads.rolling(window=lookback_bars, min_periods=1)
    rolling_mean = rolling.mean()
    rolling_std = rolling.std(ddof=0)
    zscore = (spreads - rolling_mean) / rolling_std
    zscore = zscore.mask(rolling_std <= 0)
    return pd.DataFrame(
        {
            "rolling_mean": rolling_mean,
            "rolling_std": rolling_std,
            "zscore": zscore,
        },
        index=spreads.index,
    )


def _timestamp_like_index(value: str, index: pd.Index) -> pd.Timestamp:
    timestamp = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
    timezone = getattr(index, "tz", None)
    if timezone is not None and timestamp.tzinfo is None:
        return timestamp.tz_localize(timezone)
    if timezone is not None:
        return timestamp.tz_convert(timezone)
    if timezone is None and timestamp.tzinfo is not None:
        return timestamp.tz_convert(None)
    return timestamp


def _calculate_summary(
    initial_capital: float,
    trades: pd.DataFrame,
    equity_curve: pd.DataFrame,
    test_rows: int,
    signal_rows: pd.DataFrame,
) -> dict[str, Any]:
    gross_pnl = float(trades["gross_pnl"].sum()) if "gross_pnl" in trades else 0.0
    cost_total = float(trades["cost_total"].sum()) if "cost_total" in trades else 0.0
    net_pnl = float(trades["net_pnl"].sum()) if "net_pnl" in trades else 0.0
    trade_count = len(trades)
    winning_trades = int((trades["net_pnl"] > 0).sum()) if "net_pnl" in trades else 0
    avg_trade_pnl = float(trades["net_pnl"].mean()) if trade_count else 0.0
    average_gross_pnl = float(trades["gross_pnl"].mean()) if trade_count else 0.0
    average_cost = float(trades["cost_total"].mean()) if trade_count else 0.0
    avg_holding = float(trades["holding_bars"].mean()) if "holding_bars" in trades and trade_count else 0.0
    max_drawdown = _max_drawdown(equity_curve["equity"]) if "equity" in equity_curve else 0.0
    sharpe = _sharpe(equity_curve["equity"]) if "equity" in equity_curve else None
    exposure_rows = int((signal_rows["signal"] != Signal.HOLD.value).sum()) if "signal" in signal_rows else 0

    return {
        "total_return": net_pnl / initial_capital,
        "gross_pnl": gross_pnl,
        "cost_total": cost_total,
        "net_pnl": net_pnl,
        "number_of_trades": trade_count,
        "win_rate": winning_trades / trade_count if trade_count else 0.0,
        "average_trade_pnl": avg_trade_pnl,
        "average_entry_edge_bps": _mean_or_zero(trades, "entry_edge_bps"),
        "median_entry_edge_bps": _median_or_zero(trades, "entry_edge_bps"),
        "average_cost_per_trade": average_cost,
        "average_gross_pnl_per_trade": average_gross_pnl,
        "average_net_pnl_per_trade": avg_trade_pnl,
        "gross_to_cost_ratio": gross_pnl / cost_total if cost_total else None,
        "net_to_cost_ratio": net_pnl / cost_total if cost_total else None,
        "average_edge_to_cost_ratio": _mean_or_zero(trades, "edge_to_cost_ratio"),
        "median_edge_to_cost_ratio": _median_or_zero(trades, "edge_to_cost_ratio"),
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "average_holding_bars": avg_holding,
        "exposure_time_pct": exposure_rows / test_rows if test_rows else 0.0,
    }


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return float(drawdown.min())


def _sharpe(equity: pd.Series) -> float | None:
    returns = equity.pct_change().dropna()
    if len(returns) < 2:
        return None
    std = returns.std(ddof=0)
    if std == 0:
        return None
    return float(returns.mean() / std)


def _year_start(year: int, timezone) -> pd.Timestamp:
    timestamp = pd.Timestamp(year=year, month=1, day=1)
    return timestamp.tz_localize(timezone) if timezone is not None else timestamp


def _year_end(year: int, timezone) -> pd.Timestamp:
    timestamp = pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59, second=59)
    return timestamp.tz_localize(timezone) if timezone is not None else timestamp


def _window_id(train_df: pd.DataFrame, test_df: pd.DataFrame) -> str:
    return f"{train_df.index.min().date()}_{test_df.index.min().date()}"


def _window_row(result: BacktestResult) -> dict[str, Any]:
    return {
        "pair_id": result.pair_id,
        "window_id": result.window_id,
        "train_start": result.summary["train_start"],
        "train_end": result.summary["train_end"],
        "test_start": result.summary["test_start"],
        "test_end": result.summary["test_end"],
    }


def _with_pair_window(df: pd.DataFrame, result: BacktestResult) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["pair_id", "window_id"])
    output = df.copy()
    if "window_id" not in output.columns:
        output.insert(0, "window_id", result.window_id)
    if "pair_id" not in output.columns:
        output.insert(0, "pair_id", result.pair_id)
    return output


def _concat_result_frames(results: list[BacktestResult], attr_name: str) -> pd.DataFrame:
    frames = [
        _with_pair_window(getattr(result, attr_name), result)
        for result in results
        if not getattr(result, attr_name).empty
    ]
    if not frames:
        return pd.DataFrame(columns=["pair_id", "window_id"])
    return pd.concat(frames, ignore_index=True)


def build_trade_bucket_report(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "bucket_type",
                "bucket",
                "number_of_trades",
                "gross_pnl",
                "cost_total",
                "net_pnl",
                "average_gross_pnl",
                "average_net_pnl",
                "win_rate",
            ]
        )
    rows = []
    rows.extend(_bucket_rows(trades, "entry_zscore", [0, 2.5, 3.0, 4.0, float("inf")], "entry_zscore"))
    rows.extend(_bucket_rows(trades, "entry_edge_bps", [0, 10, 20, 30, 50, float("inf")], "entry_edge_bps"))
    rows.extend(_bucket_rows(trades, "holding_bars", [0, 3, 6, 11, 26, float("inf")], "holding_bars"))
    with_hours = trades.copy()
    with_hours["entry_hour_utc"] = pd.to_datetime(with_hours["entry_timestamp"], utc=True).dt.hour
    rows.extend(_group_rows(with_hours, "entry_hour_utc", "entry_hour_utc"))
    return pd.DataFrame(rows)


def _bucket_rows(
    trades: pd.DataFrame,
    column: str,
    bins: list[float],
    bucket_type: str,
) -> list[dict[str, Any]]:
    labels = [f"{bins[i]} to {bins[i + 1]}" for i in range(len(bins) - 2)] + [f"{bins[-2]}+"]
    bucketed = trades.copy()
    bucketed["bucket"] = pd.cut(
        bucketed[column].abs() if column == "entry_zscore" else bucketed[column],
        bins=bins,
        labels=labels,
        right=False,
        include_lowest=True,
    )
    return _group_rows(bucketed, "bucket", bucket_type)


def _group_rows(trades: pd.DataFrame, group_column: str, bucket_type: str) -> list[dict[str, Any]]:
    rows = []
    for bucket, group in trades.dropna(subset=[group_column]).groupby(group_column, observed=False):
        rows.append(
            {
                "bucket_type": bucket_type,
                "bucket": bucket,
                "number_of_trades": len(group),
                "gross_pnl": float(group["gross_pnl"].sum()),
                "cost_total": float(group["cost_total"].sum()),
                "net_pnl": float(group["net_pnl"].sum()),
                "average_gross_pnl": float(group["gross_pnl"].mean()),
                "average_net_pnl": float(group["net_pnl"].mean()),
                "win_rate": float((group["net_pnl"] > 0).mean()),
            }
        )
    return rows


def _mean_or_zero(df: pd.DataFrame, column: str) -> float:
    if column not in df or df.empty:
        return 0.0
    return float(df[column].dropna().mean()) if not df[column].dropna().empty else 0.0


def _median_or_zero(df: pd.DataFrame, column: str) -> float:
    if column not in df or df.empty:
        return 0.0
    return float(df[column].dropna().median()) if not df[column].dropna().empty else 0.0


PARAMETER_KEYS = [
    "lookback_bars",
    "entry_zscore",
    "exit_zscore",
    "max_holding_bars",
    "min_expected_edge_bps",
    "min_deviation_bps",
    "min_expected_reversion_bps",
    "capital_fraction_per_trade",
    "commission_bps_per_leg",
    "estimated_half_spread_bps_per_leg",
    "slippage_bps_per_leg",
    "allowed_direction",
    "entry_hours_utc",
    "exclude_entry_hours_utc",
    "max_entry_edge_bps",
]


def resolve_effective_backtest_config(config: dict, pair_id: str) -> tuple[dict, dict[str, str]]:
    backtest_config = dict(config["backtest"])
    sources = {key: "default" for key in backtest_config}
    pair_parameters = config.get("pair_parameters", {}).get(pair_id, {})
    for key, value in pair_parameters.items():
        backtest_config[key] = value
        sources[key] = "pair_config"
    for key, value in config.get("cli_backtest_overrides", {}).items():
        backtest_config[key] = value
        sources[key] = "cli"
    return backtest_config, sources


def _summary_parameter_fields(backtest_config: dict) -> dict[str, Any]:
    return {
        "lookback_bars": backtest_config.get("lookback_bars"),
        "entry_zscore": backtest_config.get("entry_zscore"),
        "exit_zscore": backtest_config.get("exit_zscore"),
        "max_holding_bars": backtest_config.get("max_holding_bars"),
        "min_expected_edge_bps": backtest_config.get("min_expected_edge_bps"),
        "capital_fraction_per_trade": backtest_config.get("capital_fraction_per_trade"),
        "commission_bps_per_leg": backtest_config.get("commission_bps_per_leg"),
        "half_spread_bps_per_leg": backtest_config.get(
            "estimated_half_spread_bps_per_leg"
        ),
        "slippage_bps_per_leg": backtest_config.get("slippage_bps_per_leg"),
        "allowed_direction": backtest_config.get("allowed_direction", "any"),
        "entry_hours_utc": _format_optional_list(
            backtest_config.get("entry_hours_utc")
        ),
        "exclude_entry_hours_utc": _format_optional_list(
            backtest_config.get("exclude_entry_hours_utc")
        ),
        "max_entry_edge_bps": backtest_config.get("max_entry_edge_bps"),
    }


def _effective_parameter_report(
    pair_id: str,
    backtest_config: dict,
    sources: dict[str, str],
) -> dict[str, Any]:
    report: dict[str, Any] = {"pair_id": pair_id}
    for key in PARAMETER_KEYS:
        output_key = "half_spread_bps_per_leg" if key == "estimated_half_spread_bps_per_leg" else key
        report[f"effective_{output_key}"] = backtest_config.get(key)
        report[f"{output_key}_source"] = sources.get(key, "default")
    return report


def _format_optional_list(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)
