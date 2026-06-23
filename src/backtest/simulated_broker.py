"""Simulated broker for offline pair backtests."""

from dataclasses import dataclass, asdict
from typing import Any

import pandas as pd

from src.backtest.walk_forward_model import Signal


@dataclass
class SimulatedTrade:
    pair_id: str
    direction: str
    entry_timestamp: Any
    exit_timestamp: Any
    capital_allocated_sek: float
    long_quantity: float
    short_quantity: float
    entry_long_close_sek: float
    entry_short_close_sek: float
    exit_long_close_sek: float
    exit_short_close_sek: float
    entry_long_price: float
    entry_short_price: float
    exit_long_price: float
    exit_short_price: float
    entry_long_notional_sek: float
    entry_short_notional_sek: float
    exit_long_notional_sek: float
    exit_short_notional_sek: float
    entry_spread_pct: float
    entry_edge_bps: float
    entry_zscore: float | None
    estimated_roundtrip_cost_bps: float
    edge_to_cost_ratio: float | None
    long_leg_gross_pnl: float
    short_leg_gross_pnl: float
    entry_commission_sek: float
    exit_commission_sek: float
    gross_pnl: float
    cost_total: float
    net_pnl: float
    holding_bars: int


class SimulatedBroker:
    """Stateful simulated broker that never places real orders."""

    def __init__(
        self,
        pair_id: str,
        initial_capital: float,
        commission_bps_per_leg: float,
        estimated_half_spread_bps_per_leg: float,
        slippage_bps_per_leg: float,
        max_holding_bars: int,
        capital_fraction_per_trade: float = 1.0,
        invert_signals: bool = False,
        min_expected_edge_bps: float = 0.0,
        min_deviation_bps: float = 0.0,
        min_expected_reversion_bps: float = 0.0,
        allowed_direction: str = "any",
        entry_hours_utc: list[int] | None = None,
        exclude_entry_hours_utc: list[int] | None = None,
        max_entry_edge_bps: float | None = None,
    ) -> None:
        self.pair_id = pair_id
        self.initial_capital = float(initial_capital)
        self.cash = float(initial_capital)
        self.commission_bps_per_leg = float(commission_bps_per_leg)
        self.estimated_half_spread_bps_per_leg = float(estimated_half_spread_bps_per_leg)
        self.slippage_bps_per_leg = float(slippage_bps_per_leg)
        self.max_holding_bars = int(max_holding_bars)
        self.capital_fraction_per_trade = float(capital_fraction_per_trade)
        self.invert_signals = bool(invert_signals)
        self.min_expected_edge_bps = float(min_expected_edge_bps)
        self.min_deviation_bps = float(min_deviation_bps)
        self.min_expected_reversion_bps = float(min_expected_reversion_bps)
        self.allowed_direction = allowed_direction
        self.entry_hours_utc = _normalize_hours(entry_hours_utc)
        self.exclude_entry_hours_utc = _normalize_hours(exclude_entry_hours_utc)
        self.max_entry_edge_bps = (
            None if max_entry_edge_bps is None else float(max_entry_edge_bps)
        )
        self.position: dict[str, Any] | None = None
        self.trades: list[dict[str, Any]] = []
        self.equity_curve: list[dict[str, Any]] = []

    def on_bar(
        self,
        timestamp: Any,
        row: pd.Series,
        signal: Signal,
        zscore: float | None = None,
    ) -> None:
        signal = self._effective_signal(signal)
        if self.position is None:
            if signal in {
                Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND,
                Signal.ENTER_LONG_SWEDEN_SHORT_FINLAND,
            } and self._entry_passes_filters(timestamp, row, signal):
                self._enter(timestamp, row, signal, zscore)
        else:
            self.position["holding_bars"] += 1
            should_exit = signal == Signal.EXIT or (
                self.position["holding_bars"] >= self.max_holding_bars
            )
            if should_exit:
                self._exit(timestamp, row)

        self.equity_curve.append(
            {
                "timestamp": timestamp,
                "equity": self.cash + self._unrealized_pnl(row),
                "position": "" if self.position is None else self.position["direction"],
            }
        )

    def close_open_position(self, timestamp: Any, row: pd.Series) -> None:
        if self.position is not None:
            self._exit(timestamp, row)

    def _enter(
        self,
        timestamp: Any,
        row: pd.Series,
        signal: Signal,
        zscore: float | None,
    ) -> None:
        direction = (
            "SHORT_SWEDEN_LONG_FINLAND"
            if signal == Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND
            else "LONG_SWEDEN_SHORT_FINLAND"
        )
        long_close = float(row["long_price_base"])
        short_close = float(row["short_price_base"])
        capital_allocated = self.cash * self.capital_fraction_per_trade
        leg_capital = capital_allocated / 2
        long_quantity = leg_capital / long_close
        short_quantity = leg_capital / short_close
        entry_long_price = (
            self._buy_price(long_close)
            if direction == "SHORT_SWEDEN_LONG_FINLAND"
            else self._sell_price(long_close)
        )
        entry_short_price = (
            self._sell_price(short_close)
            if direction == "SHORT_SWEDEN_LONG_FINLAND"
            else self._buy_price(short_close)
        )
        entry_long_notional = abs(long_quantity * entry_long_price)
        entry_short_notional = abs(short_quantity * entry_short_price)
        entry_commission = self._commission(entry_long_notional + entry_short_notional)
        edge_bps = entry_edge_bps(row)
        roundtrip_cost_bps = estimated_roundtrip_cost_bps(
            self.commission_bps_per_leg,
            self.estimated_half_spread_bps_per_leg,
            self.slippage_bps_per_leg,
        )

        self.position = {
            "direction": direction,
            "entry_timestamp": timestamp,
            "capital_allocated_sek": capital_allocated,
            "long_quantity": long_quantity,
            "short_quantity": short_quantity,
            "entry_long_close_sek": long_close,
            "entry_short_close_sek": short_close,
            "entry_long_price": entry_long_price,
            "entry_short_price": entry_short_price,
            "entry_long_notional_sek": entry_long_notional,
            "entry_short_notional_sek": entry_short_notional,
            "entry_spread_pct": entry_spread_pct(row),
            "entry_edge_bps": edge_bps,
            "entry_zscore": zscore,
            "estimated_roundtrip_cost_bps": roundtrip_cost_bps,
            "edge_to_cost_ratio": edge_to_cost_ratio(edge_bps, roundtrip_cost_bps),
            "entry_commission_sek": entry_commission,
            "holding_bars": 0,
        }

    def _exit(self, timestamp: Any, row: pd.Series) -> None:
        if self.position is None:
            return

        direction = self.position["direction"]
        exit_long_close = float(row["long_price_base"])
        exit_short_close = float(row["short_price_base"])
        exit_long_price = (
            self._sell_price(exit_long_close)
            if direction == "SHORT_SWEDEN_LONG_FINLAND"
            else self._buy_price(exit_long_close)
        )
        exit_short_price = (
            self._buy_price(exit_short_close)
            if direction == "SHORT_SWEDEN_LONG_FINLAND"
            else self._sell_price(exit_short_close)
        )

        long_leg_gross_pnl = self._long_leg_pnl(direction, exit_long_price)
        short_leg_gross_pnl = self._short_leg_pnl(direction, exit_short_price)
        gross_pnl = long_leg_gross_pnl + short_leg_gross_pnl
        exit_long_notional = abs(self.position["long_quantity"] * exit_long_price)
        exit_short_notional = abs(self.position["short_quantity"] * exit_short_price)
        exit_commission = self._commission(exit_long_notional + exit_short_notional)
        cost_total = self.position["entry_commission_sek"] + exit_commission
        net_pnl = gross_pnl - cost_total
        self.cash += net_pnl

        trade = SimulatedTrade(
            pair_id=self.pair_id,
            direction=direction,
            entry_timestamp=self.position["entry_timestamp"],
            exit_timestamp=timestamp,
            capital_allocated_sek=self.position["capital_allocated_sek"],
            long_quantity=self.position["long_quantity"],
            short_quantity=self.position["short_quantity"],
            entry_long_close_sek=self.position["entry_long_close_sek"],
            entry_short_close_sek=self.position["entry_short_close_sek"],
            exit_long_close_sek=exit_long_close,
            exit_short_close_sek=exit_short_close,
            entry_long_price=self.position["entry_long_price"],
            entry_short_price=self.position["entry_short_price"],
            exit_long_price=exit_long_price,
            exit_short_price=exit_short_price,
            entry_long_notional_sek=self.position["entry_long_notional_sek"],
            entry_short_notional_sek=self.position["entry_short_notional_sek"],
            exit_long_notional_sek=exit_long_notional,
            exit_short_notional_sek=exit_short_notional,
            entry_spread_pct=self.position["entry_spread_pct"],
            entry_edge_bps=self.position["entry_edge_bps"],
            entry_zscore=self.position["entry_zscore"],
            estimated_roundtrip_cost_bps=self.position["estimated_roundtrip_cost_bps"],
            edge_to_cost_ratio=self.position["edge_to_cost_ratio"],
            long_leg_gross_pnl=long_leg_gross_pnl,
            short_leg_gross_pnl=short_leg_gross_pnl,
            entry_commission_sek=self.position["entry_commission_sek"],
            exit_commission_sek=exit_commission,
            gross_pnl=gross_pnl,
            cost_total=cost_total,
            net_pnl=net_pnl,
            holding_bars=self.position["holding_bars"],
        )
        self.trades.append(asdict(trade))
        self.position = None

    def _gross_pnl(
        self,
        direction: str,
        exit_long_price: float,
        exit_short_price: float,
    ) -> float:
        if self.position is None:
            return 0.0
        return self._long_leg_pnl(direction, exit_long_price) + self._short_leg_pnl(
            direction,
            exit_short_price,
        )

    def _long_leg_pnl(self, direction: str, exit_long_price: float) -> float:
        if self.position is None:
            return 0.0
        if direction == "SHORT_SWEDEN_LONG_FINLAND":
            return self.position["long_quantity"] * (
                exit_long_price - self.position["entry_long_price"]
            )
        return self.position["long_quantity"] * (
            self.position["entry_long_price"] - exit_long_price
        )

    def _short_leg_pnl(self, direction: str, exit_short_price: float) -> float:
        if self.position is None:
            return 0.0
        if direction == "SHORT_SWEDEN_LONG_FINLAND":
            return self.position["short_quantity"] * (
                self.position["entry_short_price"] - exit_short_price
            )
        return self.position["short_quantity"] * (
            exit_short_price - self.position["entry_short_price"]
        )

    def _unrealized_pnl(self, row: pd.Series) -> float:
        if self.position is None:
            return 0.0
        direction = self.position["direction"]
        exit_long_price = row["long_price_base"]
        exit_short_price = row["short_price_base"]
        return self._gross_pnl(direction, exit_long_price, exit_short_price)

    def _buy_price(self, close: float) -> float:
        cost_bps = self.estimated_half_spread_bps_per_leg + self.slippage_bps_per_leg
        return float(close) * (1 + cost_bps / 10000)

    def _sell_price(self, close: float) -> float:
        cost_bps = self.estimated_half_spread_bps_per_leg + self.slippage_bps_per_leg
        return float(close) * (1 - cost_bps / 10000)

    def _commission(self, notional: float) -> float:
        return float(notional) * self.commission_bps_per_leg / 10000

    def _effective_signal(self, signal: Signal) -> Signal:
        if not self.invert_signals:
            return signal
        if signal == Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND:
            return Signal.ENTER_LONG_SWEDEN_SHORT_FINLAND
        if signal == Signal.ENTER_LONG_SWEDEN_SHORT_FINLAND:
            return Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND
        return signal

    def _entry_passes_filters(
        self,
        timestamp: Any,
        row: pd.Series,
        signal: Signal,
    ) -> bool:
        if not self._entry_direction_passes_filter(signal):
            return False
        if not self._entry_hour_passes_filter(timestamp):
            return False
        edge_bps = entry_edge_bps(row)
        required_edge_bps = max(
            self.min_expected_edge_bps,
            self.min_deviation_bps,
            self.min_expected_reversion_bps,
        )
        if edge_bps < required_edge_bps:
            return False
        if self.max_entry_edge_bps is not None and edge_bps > self.max_entry_edge_bps:
            return False
        return True

    def _entry_direction_passes_filter(self, signal: Signal) -> bool:
        if self.allowed_direction == "any":
            return True
        return _direction_from_signal(signal) == self.allowed_direction

    def _entry_hour_passes_filter(self, timestamp: Any) -> bool:
        timestamp_utc = pd.Timestamp(timestamp)
        if timestamp_utc.tzinfo is None:
            timestamp_utc = timestamp_utc.tz_localize("UTC")
        else:
            timestamp_utc = timestamp_utc.tz_convert("UTC")
        hour = timestamp_utc.hour
        if self.entry_hours_utc is not None and hour not in self.entry_hours_utc:
            return False
        if self.exclude_entry_hours_utc is not None and hour in self.exclude_entry_hours_utc:
            return False
        return True


def entry_edge_bps(row: pd.Series) -> float:
    return abs(entry_spread_pct(row)) * 10000


def entry_spread_pct(row: pd.Series) -> float:
    if "spread_pct" in row:
        return float(row["spread_pct"])
    return (float(row["short_price_base"]) - float(row["long_price_base"])) / float(
        row["long_price_base"]
    )


def estimated_roundtrip_cost_bps(
    commission_bps_per_leg: float,
    half_spread_bps_per_leg: float,
    slippage_bps_per_leg: float,
) -> float:
    # Approximation: two legs traded on entry and again on exit.
    return 4 * (
        float(commission_bps_per_leg)
        + float(half_spread_bps_per_leg)
        + float(slippage_bps_per_leg)
    )


def edge_to_cost_ratio(edge_bps: float, cost_bps: float) -> float | None:
    if cost_bps == 0:
        return None
    return edge_bps / cost_bps


def _direction_from_signal(signal: Signal) -> str:
    if signal == Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND:
        return "SHORT_SWEDEN_LONG_FINLAND"
    if signal == Signal.ENTER_LONG_SWEDEN_SHORT_FINLAND:
        return "LONG_SWEDEN_SHORT_FINLAND"
    return ""


def _normalize_hours(hours: list[int] | None) -> set[int] | None:
    if hours is None:
        return None
    normalized = {int(hour) for hour in hours}
    invalid = [hour for hour in normalized if hour < 0 or hour > 23]
    if invalid:
        raise ValueError("Entry hour filters must use UTC hours between 0 and 23.")
    return normalized
