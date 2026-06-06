from pathlib import Path

import pytest
import yaml

from src.data.live.ibkr_market_data import (
    IBKRConnectionConfig,
    load_ibkr_connection_config,
    resolve_ibkr_port,
    validate_observe_only_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def test_config_defaults_to_paper_observe_only() -> None:
    config = load_config()

    assert config["ibkr"]["host"] == "127.0.0.1"
    assert config["ibkr"]["mode"] == "paper"
    assert config["ibkr"]["paper_port"] == 7497
    assert config["ibkr"]["live_port"] == 7496
    assert config["ibkr"]["gateway_paper_port"] == 4002
    assert config["ibkr"]["gateway_live_port"] == 4001
    assert config["execution"]["observe_only"] is True


def test_config_disables_auto_selection_and_activation() -> None:
    config = load_config()
    universe_selection = config["universe_selection"]

    assert universe_selection["mode"] == "ticker_watchlist_resolved_mapping"
    assert universe_selection["allow_auto_discovery"] is False
    assert universe_selection["allow_auto_screening"] is False
    assert universe_selection["allow_ai_generated_tickers"] is False
    assert universe_selection["allow_auto_activation"] is False
    assert universe_selection["require_manual_active_true"] is True


def test_config_limits_mvp_markets_and_live_sources() -> None:
    config = load_config()

    assert config["market_universe"]["included_countries"] == [
        "Sweden",
        "Finland",
        "Denmark",
    ]
    assert config["market_universe"]["excluded_countries"] == ["Norway"]
    assert config["market_universe"]["included_currencies"] == ["SEK", "EUR", "DKK"]
    assert config["market_universe"]["excluded_currencies"] == ["NOK"]
    assert config["fx"]["live_provider"] == "IBKR_IDEALPRO"


def test_mapping_csv_files_exist_with_expected_headers() -> None:
    expected_headers = {
        "user_watchlist.csv": "ticker,notes",
        "resolved_listings.csv": (
            "watchlist_ticker,resolved_symbol,company_name,exchange,currency,"
            "country,primary_exchange,sec_type,ibkr_conid,ibkr_local_symbol,"
            "ibkr_trading_class,resolution_source,resolved_status,"
            "rejection_reason,notes"
        ),
        "resolved_pairs.csv": (
            "pair_id,source_ticker,company_name,long_symbol,long_exchange,"
            "long_currency,short_symbol,short_exchange,short_currency,fx_pair,"
            "conversion_ratio,active,resolved_status,resolution_source,"
            "rejection_reason,notes"
        ),
        "rejected_watchlist_rows.csv": "ticker,rejection_reason,notes",
        "ibkr_live_test_pairs.csv": (
            "pair_id,source_ticker,company_name,long_symbol,long_exchange,"
            "long_currency,short_symbol,short_exchange,short_currency,fx_pair,"
            "conversion_ratio,active,resolved_status,resolution_source,"
            "rejection_reason,notes"
        ),
    }

    for file_name, expected_header in expected_headers.items():
        path = PROJECT_ROOT / "data" / "mappings" / file_name
        assert path.read_text(encoding="utf-8").splitlines()[0] == expected_header


def make_connection_config(mode: str = "paper", use_gateway: bool = False) -> IBKRConnectionConfig:
    return IBKRConnectionConfig(
        host="127.0.0.1",
        paper_port=7497,
        live_port=7496,
        gateway_paper_port=4002,
        gateway_live_port=4001,
        client_id_market_data=1,
        mode=mode,
        use_gateway=use_gateway,
    )


def test_paper_tws_resolves_to_7497() -> None:
    assert resolve_ibkr_port(make_connection_config(mode="paper")) == 7497


def test_live_tws_resolves_to_7496() -> None:
    assert resolve_ibkr_port(make_connection_config(mode="live")) == 7496


def test_paper_gateway_resolves_to_4002() -> None:
    assert resolve_ibkr_port(make_connection_config(mode="paper", use_gateway=True)) == 4002


def test_live_gateway_resolves_to_4001() -> None:
    assert resolve_ibkr_port(make_connection_config(mode="live", use_gateway=True)) == 4001


def test_observe_only_false_raises() -> None:
    config = load_config()
    config["execution"]["observe_only"] = False

    with pytest.raises(ValueError, match="observe_only"):
        validate_observe_only_config(config)


def test_unsupported_mode_raises() -> None:
    config = load_config()
    config["ibkr"]["mode"] = "demo"

    with pytest.raises(ValueError, match="Unsupported IBKR mode"):
        load_ibkr_connection_config(config)


def test_default_config_loads_as_paper() -> None:
    config = load_ibkr_connection_config(load_config())

    assert config.mode == "paper"
    assert resolve_ibkr_port(config) == 7497
