from pathlib import Path

import pytest
import yaml

from src.data.live.ibkr_market_data import (
    IBKRConnectionConfig,
    assert_no_live_trading_enabled,
    assert_order_allowed,
    load_ibkr_connection_config,
    resolve_ibkr_port,
    validate_observe_only_config,
)
from scripts.test_ibkr_live_data_diagnostic import validate_live_data_diagnostic_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    with SETTINGS_PATH.open("r", encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def test_config_defaults_to_paper_observe_only() -> None:
    config = load_config()

    assert config["ibkr"]["host"] == "127.0.0.1"
    assert config["ibkr"]["mode"] == "paper"
    assert config["ibkr"]["use_gateway"] is True
    assert config["ibkr"]["paper_port"] == 7497
    assert config["ibkr"]["live_port"] == 7496
    assert config["ibkr"]["gateway_paper_port"] == 4002
    assert config["ibkr"]["gateway_live_port"] == 4001
    assert config["ibkr"]["client_id_orders"] == 3
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
    assert "market_data" not in config
    assert "ig" not in config
    assert "ig_live_data" not in config
    assert "ig_demo_execution" not in config
    assert "live_provider" not in config["fx"]


def test_env_example_is_ibkr_only() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "IBKR_HOST=127.0.0.1" in env_example
    assert "IBKR_PORT=4002" in env_example
    assert "# IBKR_PORT=4001" in env_example
    assert "ENABLE_LIVE_TRADING=false" in env_example
    assert "I" + "G_" not in env_example
    assert "PRO" + "REALTIME" not in env_example.upper()


def test_requirements_use_ib_async_not_legacy_package() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "ib_async" in requirements
    assert "ib_" + "insync" not in requirements


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
    assert resolve_ibkr_port(config) == 4002


def test_explicit_ibkr_port_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IBKR_PORT", "4100")

    config = load_ibkr_connection_config(load_config())

    assert resolve_ibkr_port(config) == 4100


def test_env_live_gateway_resolves_to_4001(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IBKR_MODE", "live")
    monkeypatch.setenv("IBKR_USE_GATEWAY", "true")

    config = load_ibkr_connection_config(load_config())

    assert config.mode == "live"
    assert config.use_gateway is True
    assert resolve_ibkr_port(config) == 4001


def test_env_overrides_client_ids_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IBKR_HOST", "localhost")
    monkeypatch.setenv("IBKR_CLIENT_ID_MARKET_DATA", "11")
    monkeypatch.setenv("IBKR_CLIENT_ID_FX", "12")
    monkeypatch.setenv("IBKR_CLIENT_ID_ORDERS", "13")

    config = load_ibkr_connection_config(load_config())

    assert config.host == "localhost"
    assert config.client_id_market_data == 11
    assert config.client_id_fx == 12
    assert config.client_id_orders == 13


def test_live_diagnostic_refuses_unless_mode_is_live() -> None:
    with pytest.raises(RuntimeError, match="IBKR_MODE=live"):
        validate_live_data_diagnostic_config(make_connection_config(mode="paper"))


def test_live_diagnostic_allows_live_data_with_live_trading_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")

    validate_live_data_diagnostic_config(make_connection_config(mode="live", use_gateway=True))


def test_data_only_script_refuses_when_live_trading_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")

    with pytest.raises(RuntimeError, match="ENABLE_LIVE_TRADING"):
        assert_no_live_trading_enabled()


def test_live_order_placement_blocked_unless_live_trading_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")

    with pytest.raises(RuntimeError, match="Live order placement is blocked"):
        assert_order_allowed(make_connection_config(mode="live"))


def test_live_order_guard_allows_only_with_explicit_live_trading_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")

    assert_order_allowed(make_connection_config(mode="live"))
