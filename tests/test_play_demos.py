"""The runner asks each play demo the examples name whether it still answers, once per address."""

from pathlib import Path

from run_integration import PlayDemo, check_play_demos, play_demos


def write(directory: Path, name: str, base_url: str, kind: str = "dhis2") -> Path:
    """Write a pipeline document carrying one connection."""
    path = directory / name
    path.write_text(
        f"""code: {path.stem}
connections:
  demo:
    kind: {kind}
    config:
      base_url: {base_url}
      basic_username: admin
      basic_password: district
steps: {{}}
"""
    )
    return path


def test_an_address_named_twice_is_one_demo(tmp_path: Path) -> None:
    first = write(tmp_path, "a.yaml", "https://play.im.dhis2.org/stable-2-42-7")
    second = write(tmp_path, "b.yaml", "https://play.im.dhis2.org/stable-2-42-7/")
    demos = play_demos([tmp_path])
    assert list(demos) == ["https://play.im.dhis2.org/stable-2-42-7"]
    demo = demos["https://play.im.dhis2.org/stable-2-42-7"]
    assert demo.named_by == [first, second]
    assert (demo.username, demo.password) == ("admin", "district")


def test_only_dhis2_connections_on_a_play_host_are_collected(tmp_path: Path) -> None:
    write(tmp_path, "local.yaml", "http://localhost:8095")
    write(tmp_path, "fhir.yaml", "https://play.im.dhis2.org/stable-2-42-7", kind="http")
    write(tmp_path, "other.yaml", "https://hapi.fhir.org/baseR4")
    assert play_demos([tmp_path, tmp_path / "absent"]) == {}


def test_a_demo_that_answers_200_passes(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", "https://play.im.dhis2.org/stable-2-42-7")
    asked: list[str] = []

    def status(demo: PlayDemo) -> int:
        asked.append(demo.base_url)
        return 200

    assert check_play_demos([tmp_path], status) is True
    assert asked == ["https://play.im.dhis2.org/stable-2-42-7"]


def test_a_retired_or_unreachable_demo_fails(tmp_path: Path) -> None:
    write(tmp_path, "gone.yaml", "https://play.im.dhis2.org/stable-2-42-6")
    assert check_play_demos([tmp_path], lambda demo: 404) is False
    assert check_play_demos([tmp_path], lambda demo: "timed out") is False


def test_no_demo_named_passes(tmp_path: Path) -> None:
    assert check_play_demos([tmp_path], lambda demo: 404) is True
