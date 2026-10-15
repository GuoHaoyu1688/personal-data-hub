from pathlib import Path

import pytest

from personal_data_hub.core.store import Hub


@pytest.fixture
def hub(tmp_path):
    return Hub(tmp_path / "data")


@pytest.fixture
def examples():
    return Path(__file__).parents[1] / "examples"
