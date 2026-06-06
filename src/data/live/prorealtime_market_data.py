"""ProRealTime DDE/CSV quote provider for the observe-only monitor."""

from pathlib import Path
from typing import Any

import pandas as pd

from src.data.live.quote_models import EquityQuote, FXQuote
from src.utils.time_utils import ensure_utc, utc_now


SOURCE = "PROREALTIME_DDE_CSV"
REQUIRED_COLUMNS = {
    "kind",
    "symbol",
    "exchange",
    "currency",
    "pair",
    "bid",
    "ask",
    "bid_size",
    "ask_size",
    "last",
    "timestamp",
}


class ProRealTimeCSVQuoteProvider:
    """Read latest ProRealTime quotes from a local DDE-fed CSV file."""

    def __init__(self, quotes_path: Path) -> None:
        self.quotes_path = quotes_path
        self.connected = False

    def connect(self) -> None:
        """Mark the file-backed provider as ready."""
        self.connected = True

    def disconnect(self) -> None:
        """Mark the file-backed provider as disconnected."""
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def load_quotes(self) -> pd.DataFrame:
        """Load quote rows from the ProRealTime bridge CSV."""
        if not self.quotes_path.exists():
            return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))

        df = pd.read_csv(self.quotes_path, dtype=str, keep_default_na=False)
        normalized_columns = {column: column.strip().lower() for column in df.columns}
        df = df.rename(columns=normalized_columns)
        missing_columns = REQUIRED_COLUMNS - set(df.columns)
        if missing_columns:
            raise ValueError(
                "ProRealTime quote CSV missing columns: "
                + ", ".join(sorted(missing_columns))
            )
        return df

    def get_equity_quote(
        self,
        symbol: str,
        exchange: str,
        currency: str,
    ) -> EquityQuote:
        """Return the latest equity quote matching symbol/exchange/currency."""
        df = self.load_quotes()
        rows = df[
            (df["kind"].map(_normalize) == "EQUITY")
            & (df["symbol"].map(_normalize) == _normalize(symbol))
            & (df["exchange"].map(_normalize) == _normalize(exchange))
            & (df["currency"].map(_normalize) == _normalize(currency))
        ]
        row = _latest_row(rows)
        return EquityQuote(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            bid=_optional_float(row.get("bid")),
            ask=_optional_float(row.get("ask")),
            bid_size=_optional_float(row.get("bid_size")),
            ask_size=_optional_float(row.get("ask_size")),
            last=_optional_float(row.get("last")),
            timestamp=_timestamp(row.get("timestamp")),
            source=SOURCE,
        )

    def get_fx_quote(self, pair: str) -> FXQuote:
        """Return the latest FX quote matching the six-letter pair."""
        normalized_pair = _normalize(pair)
        df = self.load_quotes()
        rows = df[
            (df["kind"].map(_normalize) == "FX")
            & (df["pair"].map(_normalize) == normalized_pair)
        ]
        row = _latest_row(rows)
        return FXQuote(
            pair=normalized_pair,
            base_currency=normalized_pair[:3],
            quote_currency=normalized_pair[3:],
            bid=_optional_float(row.get("bid")),
            ask=_optional_float(row.get("ask")),
            last=_optional_float(row.get("last")),
            timestamp=_timestamp(row.get("timestamp")),
            source=SOURCE,
        )


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _timestamp(value: Any):
    if value is None or str(value).strip() == "":
        return utc_now()
    try:
        return ensure_utc(pd.Timestamp(value).to_pydatetime())
    except (TypeError, ValueError):
        return utc_now()


def _latest_row(rows: pd.DataFrame) -> pd.Series:
    if rows.empty:
        return pd.Series(dtype=str)
    parsed = pd.to_datetime(rows["timestamp"], errors="coerce", utc=True)
    if parsed.notna().any():
        return rows.loc[parsed.idxmax()]
    return rows.iloc[-1]
