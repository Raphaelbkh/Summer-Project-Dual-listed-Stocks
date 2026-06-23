"""Walk-forward statistical spread model for offline backtests."""

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class Signal(StrEnum):
    ENTER_SHORT_SWEDEN_LONG_FINLAND = "ENTER_SHORT_SWEDEN_LONG_FINLAND"
    ENTER_LONG_SWEDEN_SHORT_FINLAND = "ENTER_LONG_SWEDEN_SHORT_FINLAND"
    ENTER_LONG_SPREAD = "ENTER_SHORT_SWEDEN_LONG_FINLAND"
    ENTER_SHORT_SPREAD = "ENTER_LONG_SWEDEN_SHORT_FINLAND"
    EXIT = "EXIT"
    HOLD = "HOLD"


@dataclass
class WalkForwardSpreadModel:
    entry_zscore: float = 2.0
    exit_zscore: float = 0.5
    lookback_bars: int = 100
    spread_mean: float | None = None
    spread_std: float | None = None
    fit_rows: int = 0

    def fit(self, train_df: pd.DataFrame) -> None:
        """Fit model parameters on the training period only."""
        spreads = train_df["spread_pct"].dropna()
        if spreads.empty:
            raise ValueError("Training data must include spread_pct rows.")
        spread_std = float(spreads.std(ddof=0))
        if spread_std <= 0:
            raise ValueError("Training spread standard deviation must be positive.")
        self.spread_mean = float(spreads.mean())
        self.spread_std = spread_std
        self.fit_rows = len(train_df)

    def predict_bar(self, history_until_now: pd.DataFrame) -> dict:
        """Predict using only rows available up to the current timestamp."""
        if self.spread_mean is None or self.spread_std is None:
            raise RuntimeError("Model must be fit before prediction.")
        if history_until_now.empty:
            return {"zscore": None, "signal": Signal.HOLD}

        recent = history_until_now.tail(self.lookback_bars)
        current_spread = float(recent["spread_pct"].iloc[-1])
        rolling_mean = float(recent["spread_pct"].mean())
        rolling_std = float(recent["spread_pct"].std(ddof=0))
        if rolling_std <= 0:
            return {
                "zscore": None,
                "rolling_mean": rolling_mean,
                "rolling_std": rolling_std,
                "signal": Signal.HOLD,
            }
        zscore = (current_spread - rolling_mean) / rolling_std
        return {
            "zscore": zscore,
            "rolling_mean": rolling_mean,
            "rolling_std": rolling_std,
            "signal": self.generate_signal_from_zscore(zscore),
        }

    def generate_signal(self, history_until_now: pd.DataFrame) -> Signal:
        """Return the current signal without exposing future rows."""
        return self.predict_bar(history_until_now)["signal"]

    def generate_signal_from_zscore(self, zscore: float) -> Signal:
        if zscore >= self.entry_zscore:
            return Signal.ENTER_SHORT_SWEDEN_LONG_FINLAND
        if zscore <= -self.entry_zscore:
            return Signal.ENTER_LONG_SWEDEN_SHORT_FINLAND
        if abs(zscore) <= self.exit_zscore:
            return Signal.EXIT
        return Signal.HOLD
