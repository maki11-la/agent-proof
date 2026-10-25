"""File existence, content, mtime, globs, and git diff membership."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.conftest import git_commit, git_init, run_text


def test_exists_contains_regex_and_size(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Install with pipx install agent-proof\n", encoding="utf-8")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: readme
    type: file
    path: README.md
    min_bytes: 10
    contains: "pipx install"
    matches: "agent-proof$"
    not_contains: "TODO"
""",
    )
    assert report.ok
    assert "contains" in report.checks[0].message
    assert "matches" in report.checks[0].message


def test_missing_file_and_unexpected_file(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: missing\n    type: file\n    path: README.md\n",
    )
    assert not report.ok
    assert report.checks[0].message == "README.md does not exist"

    (tmp_path / "scratch.tmp").write_text("x", encoding="utf-8")
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: scratch\n    type: file\n    path: scratch.tmp\n    exists: false\n",
    )
    assert report.checks[0].message == "scratch.tmp exists"


def test_glob_min_and_max(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (source / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: sources
    type: file
    glob: src/*.py
    min_matches: 2
    max_matches: 2
    contains: "def "
""",
    )
    assert report.ok
    assert "2 files matched src/*.py" in report.checks[0].message

    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: none\n    type: file\n    glob: src/*.md\n",
    )
    assert not report.ok
    assert "0 files matched" in report.checks[0].message


def test_glob_must_not_match(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: no-logs\n    type: file\n    glob: '*.log'\n    exists: false\n",
    )
    assert report.ok
    (tmp_path / "debug.log").write_text("x", encoding="utf-8")
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: no-logs\n    type: file\n    glob: '*.log'\n    exists: false\n",
    )
    assert not report.ok
    assert "debug.log" in report.checks[0].message


def test_modified_after_and_within(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"
    path.write_text("fresh", encoding="utf-8")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: recent
    type: file
    path: out.txt
    modified_after: 2020-01-01
    modified_within: 1h
""",
    )
    assert report.ok, report.checks[0].message

    old = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp()
    os.utime(path, (old, old))
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: recent\n    type: file\n    path: out.txt\n    modified_within: 1h\n",
    )
    assert not report.ok
    assert "expected within 1h" in report.checks[0].message


def test_binary_file_is_rejected_for_text_checks(tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe hello")
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: blob\n    type: file\n    path: blob.bin\n    contains: hello\n",
    )
    assert "UTF-8" in report.checks[0].message


def test_in_diff_for_new_changed_and_deleted_files(tmp_path: Path) -> None:
    git_init(tmp_path)
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")
    git_commit(tmp_path, "init")
    (tmp_path / "keep.txt").write_text("keep\nedited\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new", encoding="utf-8")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: edited
    type: file
    path: keep.txt
    in_diff: true
  - name: created
    type: file
    path: new.txt
    in_diff: true
    include_untracked: true
  - name: untouched-would-fail
    type: file
    path: keep.txt
    in_diff: false
""",
    )
    assert report.checks[0].ok
    assert report.checks[1].ok
    assert not report.checks[2].ok
    assert "is in the git diff" in report.checks[2].message

    git_commit(tmp_path, "add new")
    tracked = tmp_path / "gone.txt"
    tracked.write_text("bye", encoding="utf-8")
    git_commit(tmp_path, "add gone")
    tracked.unlink()
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: deleted
    type: file
    path: gone.txt
    exists: false
    in_diff: true
""",
    )
    assert report.ok, report.checks[0].message
    assert "does not exist and is in the git diff" in report.checks[0].message
