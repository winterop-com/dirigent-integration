"""The runner reads each pack's manifest entry, and installs only the dev dependencies it lacks.

The rule is what the environment holds, not what a name looks like: a pack's client library is
skipped because the pack brought it, not because of the prefix it happens to carry.
"""

from run_integration import CHECKOUTS, Component, missing_dev_dependencies, packs


def test_a_pack_naming_no_examples_reads_its_examples_directory():
    pack = Component("somepack", "https://example.invalid/somepack", "main")
    assert pack.examples == [CHECKOUTS / "somepack" / "examples"]
    assert pack.pytest_args == []


def test_the_manifest_runs_contrib_without_its_live_tests_and_reads_both_shelves():
    contrib = next(pack for pack in packs() if pack.name == "dirigent-contrib")
    assert contrib.pytest_args == ["-m", "not live"]
    assert contrib.examples == [
        CHECKOUTS / "dirigent-contrib" / "src" / "dirigent_contrib" / "chap" / "shelves",
        CHECKOUTS / "dirigent-contrib" / "src" / "dirigent_contrib" / "climate" / "shelves",
    ]


def test_a_present_distribution_is_skipped_whatever_its_prefix():
    dev = ["dhis2w-client>=1.14", "dirigent-testing==0.21.0", "httpx2>=0.1", "pytest>=8"]
    present = {"dhis2w-client", "dirigent-testing", "httpx2", "pytest"}
    assert missing_dev_dependencies(dev, present) == []


def test_an_absent_dependency_is_installed_verbatim():
    assert missing_dev_dependencies(["mkdocs>=1.6.1", "pytest>=8"], {"pytest"}) == ["mkdocs>=1.6.1"]


def test_a_client_the_environment_lacks_is_installed():
    assert missing_dev_dependencies(["otherpack-client>=2"], {"pytest"}) == ["otherpack-client>=2"]


def test_the_pack_order_is_kept():
    dev = ["mypy>=1.19", "pytest>=8", "ruff>=0.16"]
    assert missing_dev_dependencies(dev, {"pytest"}) == ["mypy>=1.19", "ruff>=0.16"]


def test_a_marker_for_another_platform_is_skipped():
    dev = ['pywin32>=306; sys_platform == "win32-not-this-one"']
    assert missing_dev_dependencies(dev, set()) == []


def test_a_marker_this_interpreter_satisfies_is_kept():
    dev = ['mkdocs>=1.6.1; python_version >= "3.13"']
    assert missing_dev_dependencies(dev, set()) == dev


def test_a_non_string_entry_is_skipped():
    dev = [{"include-group": "docs"}, 42, None, "mkdocs>=1.6.1"]
    assert missing_dev_dependencies(dev, set()) == ["mkdocs>=1.6.1"]


def test_an_unparseable_entry_is_skipped():
    assert missing_dev_dependencies(["not a requirement!!", "mkdocs>=1.6.1"], set()) == ["mkdocs>=1.6.1"]


def test_names_compare_canonically():
    assert missing_dev_dependencies(["Foo_Bar>=1"], {"foo-bar"}) == []
    assert missing_dev_dependencies(["foo-bar>=1"], {"Foo_Bar"}) == []
    assert missing_dev_dependencies(["foo.bar>=1"], {"FOO-BAR"}) == []


def test_an_extra_does_not_hide_a_present_name():
    assert missing_dev_dependencies(["pytest[testing]>=8"], {"pytest"}) == []
