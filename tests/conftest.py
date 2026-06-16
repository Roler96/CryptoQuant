"""Pytest configuration."""
import pytest

from cryptoquant.execution.mock_broker import MockBroker


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests that hit real exchange APIs"
    )


@pytest.fixture
def mock_broker():
    return MockBroker()
