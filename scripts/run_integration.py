"""The integration runner: assemble the ecosystem and run everyone together.

Reading ecosystem.yaml, this clones each pack repository at its tracked ref into checkouts/,
then, against the one assembled environment where the dirigent runtime and every pack are
installed together, it:

  b. runs each pack's own pytest suite;
  c. validates each pack's own examples, and the bodies they carry, against the merged catalog;
  d. validates the integration's own cross-boundary examples against the merged catalog;
  e. runs the integration's own tests.

It reports one green or red. A pack repository whose checkout already exists is moved to its
ref's tip; one with local changes is left where it is, which is what lets a local, offline
verification substitute a copy of a sibling working tree for a clone.

`--clone-only` clones the runtime component as well, which is where `make ui` builds the web
bundle from; no suite reads it, so a full run never clones it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from dirigent_core.plugins import PluginHost

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ecosystem.yaml"
CHECKOUTS = ROOT / "checkouts"
INTEGRATION_EXAMPLES = ROOT / "src" / "dirigent_integration" / "shelves"
INTEGRATION_TESTS = ROOT / "tests"


class Component:
    """One cloned component: where its repository lives and what it contributes to run here."""

    def __init__(self, name: str, repo: str, ref: str) -> None:
        """Bind a pack's name to its repository, its tracked ref, and its checkout path."""
        self.name = name
        self.repo = repo
        self.ref = ref
        self.path = CHECKOUTS / name

    @property
    def tests(self) -> Path:
        """The pack's own test directory inside its checkout."""
        return self.path / "tests"

    @property
    def examples(self) -> Path:
        """The pack's own examples directory inside its checkout."""
        return self.path / "examples"


def components(role: str) -> list[Component]:
    """Read the manifest and return the components in one role, in the order it names them."""
    manifest = yaml.safe_load(MANIFEST.read_text())
    return [
        Component(name, entry["repo"], entry["ref"])
        for name, entry in manifest["components"].items()
        if entry.get("role") == role
    ]


def packs() -> list[Component]:
    """The components that are cloned and self-tested here."""
    return components("pack")


def clone(pack: Component) -> None:
    """Clone a pack at its ref, or bring a checkout that is already there up to that ref.

    The pack's source is installed from the ref's tip, so the tests must be read from the same
    tip: a checkout left at an older commit runs one commit's tests against another's code.
    A checkout with local changes is left alone and reported, never reset.
    """
    if pack.path.exists():
        dirty = subprocess.run(
            ["git", "-C", str(pack.path), "status", "--porcelain"], check=True, capture_output=True, text=True
        ).stdout.strip()
        if dirty:
            print(f"  keep    {pack.name}  (checkout has local changes; not moved to {pack.ref})")
            return
        print(f"  refresh {pack.name}  {pack.repo}@{pack.ref}")
        subprocess.run(["git", "-C", str(pack.path), "fetch", "--depth", "1", "origin", pack.ref], check=True)
        subprocess.run(["git", "-C", str(pack.path), "reset", "--hard", "FETCH_HEAD"], check=True)
        return
    CHECKOUTS.mkdir(exist_ok=True)
    print(f"  clone   {pack.name}  {pack.repo}@{pack.ref}")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", pack.ref, pack.repo, str(pack.path)],
        check=True,
    )


def install_pack_test_deps(pack: Component) -> None:
    """Install a cloned pack's non-workspace dev dependencies into the assembled environment.

    A pack's tests import its own dev tools (respx, pytest plugins) that the ecosystem
    installs the pack without. The workspace deps (dirigent-*, dhis2w-*) are already present;
    only the third-party ones from the pack's dev group need adding.
    """
    config = pack.path / "pyproject.toml"
    if not config.exists():
        return
    dev = tomllib.loads(config.read_text()).get("dependency-groups", {}).get("dev", [])
    wanted = [d for d in dev if isinstance(d, str) and not d.startswith(("dirigent-", "dhis2w-"))]
    if not wanted:
        return
    print(f"  deps    {pack.name}: {', '.join(wanted)}")
    subprocess.run(["uv", "pip", "install", *wanted], check=True)


def run_pack_tests(pack: Component) -> bool:
    """Run one pack's own pytest suite against the assembled environment."""
    if not pack.tests.is_dir():
        print(f"  skip    {pack.name}: no tests/ directory")
        return True
    install_pack_test_deps(pack)
    config = pack.path / "pyproject.toml"
    argv = ["pytest", str(pack.tests)]
    if config.exists():
        argv += ["-c", str(config)]
    print(f"\n=== pytest: {pack.name} ===")
    return subprocess.run([sys.executable, "-m", *argv]).returncode == 0


def example_documents(directory: Path) -> list[Path]:
    """Every pipeline document under a directory, in a stable order."""
    return sorted(directory.rglob("*.yaml"))


def referenced_connections(path: Path) -> set[str]:
    """Every connection code a document names, whether it carries it or expects the instance to.

    A pack example may reference an instance-level connection it does not declare. The merged
    catalog is about the blocks and kinds each pack contributes, not about what connections an
    instance holds, so a check against the catalog treats a named connection as satisfied.
    """
    definition = yaml.safe_load(path.read_text()) or {}
    codes = set(definition.get("connections", {}))
    codes |= set(definition.get("requires", {}).get("connections", []))
    for step in definition.get("steps", {}).values():
        code = step.get("config", {}).get("connection")
        if isinstance(code, str):
            codes.add(code)
    return codes


def connection_body_issues(definition: Any, host: PluginHost) -> list[str]:
    """Every problem in the config body of a connection the document carries.

    The catalog check reads a connection's code and stops there, so a body carrying a field its
    kind no longer has passes it and is refused only when a block resolves the connection mid-run.
    A kind's config model forbids an unknown key, so validating a carried body against it here is
    the refusal an apply makes, at the time the document is checked.
    """
    from pydantic import ValidationError

    issues: list[str] = []
    for code, connection in getattr(definition, "connections", {}).items():
        kind = host.connection_kinds.get(connection.kind)
        if kind is None:
            issues.append(f"connections.{code}.kind: no installed pack contributes a {connection.kind!r} connection")
            continue
        try:
            kind.config_model.model_validate(connection.config)
        except ValidationError as error:
            for problem in error.errors():
                field = ".".join(str(part) for part in problem["loc"])
                where = f"connections.{code}.config.{field}" if field else f"connections.{code}.config"
                issues.append(f"{where}: {problem['msg']}")
    return issues


def validate_examples(label: str, directories: list[Path]) -> bool:
    """Structurally validate a set of example directories against the merged catalog.

    The integration may import dirigent-core to do this; a pack, which must not know the whole
    ecosystem, cannot. That asymmetry is the point: only here is every pack loaded at once.

    A carried connection's config body is checked against its kind's own model as well, which
    the catalog check does not read.
    """
    from dirigent_client.schemas.catalog import Catalog
    from dirigent_core.documents import DocumentError, load_text, validate_against_catalog
    from dirigent_core.plugins import load_plugin_host

    host = load_plugin_host()
    catalog: Catalog = host.catalog()
    blocks = host.blocks

    print(f"\n=== validate examples: {label} ===")
    documents = [path for directory in directories if directory.is_dir() for path in example_documents(directory)]
    if not documents:
        print("  (no example documents found)")
        return True

    ok = True
    for path in documents:
        rel = path.relative_to(ROOT) if ROOT in path.parents else path
        try:
            definition = load_text(path.read_text())
        except DocumentError as error:
            ok = False
            print(f"  invalid  {rel}")
            for problem in error.problems:
                print(f"    - {problem}")
            continue
        issues = validate_against_catalog(
            definition,
            catalog,
            connections=referenced_connections(path),
            check_blocks=True,
            blocks=blocks,
        )
        problems = [str(issue) for issue in issues] + connection_body_issues(definition, host)
        if problems:
            ok = False
            print(f"  invalid  {rel}")
            for problem in problems:
                print(f"    - {problem}")
        else:
            print(f"  ok       {rel}")
    return ok


def run_integration_tests() -> bool:
    """Run the integration's own pytest suite."""
    print("\n=== pytest: dirigent-integration ===")
    return subprocess.run([sys.executable, "-m", "pytest", str(INTEGRATION_TESTS)]).returncode == 0


def main() -> int:
    """Assemble the ecosystem and run every suite, returning a shell exit code."""
    parser = argparse.ArgumentParser(description="Assemble and run the dirigent ecosystem.")
    parser.add_argument(
        "--clone-only",
        action="store_true",
        help="Clone every component named in the manifest, the runtime included, and stop.",
    )
    args = parser.parse_args()

    the_packs = packs()

    print("=== assemble: clone the packs named in ecosystem.yaml ===")
    for pack in the_packs:
        clone(pack)
    if args.clone_only:
        # The runtime is installed from git, so a checkout of it is only ever wanted for the
        # web bundle `make ui` builds there; the suites never read it, and a run without
        # --clone-only leaves it alone.
        for runtime in components("runtime"):
            clone(runtime)
        return 0

    results: dict[str, bool] = {}

    for pack in the_packs:
        results[f"{pack.name} tests"] = run_pack_tests(pack)

    for pack in the_packs:
        results[f"{pack.name} examples"] = validate_examples(pack.name, [pack.examples])

    results["cross-boundary examples"] = validate_examples("cross-boundary", [INTEGRATION_EXAMPLES])

    results["integration tests"] = run_integration_tests()

    print("\n=== integration summary ===")
    for name, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    every = all(results.values())
    print(f"\n{'GREEN: the ecosystem is coherent.' if every else 'RED: something above failed.'}")
    return 0 if every else 1


if __name__ == "__main__":
    raise SystemExit(main())
