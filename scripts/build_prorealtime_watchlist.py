"""Build ProRealTime bridge watchlist from user-provided tickers only."""

from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.live.prorealtime_bridge import write_prorealtime_bridge_watchlist  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def main() -> None:
    config_dict = load_config()
    user_watchlist_path = (
        PROJECT_ROOT / config_dict["universe_selection"]["user_watchlist_path"]
    )
    output_path = PROJECT_ROOT / config_dict["market_data"]["prorealtime_watchlist_path"]

    written_path = write_prorealtime_bridge_watchlist(
        user_watchlist_path=user_watchlist_path,
        output_path=output_path,
    )
    print(f"wrote: {written_path}")
    print("source: user_watchlist.csv")
    print("note: no tickers were added or suggested")


if __name__ == "__main__":
    main()
