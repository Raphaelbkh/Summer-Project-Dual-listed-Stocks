import importlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_step_0_directories_exist() -> None:
    expected_dirs = [
        "config",
        "data/raw",
        "data/processed",
        "data/mappings",
        "data/live_quotes",
        "data/live_spreads",
        "scripts",
        "src/data/live",
        "src/data/borsdata",
        "src/data/mappings",
        "src/fx",
        "src/execution",
        "src/paper",
        "src/signal",
        "src/logging",
        "src/utils",
        "tests",
    ]

    for relative_path in expected_dirs:
        assert (PROJECT_ROOT / relative_path).is_dir()


def test_step_0_placeholder_modules_import() -> None:
    modules = [
        "src",
        "src.data.live.quote_models",
        "src.data.live.ibkr_market_data",
        "src.data.live.ibkr_contract_resolver",
        "src.data.borsdata.borsdata_client",
        "src.data.mappings.watchlist",
        "src.data.mappings.listing_master",
        "src.fx.ibkr_fx",
        "src.execution.entry_policy",
        "src.paper.tieto_readiness",
        "src.signal.executable_spread",
        "src.logging.csv_logger",
        "src.utils.time_utils",
    ]

    for module_name in modules:
        assert importlib.import_module(module_name)
