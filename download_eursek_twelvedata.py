import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests


BASE_URL = "https://api.twelvedata.com/time_series"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download EURSEK historical hourly data from Twelve Data to TradingView-style CSV."
    )
    parser.add_argument("--symbol", default="EUR/SEK")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start", default="2009-01-01")
    parser.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--chunk-days", type=int, default=60)
    parser.add_argument("--out", default="FX_EURSEK_60.csv")
    parser.add_argument("--apikey", default=os.getenv("TWELVEDATA_API_KEY"))
    return parser.parse_args()


def to_dt(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def fetch_chunk(symbol: str, interval: str, start_dt: datetime, end_dt: datetime, apikey: str) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "interval": interval,
        "start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "apikey": apikey,
        "timezone": "UTC",
        "order": "ASC",
        "format": "JSON",
    }

    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data API error: {data.get('message', data)}")

    values = data.get("values", [])
    if not values:
        return pd.DataFrame()

    df = pd.DataFrame(values)

    # Twelve Data usually returns datetime, open, high, low, close.
    if "datetime" not in df.columns:
        raise RuntimeError(f"Unexpected response columns: {df.columns.tolist()}")

    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise RuntimeError(f"Missing required column from Twelve Data response: {col}")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    else:
        df["Volume"] = 0

    df["time"] = df["datetime"].map(lambda x: int(x.timestamp()))

    out = df[["time", "open", "high", "low", "close", "Volume"]].copy()
    return out


def download_all(symbol: str, interval: str, start: str, end: str, chunk_days: int, apikey: str) -> pd.DataFrame:
    if not apikey:
        raise RuntimeError(
            "Missing API key. Set TWELVEDATA_API_KEY or pass --apikey YOUR_KEY."
        )

    start_dt = to_dt(start)
    end_dt = to_dt(end)

    all_chunks = []
    current = start_dt

    while current < end_dt:
        chunk_end = min(current + timedelta(days=chunk_days), end_dt)

        print(f"Fetching {symbol} {interval}: {current.date()} -> {chunk_end.date()}")

        try:
            chunk = fetch_chunk(symbol, interval, current, chunk_end, apikey)
            if not chunk.empty:
                print(f"  rows: {len(chunk)}")
                all_chunks.append(chunk)
            else:
                print("  rows: 0")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            raise

        # Be polite with API limits.
        time.sleep(1.0)

        # Move forward one second to avoid overlapping exact boundary.
        current = chunk_end + timedelta(seconds=1)

    if not all_chunks:
        raise RuntimeError("No data downloaded.")

    result = pd.concat(all_chunks, ignore_index=True)
    result = result.drop_duplicates(subset=["time"])
    result = result.sort_values("time").reset_index(drop=True)

    return result


def main():
    args = parse_args()

    df = download_all(
        symbol=args.symbol,
        interval=args.interval,
        start=args.start,
        end=args.end,
        chunk_days=args.chunk_days,
        apikey=args.apikey,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    first = pd.to_datetime(df["time"].iloc[0], unit="s", utc=True)
    last = pd.to_datetime(df["time"].iloc[-1], unit="s", utc=True)

    print()
    print("DONE")
    print(f"output: {out_path}")
    print(f"rows: {len(df)}")
    print(f"first: {first}")
    print(f"last: {last}")


if __name__ == "__main__":
    main()
    