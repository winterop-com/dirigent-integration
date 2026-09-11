"""The control center's own contribution: the cross-boundary example shelves.

This distribution contributes no blocks and no connection kinds. Every block its documents
name comes from a pack the integration assembles; what is only ever authored here is the
document that puts two packs in one flow, and this is how that corpus reaches an instance.
"""

from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable

from dirigent_plugin import extension

#: The directory the cross-boundary shelves live in, inside this distribution.
SHELVES_DIRECTORY = "shelves"


class IntegrationPlugin:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def examples(self) -> Sequence[Traversable]:
        """Contribute the cross-boundary shelves this distribution carries, and nothing else."""
        return [files(__package__ or "dirigent_integration") / SHELVES_DIRECTORY]


plugin = IntegrationPlugin()

__all__ = ["SHELVES_DIRECTORY", "IntegrationPlugin", "plugin"]
