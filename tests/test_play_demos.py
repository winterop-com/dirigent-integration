"""The runner asks each play demo the examples name whether it still answers, once per address."""

from pathlib import Path
from typing import Any

import yaml

from run_integration import (
    DHIS2_TARGETS,
    PLAY_BASE_URL,
    PLAY_CONNECTION,
    REHEARSAL_ACCOUNT,
    PlayDemo,
    Rehearsal,
    check_demos_current,
    check_play_demos,
    play_connections,
    play_demos,
    read_rehearsal,
    rehearse_targets,
    stable_demos,
)


def write(directory: Path, name: str, base_url: str, kind: str = "dhis2") -> Path:
    """Write a pipeline document carrying one connection without a credential."""
    path = directory / name
    path.write_text(
        f"""code: {path.stem}
connections:
  demo:
    kind: {kind}
    config:
      base_url: {base_url}
steps: {{}}
"""
    )
    return path


def name_play(directory: Path, name: str) -> Path:
    """Write a pipeline document naming the play connection under requires."""
    path = directory / name
    path.write_text(f"code: {path.stem}\nrequires:\n  connections: [{PLAY_CONNECTION}]\nsteps: {{}}\n")
    return path


def test_an_address_named_twice_is_one_demo(tmp_path: Path) -> None:
    first = write(tmp_path, "a.yaml", "https://play.im.dhis2.org/stable-2-43-2")
    second = write(tmp_path, "b.yaml", "https://play.im.dhis2.org/stable-2-43-2/")
    demos = play_demos([tmp_path])
    assert list(demos) == ["https://play.im.dhis2.org/stable-2-43-2"]
    assert demos["https://play.im.dhis2.org/stable-2-43-2"].named_by == [first, second]


def test_a_document_naming_the_play_connection_reaches_its_demo(tmp_path: Path) -> None:
    first = name_play(tmp_path, "a.yaml")
    second = name_play(tmp_path, "b.yaml")
    demos = play_demos([tmp_path])
    assert list(demos) == [PLAY_BASE_URL]
    assert demos[PLAY_BASE_URL].named_by == [first, second]


def test_a_rehearsal_signs_in_as_the_full_access_account_at_its_target() -> None:
    target = "https://play.im.dhis2.org/stable-2-42-7"
    connection = play_connections(target, REHEARSAL_ACCOUNT)[PLAY_CONNECTION]
    assert connection["kind"] == "dhis2"
    assert connection["config"]["base_url"] == target
    assert (connection["config"]["basic_username"], connection["config"]["basic_password"]) == REHEARSAL_ACCOUNT
    assert yaml.safe_load(yaml.safe_dump(play_connections(target))) == play_connections(target)


def test_only_dhis2_connections_on_a_play_host_are_collected(tmp_path: Path) -> None:
    write(tmp_path, "local.yaml", "http://localhost:8095")
    write(tmp_path, "fhir.yaml", "https://play.im.dhis2.org/stable-2-43-2", kind="http")
    write(tmp_path, "other.yaml", "https://hapi.fhir.org/baseR4")
    assert play_demos([tmp_path, tmp_path / "absent"]) == {}


def test_a_demo_that_answers_200_passes(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "https://play.im.dhis2.org/stable-2-43-2")
    asked: list[str] = []

    def status(demo: PlayDemo) -> int:
        asked.append(demo.base_url)
        return 200

    assert check_play_demos([tmp_path], status) is True
    assert asked == ["https://play.im.dhis2.org/stable-2-43-2"]


def test_a_retired_or_unreachable_demo_fails(tmp_path: Path) -> None:
    write(tmp_path, "gone.yaml", "https://play.im.dhis2.org/stable-2-42-6")
    assert check_play_demos([tmp_path], lambda demo: 404) is False
    assert check_play_demos([tmp_path], lambda demo: "timed out") is False


def test_no_demo_named_passes(tmp_path: Path) -> None:
    assert check_play_demos([tmp_path], lambda demo: 404) is True


#: The public instance list as the Instance Manager answers it, trimmed to what is read.
LISTING: list[dict[str, Any]] = [
    {
        "name": "play",
        "categories": [
            {
                "label": "Stable",
                "instances": [
                    {"name": "stable-2-43-2", "hostname": "https://play.im.dhis2.org/stable-2-43-2"},
                    {"name": "stable-2-42-7", "hostname": "https://play.im.dhis2.org/stable-2-42-7"},
                    {"name": "stable-2-42-6", "hostname": "https://play.im.dhis2.org/stable-2-42-6"},
                    {"name": "stable-2-41-10-1", "hostname": "https://play.im.dhis2.org/stable-2-41-10-1"},
                    {"name": "stable-2-41-10", "hostname": "https://play.im.dhis2.org/stable-2-41-10"},
                    {"name": "stable-2-41-9-3", "hostname": "https://play.im.dhis2.org/stable-2-41-9-3"},
                ],
            },
            {"label": "Under Development", "instances": [{"name": "dev-2-43", "hostname": "https://x"}]},
        ],
    }
]


def test_the_newest_patch_of_each_version_is_kept() -> None:
    assert stable_demos(LISTING) == {
        "2.43": ((2, 0), "https://play.im.dhis2.org/stable-2-43-2"),
        "2.42": ((7, 0), "https://play.im.dhis2.org/stable-2-42-7"),
        "2.41": ((10, 1), "https://play.im.dhis2.org/stable-2-41-10-1"),
    }
    assert stable_demos(None) == {}


def test_a_demo_on_its_versions_newest_patch_is_current(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "https://play.im.dhis2.org/stable-2-43-2")
    assert check_demos_current([tmp_path], LISTING) is True


def test_a_demo_a_newer_patch_superseded_fails(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "https://play.im.dhis2.org/stable-2-42-6")
    assert check_demos_current([tmp_path], LISTING) is False


def test_a_targeted_version_with_no_listed_demo_fails(tmp_path: Path) -> None:
    only_43 = [{"categories": [{"instances": [LISTING[0]["categories"][0]["instances"][0]]}]}]
    assert "2.42" in DHIS2_TARGETS
    assert check_demos_current([tmp_path], only_43) is False


def test_an_unreadable_listing_fails(tmp_path: Path) -> None:
    assert check_demos_current([tmp_path], None) is False


STREAM = "\n".join(
    [
        '{"kind": "log", "message": "import summary", "fields": {"status": "SUCCESS", "conflict_count": 0}}',
        '{"kind": "run", "message": "succeeded", "steps": [{"output": {"body": {"dataValues": [{}, {}]}}}]}',
    ]
)


def test_a_rehearsal_that_moved_values_cleanly_passes() -> None:
    result = read_rehearsal(STREAM)
    assert (result.succeeded, result.exported, result.status, result.conflicts) == (True, 2, "SUCCESS", 0)
    assert result.passed


def test_a_rehearsal_that_exported_nothing_fails() -> None:
    empty = STREAM.replace("[{}, {}]", "[]")
    assert not read_rehearsal(empty).passed


def test_every_targeted_version_is_rehearsed_against_its_newest_demo(tmp_path: Path) -> None:
    (tmp_path / "dhis2-rehearse-import.yaml").write_text("base_url: https://play.im.dhis2.org/stable-2-42-6\n")
    asked: list[str] = []

    def run(document: str, hostname: str) -> Rehearsal:
        asked.append(hostname)
        return Rehearsal(True, 16, "SUCCESS", 0)

    assert rehearse_targets([tmp_path], LISTING, run) is True
    assert asked == ["https://play.im.dhis2.org/stable-2-42-7", "https://play.im.dhis2.org/stable-2-43-2"]


def test_one_failed_rehearsal_fails_the_stage(tmp_path: Path) -> None:
    (tmp_path / "dhis2-rehearse-import.yaml").write_text("steps: {}\n")
    outcomes = iter([Rehearsal(True, 16, "SUCCESS", 0), Rehearsal(True, 0, "SUCCESS", 0)])
    assert rehearse_targets([tmp_path], LISTING, lambda document, hostname: next(outcomes)) is False
