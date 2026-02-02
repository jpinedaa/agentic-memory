"""Pytest configuration and shared fixtures."""

import os

import pytest
from dotenv import load_dotenv

# Load .env file for API keys
load_dotenv()

# -- Neo4j availability check (cached for the session) --

_neo4j_available: bool | None = None


def _check_neo4j() -> bool:
    """Check if Neo4j is reachable. Result is cached for the session."""
    global _neo4j_available  # noqa: PLW0603
    if _neo4j_available is not None:
        return _neo4j_available
    import socket
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    # Parse host:port from bolt://host:port
    host_port = uri.split("://", 1)[-1]
    host, _, port = host_port.partition(":")
    port = int(port) if port else 7687
    try:
        with socket.create_connection((host, port), timeout=2):
            _neo4j_available = True
    except OSError:
        _neo4j_available = False
    return _neo4j_available


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "llm: tests that require ANTHROPIC_API_KEY")
    config.addinivalue_line("markers", "slow: tests that take > 5 seconds")
    config.addinivalue_line("markers", "integration: end-to-end integration tests")


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests based on available infrastructure."""
    skip_neo4j = pytest.mark.skip(reason="Neo4j not reachable")
    skip_llm = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set")

    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_neo4j = _check_neo4j()

    for item in items:
        # Skip @pytest.mark.llm tests when no API key
        if "llm" in item.keywords and not has_api_key:
            item.add_marker(skip_llm)

        # Skip tests that use the `store` or `memory` or `system` fixtures when Neo4j is down
        fixture_names = getattr(item, "fixturenames", [])
        needs_neo4j = {"store", "memory", "system"} & set(fixture_names)
        if needs_neo4j and not has_neo4j:
            item.add_marker(skip_neo4j)


@pytest.fixture(scope="session")
def api_key():
    """Get API key or skip test."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return key
