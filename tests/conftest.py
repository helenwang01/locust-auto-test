from __future__ import annotations

import pytest

from loadtests.common.config_center import LoadtestConfigCenter
from utils.rest_client import RestClient


@pytest.fixture(scope="module")
def config_center() -> LoadtestConfigCenter:
    return LoadtestConfigCenter.get()


@pytest.fixture(scope="module")
def data_seed_config(config_center: LoadtestConfigCenter):
    return config_center.data_seed_config()


@pytest.fixture(scope="module")
def rest_client(config_center: LoadtestConfigCenter) -> RestClient:
    return RestClient.from_config(config_center.cfg)
