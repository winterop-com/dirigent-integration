"""Shared fixtures: the assembled plugin host and its merged catalog, built once per session."""

import sys
from pathlib import Path

import pytest
from dirigent_client.schemas.catalog import Catalog
from dirigent_core.plugins import PluginHost, load_plugin_host

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_EXAMPLES = ROOT / "examples"

# The runner is the integration's own code and the tests check the same validation it runs.
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session")
def host() -> PluginHost:
    """The plugin host with every installed pack discovered and contributed once."""
    return load_plugin_host()


@pytest.fixture(scope="session")
def catalog(host: PluginHost) -> Catalog:
    """The merged catalog the assembled environment serves."""
    return host.catalog()
