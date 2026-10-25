"""Spec parsing fails closed."""

from pathlib import Path

import pytest

from agent_proof.spec import load_spec, resolve_root
from tests.conftest import spec_errors

VALID = """\
version: 1
name: demo
checks:
  - name: readme
    type: file
    path: README.md
"""


def test_valid_spec_loads(tmp_path: Path) -> None:
    path = tmp_path / "proof.yaml"
    path.write_text(VALID, encoding="utf-8")
    spec = load_spec(path)
    assert spec.version == 1
    assert spec.name == "demo"
    assert spec.checks[0].name == "readme"
    assert spec.checks[0].path == "README.md"  # type: ignore[attr-defined]


def test_rejects_wrong_version_and_empty_checks(tmp_path: Path) -> None:
    errors = spec_errors(tmp_path, "version: 2\nchecks: []\n")
    assert any("version" in item for item in errors)
    assert any("checks" in item for item in errors)


def test_rejects_unknown_field_and_duplicate_name(tmp_path: Path) -> None:
    text = """\
version: 1
checks:
  - name: one
    type: file
    path: a.txt
    paht: a.txt
  - name: one
    type: file
    path: b.txt
"""
    errors = spec_errors(tmp_path, text)
    assert any("unknown field" in item and "paht" in item for item in errors)
    assert any("duplicate" in item for item in errors)


def test_duplicate_yaml_key(tmp_path: Path) -> None:
    errors = spec_errors(tmp_path, "version: 1\nversion: 1\nchecks:\n  - name: a\n    type: file\n    path: a.txt\n")
    assert any("duplicate key" in item for item in errors)


def test_json_spec_and_duplicate_key(tmp_path: Path) -> None:
    path = tmp_path / "proof.json"
    path.write_text(
        '{"version": 1, "checks": [{"name": "a", "type": "file", "path": "a.txt"}]}',
        encoding="utf-8",
    )
    spec = load_spec(path)
    assert spec.checks[0].name == "a"
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": 1, "version": 1, "checks": []}', encoding="utf-8")
    from agent_proof.spec import SpecError

    with pytest.raises(SpecError) as caught:
        load_spec(bad)
    assert any("duplicate key" in item for item in caught.value.errors)


def test_rejects_absolute_path_and_parent_segments(tmp_path: Path) -> None:
    errors = spec_errors(
        tmp_path,
        "version: 1\nchecks:\n  - name: a\n    type: file\n    path: /etc/passwd\n"
        "  - name: b\n    type: file\n    path: ../secret\n",
    )
    assert any("relative" in item for item in errors)
    assert any(".." in item for item in errors)


def test_file_rules(tmp_path: Path) -> None:
    errors = spec_errors(
        tmp_path,
        """\
version: 1
checks:
  - name: both
    type: file
    path: a.txt
    glob: "*.txt"
  - name: neither
    type: file
  - name: gone
    type: file
    path: a.txt
    exists: false
    contains: secret
  - name: bad-re
    type: file
    path: a.txt
    matches: "("
""",
    )
    joined = "\n".join(errors)
    assert "not both" in joined
    assert "set path or glob" in joined
    assert "cannot be set when exists is false" in joined
    assert "regular expression" in joined


def test_command_and_git_rules(tmp_path: Path) -> None:
    errors = spec_errors(
        tmp_path,
        """\
version: 1
checks:
  - name: cmd
    type: command
    timeout: 0
  - name: repo
    type: git
    min_commits: 1
  - name: ref
    type: git
    since: "-evil"
""",
    )
    joined = "\n".join(errors)
    assert "run is required" in joined
    assert "timeout" in joined
    assert "set dirty, since, or both" in joined or "min_commits requires since" in joined
    assert "not a valid git ref" in joined


def test_data_path_rules(tmp_path: Path) -> None:
    errors = spec_errors(
        tmp_path,
        """\
version: 1
checks:
  - name: doc
    type: json
    equals:
      ".name": hi
""",
    )
    joined = "\n".join(errors)
    assert "path is required" in joined
    assert "invalid path" in joined


def test_root_is_relative_to_the_spec_file(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    path = nested / "proof.yaml"
    path.write_text(
        "version: 1\nroot: ..\nchecks:\n  - name: readme\n    type: file\n    path: README.md\n",
        encoding="utf-8",
    )
    spec = load_spec(path)
    assert resolve_root(spec, path, None) == tmp_path.resolve()
    other = tmp_path / "other"
    other.mkdir()
    assert resolve_root(spec, path, str(other)) == other.resolve()


def test_rejects_absolute_root(tmp_path: Path) -> None:
    errors = spec_errors(tmp_path, "version: 1\nroot: /tmp\nchecks:\n  - name: a\n    type: file\n    path: a.txt\n")
    assert any("root must be a relative path" in item for item in errors)
