"""Pytest configuration."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests that hit real exchange APIs"
    )
