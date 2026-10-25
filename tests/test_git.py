"""Git working-tree and commit-range checks."""

from pathlib import Path

from tests.conftest import git_commit, git_init, run_text


def _repo(tmp_path: Path) -> None:
    git_init(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    git_commit(tmp_path, "init")


def test_dirty_true_and_false(tmp_path: Path) -> None:
    _repo(tmp_path)
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: clean
    type: git
    dirty: false
""",
    )
    assert report.ok, report.checks[0].message

    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: src-only
    type: git
    paths: [a.txt]
    dirty: true
  - name: other
    type: git
    paths: [missing.txt]
    dirty: true
""",
    )
    assert report.checks[0].ok
    assert "1 changed path" in report.checks[0].message
    assert not report.checks[1].ok
    assert "no changes" in report.checks[1].message


def test_untracked_files_and_renames(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "new.txt").write_text("new", encoding="utf-8")
    ignored = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: tracked-only
    type: git
    dirty: true
    include_untracked: false
""",
    )
    assert not ignored.ok
    included = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: any\n    type: git\n    dirty: true\n",
    )
    assert included.ok

    git_commit(tmp_path, "add new")
    # Rename so porcelain -z emits two paths.
    import subprocess

    subprocess.run(["git", "mv", "a.txt", "b.txt"], cwd=tmp_path, check=True, capture_output=True)
    renamed = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: moved\n    type: git\n    dirty: true\n",
    )
    assert renamed.ok, renamed.checks[0].message
    assert "b.txt" in renamed.checks[0].message


def test_commits_since_ref(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    git_commit(tmp_path, "add b")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: moved
    type: git
    since: HEAD~1
    min_commits: 1
  - name: touched-b
    type: git
    since: HEAD~1
    paths: [b.txt]
    min_commits: 1
  - name: touched-a
    type: git
    since: HEAD~1
    paths: [a.txt]
    min_commits: 1
  - name: same-commit
    type: git
    since: HEAD
    min_commits: 1
""",
    )
    assert report.checks[0].ok
    assert report.checks[1].ok
    assert not report.checks[2].ok
    assert "0 commits" in report.checks[2].message
    assert not report.checks[3].ok


def test_missing_repo_and_missing_ref(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: git\n    type: git\n    dirty: true\n",
    )
    assert not report.ok
    assert "not inside a git repository" in report.checks[0].message

    _repo(tmp_path)
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: base\n    type: git\n    since: does-not-exist\n",
    )
    assert "was not found" in report.checks[0].message


def test_directory_in_diff(tmp_path: Path) -> None:
    git_init(tmp_path)
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text("print(1)\n", encoding="utf-8")
    git_commit(tmp_path, "init")
    (source / "app.py").write_text("print(2)\n", encoding="utf-8")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: src changed
    type: file
    path: src
    in_diff: true
""",
    )
    assert report.ok, report.checks[0].message
