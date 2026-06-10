"""Manual observe-only ProRealTime DDE/CSV quote smoke test."""

from argparse import ArgumentParser, Namespace
from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.prorealtime_market_data import ProRealTimeCSVQuoteProvider  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Read latest ProRealTime CSV quotes.")
    parser.add_argument("--symbol", help="Equity symbol to inspect.")
    parser.add_argument("--exchange", help="Equity exchange to inspect.")
    parser.add_argument("--currency", help="Equity currency to inspect.")
    parser.add_argument("--fx-pair", help="FX pair to inspect, for example EURSEK.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_dict = load_config()
    quotes_path = PROJECT_ROOT / config_dict["market_data"]["prorealtime_quotes_path"]
    provider = ProRealTimeCSVQuoteProvider(quotes_path)
    provider.connect()

    print(f"provider: {config_dict['market_data']['live_provider']}")
    print(f"quotes_path: {quotes_path}")
    print(f"connected: {provider.is_connected()}")

    df = provider.load_quotes()
    print(f"rows: {len(df)}")
    print(f"columns: {','.join(df.columns)}")

    if args.symbol and args.exchange and args.currency:
        quote = provider.get_equity_quote(args.symbol, args.exchange, args.currency)
        print("")
        print("equity_quote:")
        print(f"symbol: {quote.symbol}")
        print(f"exchange: {quote.exchange}")
        print(f"currency: {quote.currency}")
        print(f"bid: {quote.bid}")
        print(f"ask: {quote.ask}")
        print(f"last: {quote.last}")
        print(f"timestamp: {quote.timestamp.isoformat()}")
        print(f"is_valid: {quote.is_valid}")
        print(f"spread_pct: {quote.spread_pct}")

    if args.fx_pair:
        quote = provider.get_fx_quote(args.fx_pair)
        print("")
        print("fx_quote:")
        print(f"pair: {quote.pair}")
        print(f"bid: {quote.bid}")
        print(f"ask: {quote.ask}")
        print(f"last: {quote.last}")
        print(f"timestamp: {quote.timestamp.isoformat()}")
        print(f"is_valid: {quote.is_valid}")
        print(f"spread_pct: {quote.spread_pct}")


if __name__ == "__main__":
    main()
