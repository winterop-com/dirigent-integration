"""The assembled catalog is coherent, and the cross-boundary examples hold against it.

These are the integration's own tests: they assert the property no single pack can, that every
pack loads together into one catalog with no collisions, and that a pipeline spanning packs
validates against that whole.
"""

from pathlib import Path

import pytest
import yaml
from dirigent_client.schemas.catalog import Catalog
from dirigent_core.documents import load_text, validate_against_catalog
from dirigent_core.plugins import PluginHost

from run_integration import connection_body_issues

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_EXAMPLES = ROOT / "examples"

#: The blocks each pack is expected to contribute, keyed by the plugin name the pack registers
#: under, so their presence in one catalog and their attribution to the right pack are proven.
EXPECTED_BLOCKS = {
    "builtin": ["http.request", "storage.copy"],
    "parquet": ["convert.arrow"],
    "dhis2": [
        "dhis2.analytics_query",
        "dhis2.analytics_run",
        "dhis2.data_set_complete",
        "dhis2.data_value_set_export",
        "dhis2.data_value_set_import",
        "dhis2.metadata",
        "dhis2.tracker",
    ],
}

#: A storage scheme and a connection kind each pack contributes beyond blocks. The file://
#: scheme is a core built-in, registered when storage is built rather than contributed to the
#: catalog, so the only contributed scheme in the merged catalog is s3.
EXPECTED_STORAGE_SCHEMES = ["s3"]
EXPECTED_CONNECTION_KINDS = ["dhis2", "s3"]

CROSS_BOUNDARY = sorted(INTEGRATION_EXAMPLES.rglob("*.yaml"))


def test_the_host_loaded_more_than_one_plugin(host: PluginHost) -> None:
    assert len(set(host.catalog().plugins)) > 1, "the assembled host contributed fewer plugins than there are packs"


@pytest.mark.parametrize(
    "block_id",
    [block for blocks in EXPECTED_BLOCKS.values() for block in blocks],
)
def test_every_expected_block_is_in_the_merged_catalog(catalog: Catalog, block_id: str) -> None:
    assert catalog.block(block_id) is not None, f"{block_id} is missing from the merged catalog"


@pytest.mark.parametrize(
    ("plugin", "block_id"),
    [(plugin, block) for plugin, blocks in EXPECTED_BLOCKS.items() for block in blocks],
)
def test_every_expected_block_is_attributed_to_its_pack(catalog: Catalog, plugin: str, block_id: str) -> None:
    """The host refuses a colliding id at load, so what is left to prove is who owns each block."""
    entry = catalog.block(block_id)
    assert entry is not None, f"{block_id} is missing from the merged catalog"
    assert entry.plugin == plugin, f"{block_id} is attributed to {entry.plugin!r}, not {plugin!r}"


@pytest.mark.parametrize("scheme", EXPECTED_STORAGE_SCHEMES)
def test_every_expected_storage_scheme_is_present(catalog: Catalog, scheme: str) -> None:
    assert scheme in {entry.id for entry in catalog.storage_schemes}, f"the {scheme} scheme is missing"


@pytest.mark.parametrize("kind", EXPECTED_CONNECTION_KINDS)
def test_every_expected_connection_kind_is_present(catalog: Catalog, kind: str) -> None:
    assert kind in {entry.id for entry in catalog.connection_kinds}, f"the {kind} connection kind is missing"


def test_there_are_cross_boundary_examples_to_check() -> None:
    assert CROSS_BOUNDARY, "the integration authors cross-boundary examples under examples/"


@pytest.mark.parametrize("path", CROSS_BOUNDARY, ids=[str(p.relative_to(INTEGRATION_EXAMPLES)) for p in CROSS_BOUNDARY])
def test_a_cross_boundary_example_opens_with_a_comment_and_is_a_v1_pipeline(path: Path) -> None:
    text = path.read_text()
    assert text.startswith("#"), "every example opens with a comment saying what it shows"
    definition = yaml.safe_load(text)
    assert definition["format"] == "dirigent/v1"
    assert definition["kind"] == "pipeline"
    assert definition["code"] == path.stem, "a document's code should match its file name"
    assert definition["description"], "every example says what it is for"


@pytest.mark.parametrize("path", CROSS_BOUNDARY, ids=[str(p.relative_to(INTEGRATION_EXAMPLES)) for p in CROSS_BOUNDARY])
def test_a_cross_boundary_example_validates_against_the_merged_catalog(
    catalog: Catalog, host: PluginHost, path: Path
) -> None:
    definition = load_text(path.read_text())
    issues = validate_against_catalog(definition, catalog, check_blocks=True, blocks=host.blocks)
    assert not issues, f"{path.name}: " + "; ".join(str(issue) for issue in issues)


@pytest.mark.parametrize("path", CROSS_BOUNDARY, ids=[str(p.relative_to(INTEGRATION_EXAMPLES)) for p in CROSS_BOUNDARY])
def test_a_cross_boundary_example_carries_a_connection_body_its_kind_accepts(host: PluginHost, path: Path) -> None:
    definition = load_text(path.read_text())
    issues = connection_body_issues(definition, host)
    assert not issues, f"{path.name}: " + "; ".join(issues)


#: A document whose dhis2 connection spells the timeout the way the pack carried it before the
#: field became a Duration. The catalog check passes it, because it reads the connection's code
#: and never its body.
STALE_CONNECTION_BODY = """
format: dirigent/v1
kind: pipeline
code: stale-connection-body
description: A dhis2 connection carrying a field the kind no longer has.

connections:
  dhis2-demo:
    kind: dhis2
    config:
      base_url: https://play.im.dhis2.org/stable-2-43-1
      basic_username: admin
      basic_password: district
      timeout_seconds: 60

steps:
  read_org_units:
    block: dhis2.metadata
    config:
      connection: dhis2-demo
      resource: organisationUnits
"""


def test_a_stale_connection_body_passes_the_catalog_check(catalog: Catalog, host: PluginHost) -> None:
    definition = load_text(STALE_CONNECTION_BODY)
    assert not validate_against_catalog(definition, catalog, check_blocks=True, blocks=host.blocks)


def test_a_stale_connection_body_is_refused(host: PluginHost) -> None:
    definition = load_text(STALE_CONNECTION_BODY)
    issues = connection_body_issues(definition, host)
    assert issues == ["connections.dhis2-demo.config.timeout_seconds: Extra inputs are not permitted"]


def test_a_connection_of_an_uninstalled_kind_is_refused(host: PluginHost) -> None:
    definition = load_text(STALE_CONNECTION_BODY.replace("kind: dhis2\n", "kind: nowhere\n"))
    assert connection_body_issues(definition, host) == [
        "connections.dhis2-demo.kind: no installed pack contributes a 'nowhere' connection"
    ]


@pytest.mark.parametrize("path", CROSS_BOUNDARY, ids=[str(p.relative_to(INTEGRATION_EXAMPLES)) for p in CROSS_BOUNDARY])
def test_a_cross_boundary_example_spans_more_than_one_pack(catalog: Catalog, path: Path) -> None:
    definition = yaml.safe_load(path.read_text())
    used = {step["block"] for step in definition.get("steps", {}).values()}
    plugins = {catalog.block(block).plugin for block in used if catalog.block(block) is not None}
    # A pack is spanned by the connection kinds it contributes as much as by its blocks: a
    # document that reaches DHIS2 through http.request on a dhis2 connection crosses into
    # the dhis2 pack, since only that pack makes the connection exist.
    kinds = {connection.get("kind") for connection in definition.get("connections", {}).values()}
    owners = {entry.id: entry.plugin for entry in catalog.connection_kinds}
    plugins |= {owners[kind] for kind in kinds if kind in owners}
    assert len(plugins) > 1, (
        f"{path.name} names blocks and connection kinds from only {plugins}; a cross-boundary example spans packs"
    )
