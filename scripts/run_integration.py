"""The integration runner: assemble the ecosystem and run everyone together.

Reading ecosystem.yaml, this clones each pack repository at its tracked ref into checkouts/,
then, against the one assembled environment where the dirigent runtime and every pack are
installed together, it:

  b. runs each pack's own pytest suite;
  c. validates each pack's own examples, and the bodies they carry, against the merged catalog;
  d. validates the integration's own cross-boundary examples against the merged catalog;
  e. runs the integration's own tests;
  f. asks every DHIS2 play demo an example names whether it still answers;
  g. checks each of those demos against the public instance list, so a superseded one is
     named before it is retired;
  h. rehearses an export and a dry-run import against the newest demo of each targeted
     DHIS2 version.

It reports one green or red. A pack repository whose checkout already exists is moved to its
ref's tip; one with local changes is left where it is, which is what lets a local, offline
verification substitute a copy of a sibling working tree for a clone.

`--clone-only` clones the runtime component as well, which is where `make ui` builds the web
bundle from; no suite reads it, so a full run never clones it.
"""

from __future__ import annotations

import argparse
import base64
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

if TYPE_CHECKING:
    from dirigent_core.plugins import PluginHost

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ecosystem.yaml"
CHECKOUTS = ROOT / "checkouts"
INTEGRATION_EXAMPLES = ROOT / "src" / "dirigent_integration" / "shelves"
INTEGRATION_TESTS = ROOT / "tests"

#: The hosts DHIS2 serves its public play demos from, which retire a version without notice.
PLAY_HOSTS = frozenset({"play.im.dhis2.org", "play.dhis2.org"})

#: How long one play demo is given to answer.
PLAY_TIMEOUT_SECONDS = 30

#: The DHIS2 Instance Manager's list of the public instances, the play demos among them.
PUBLIC_INSTANCES = "https://api.im.dhis2.org/instances/public"

#: The DHIS2 versions the packs are built for, each followed at its newest stable play demo.
DHIS2_TARGETS = ("2.42", "2.43")

#: A stable play demo's name: the version it serves, patch included.
STABLE_DEMO = re.compile(r"^stable-(\d+)-(\d+)-(\d+)$")

#: A play demo address in a document, which a rehearsal points at its target instead.
PLAY_ADDRESS = re.compile(r"https://play\.im\.dhis2\.org/stable-\d+-\d+-\d+")

#: The example a rehearsal runs: an export, then the same values imported as a dry run.
REHEARSAL = "dhis2-rehearse-import.yaml"

#: The play demos' full-access account, which holds the root org unit on every version.
REHEARSAL_ACCOUNT = ("system", "System123")

#: How long one rehearsal run may take.
REHEARSAL_TIMEOUT_SECONDS = 300


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


def missing_dev_dependencies(dev: list[Any], present: set[str]) -> list[str]:
    """The entries of a dev group naming a distribution `present` does not hold, in its order.

    Names compare canonically. An entry that is not a plain string, that is not a requirement,
    or whose marker the running interpreter does not satisfy, names nothing to install here.
    """
    held = {canonicalize_name(name) for name in present}
    wanted: list[str] = []
    for entry in dev:
        if not isinstance(entry, str):
            continue
        try:
            requirement = Requirement(entry)
        except InvalidRequirement:
            continue
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        if canonicalize_name(requirement.name) in held:
            continue
        wanted.append(entry)
    return wanted


def installed_distributions() -> set[str]:
    """The canonical name of every distribution the running environment provides."""
    return {canonicalize_name(dist.name) for dist in importlib.metadata.distributions() if dist.name}


def install_pack_test_deps(pack: Component) -> None:
    """Install what the assembled environment lacks of a cloned pack's dev dependencies.

    A pack's tests import dev tools the ecosystem installs the pack without. An entry naming a
    distribution the environment already holds is skipped, so the pack's own runtime
    dependencies, its client library among them, every dirigent package, and the test tools this
    repository's dev group carries stay as assembled, never reinstalled from an index.
    """
    config = pack.path / "pyproject.toml"
    if not config.exists():
        return
    dev = tomllib.loads(config.read_text()).get("dependency-groups", {}).get("dev", [])
    wanted = missing_dev_dependencies(dev, installed_distributions())
    held = [entry for entry in dev if isinstance(entry, str) and entry not in wanted]
    installing = ", ".join(wanted) if wanted else "nothing"
    print(f"  deps    {pack.name}: installing {installing}; present already: {', '.join(held) or 'none'}")
    if not wanted:
        return
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


class PlayDemo:
    """One play demo address, the credentials an example signs in with, and who names it."""

    def __init__(self, base_url: str, username: str | None, password: str | None) -> None:
        """Bind an address to the first credentials an example gave for it."""
        self.base_url = base_url
        self.username = username
        self.password = password
        self.named_by: list[Path] = []


def play_demos(directories: list[Path]) -> dict[str, PlayDemo]:
    """Every play demo a carried ``dhis2`` connection points at, keyed by its address."""
    demos: dict[str, PlayDemo] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in example_documents(directory):
            definition = yaml.safe_load(path.read_text()) or {}
            connections = definition.get("connections") if isinstance(definition, dict) else None
            for connection in (connections or {}).values():
                if not isinstance(connection, dict) or connection.get("kind") != "dhis2":
                    continue
                config = connection.get("config") or {}
                base_url = config.get("base_url")
                if not isinstance(base_url, str) or urlsplit(base_url).hostname not in PLAY_HOSTS:
                    continue
                base_url = base_url.rstrip("/")
                demo = demos.setdefault(
                    base_url, PlayDemo(base_url, config.get("basic_username"), config.get("basic_password"))
                )
                if path not in demo.named_by:
                    demo.named_by.append(path)
    return demos


def demo_status(demo: PlayDemo) -> int | str:
    """The status a play demo's system info answers with, or why nothing answered."""
    request = urllib.request.Request(f"{demo.base_url}/api/system/info")
    if demo.username and demo.password:
        token = base64.b64encode(f"{demo.username}:{demo.password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=PLAY_TIMEOUT_SECONDS) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, TimeoutError) as error:
        return str(getattr(error, "reason", error))


def check_play_demos(directories: list[Path], status: Callable[[PlayDemo], int | str] = demo_status) -> bool:
    """Ask every play demo the examples name for its system info; any answer but 200 fails."""
    print("\n=== play demos the examples name ===")
    demos = play_demos(directories)
    if not demos:
        print("  (no example names a play demo)")
        return True
    ok = True
    for demo in demos.values():
        answer = status(demo)
        if answer == 200:
            print(f"  ok       {demo.base_url}  ({len(demo.named_by)} examples)")
            continue
        ok = False
        print(f"  gone     {demo.base_url}  answered {answer}, named by:")
        for path in demo.named_by:
            print(f"    - {path.relative_to(ROOT) if ROOT in path.parents else path}")
    return ok


def stable_demos(listing: Any) -> dict[str, tuple[int, str]]:
    """Index the public instance list's stable demos by version, keeping the newest patch of each."""
    newest: dict[str, tuple[int, str]] = {}
    groups = listing if isinstance(listing, list) else []
    for group in groups:
        for category in (group or {}).get("categories") or []:
            for instance in (category or {}).get("instances") or []:
                found = STABLE_DEMO.match(str((instance or {}).get("name", "")))
                hostname = (instance or {}).get("hostname")
                if found is None or not isinstance(hostname, str):
                    continue
                version, patch = f"{found.group(1)}.{found.group(2)}", int(found.group(3))
                if version not in newest or patch > newest[version][0]:
                    newest[version] = (patch, hostname.rstrip("/"))
    return newest


def public_instances() -> Any:
    """Read the public instance list, or None when it cannot be read."""
    try:
        with urllib.request.urlopen(PUBLIC_INSTANCES, timeout=PLAY_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        print(f"  unread   {PUBLIC_INSTANCES}: {getattr(error, 'reason', error)}")
        return None


def check_demos_current(directories: list[Path], listing: Any) -> bool:
    """Fail on a stable demo an example names that a newer patch of its version has superseded.

    A demo is retired when its version's next patch is published, so the example has a day or
    so before its address stops answering; this is where that day starts. Every targeted
    version has to be listed too, or there is nothing to move to.
    """
    print("\n=== play demos against the public instance list ===")
    newest = stable_demos(listing)
    if not newest:
        print("  (the public instance list named no stable demo)")
        return False
    ok = True
    for version in DHIS2_TARGETS:
        if version not in newest:
            ok = False
            print(f"  missing  no stable {version} demo is listed")
    for demo in play_demos(directories).values():
        found = STABLE_DEMO.match(urlsplit(demo.base_url).path.strip("/"))
        if found is None:
            continue
        version, patch = f"{found.group(1)}.{found.group(2)}", int(found.group(3))
        if version not in newest:
            ok = False
            print(f"  unlisted {demo.base_url}: no stable {version} demo is listed any more")
        elif patch < newest[version][0]:
            ok = False
            print(f"  behind   {demo.base_url}: {newest[version][1]} has superseded it, named by:")
            for path in demo.named_by:
                print(f"    - {path.relative_to(ROOT) if ROOT in path.parents else path}")
        else:
            print(f"  current  {demo.base_url}")
    return ok


class Rehearsal:
    """What one rehearsal run said: whether it succeeded, how many values it exported, and the import's verdict."""

    def __init__(self, succeeded: bool, exported: int, status: str | None, conflicts: int | None) -> None:
        """Bind what the run's records said."""
        self.succeeded = succeeded
        self.exported = exported
        self.status = status
        self.conflicts = conflicts

    @property
    def passed(self) -> bool:
        """Report whether the round trip moved values and the instance took them cleanly."""
        return self.succeeded and self.exported > 0 and self.status == "SUCCESS" and self.conflicts == 0


def read_rehearsal(stream: str) -> Rehearsal:
    """Read a rehearsal run's NDJSON records into what it said."""
    succeeded, exported, status, conflicts = False, 0, None, None
    for line in stream.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("kind") == "log" and record.get("message") == "import summary":
            fields = record.get("fields") or {}
            status, conflicts = fields.get("status"), fields.get("conflict_count")
        if record.get("kind") == "run" and record.get("message") in ("succeeded", "failed"):
            succeeded = record["message"] == "succeeded"
            for step in record.get("steps") or []:
                body = ((step or {}).get("output") or {}).get("body")
                if isinstance(body, dict) and isinstance(body.get("dataValues"), list):
                    exported = max(exported, len(body["dataValues"]))
    return Rehearsal(succeeded, exported, status, conflicts)


def rehearse(document: str, hostname: str) -> Rehearsal:
    """Run the rehearsal document against one play demo, as the full-access account."""
    username, password = REHEARSAL_ACCOUNT
    pointed = PLAY_ADDRESS.sub(hostname, document)
    pointed = re.sub(r"basic_username: \S+", f"basic_username: {username}", pointed)
    pointed = re.sub(r"basic_password: \S+", f"basic_password: {password}", pointed)
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / REHEARSAL
        path.write_text(pointed)
        try:
            finished = subprocess.run(
                [str(Path(sys.executable).parent / "dg"), "--json", "run", "--local", str(path)],
                cwd=scratch,
                capture_output=True,
                text=True,
                timeout=REHEARSAL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return Rehearsal(False, 0, None, None)
    return read_rehearsal(finished.stdout)


def rehearse_targets(directories: list[Path], listing: Any, run: Callable[[str, str], Rehearsal] = rehearse) -> bool:
    """Export and dry-run import against the newest stable demo of every targeted DHIS2 version."""
    print("\n=== rehearsals against the targeted DHIS2 versions ===")
    found = [path for directory in directories if directory.is_dir() for path in directory.rglob(REHEARSAL)]
    if not found:
        print(f"  (no example is called {REHEARSAL})")
        return False
    document = found[0].read_text()
    newest = stable_demos(listing)
    ok = True
    for version in DHIS2_TARGETS:
        if version not in newest:
            ok = False
            print(f"  missing  {version}: no stable demo to rehearse against")
            continue
        hostname = newest[version][1]
        result = run(document, hostname)
        verdict = "ok      " if result.passed else "failed  "
        ok = ok and result.passed
        print(
            f"  {verdict} {version} {hostname}: run {'succeeded' if result.succeeded else 'failed'}, "
            f"{result.exported} values exported, import {result.status} with {result.conflicts} conflicts"
        )
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

    every_example = [pack.examples for pack in the_packs] + [INTEGRATION_EXAMPLES]
    results["play demos"] = check_play_demos(every_example)
    listing = public_instances()
    results["play demos current"] = check_demos_current(every_example, listing)
    results["rehearsals on 2.42 and 2.43"] = rehearse_targets([pack.examples for pack in the_packs], listing)

    print("\n=== integration summary ===")
    for name, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    every = all(results.values())
    print(f"\n{'GREEN: the ecosystem is coherent.' if every else 'RED: something above failed.'}")
    return 0 if every else 1


if __name__ == "__main__":
    raise SystemExit(main())
