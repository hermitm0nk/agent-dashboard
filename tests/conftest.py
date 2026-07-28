import pytest
import os

os.environ.setdefault("AGENT_DASHBOARD_DB", ":memory:")
from agent_dashboard.api import create_app
from agent_dashboard.db import Database


@pytest.fixture
def database():
    return Database(":memory:")


@pytest.fixture
def app(database):
    return create_app(database)
