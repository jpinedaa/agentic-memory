"""Pytest configuration and shared fixtures."""

import os

import pytest
from dotenv import load_dotenv

# Load .env file for API keys
load_dotenv()


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "llm: tests that require ANTHROPIC_API_KEY")
    config.addinivalue_line("markers", "slow: tests that take > 5 seconds")
    config.addinivalue_line("markers", "integration: end-to-end integration tests")


@pytest.fixture(scope="session")
def api_key():
    """Get API key or skip test."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return key
