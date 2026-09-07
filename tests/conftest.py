import os
from pathlib import Path

import pytest

# Rich renders to the width of the terminal it finds, so the same correct message wraps in
# different places on different machines and an assertion spanning a space passes locally and
# fails on a runner with a narrower console. Pinning the width makes the rendering a constant.
CONSOLE_WIDTH = "120"


def pytest_configure(config):
    """Turn coverage off when nothing runs, so a collection does not report 0% and fail.

    `--cov` lives in `addopts`, which pytest also applies to `--collect-only`; without
    this the plugin measures a run that never happened and prints a failing total.
    """
    os.environ["COLUMNS"] = CONSOLE_WIDTH

    if not config.getoption("collectonly", False):
        return
    plugin = config.pluginmanager.get_plugin("_cov")
    if plugin is not None:
        plugin._disabled = True
        config.option.no_cov = True
        config.option.no_cov_should_warn = False


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def old_csv() -> Path:
    return FIXTURES / "old.csv"


@pytest.fixture
def new_csv() -> Path:
    return FIXTURES / "new.csv"


@pytest.fixture
def old_parquet() -> Path:
    return FIXTURES / "old.parquet"


@pytest.fixture
def new_parquet() -> Path:
    return FIXTURES / "new.parquet"


@pytest.fixture
def old_json() -> Path:
    return FIXTURES / "old.json"


@pytest.fixture
def new_json() -> Path:
    return FIXTURES / "new.json"
