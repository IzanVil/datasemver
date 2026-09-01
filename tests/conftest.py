from pathlib import Path

import pytest

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
