import pytest

from agent_dashboard.api import create_app
from agent_dashboard.db import Database


@pytest.fixture
def database():
    return Database()


@pytest.fixture
def app(database):
    return create_app(database)
