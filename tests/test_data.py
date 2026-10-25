"""JSON and YAML path checks."""

import json
from pathlib import Path

from tests.conftest import run_text


def test_json_paths_and_strict_numbers(tmp_path: Path) -> None:
    (tmp_path / "app.json").write_text(
        json.dumps(
            {
                "name": "tiny-app",
                "version": "0.1.0",
                "server": {"port": 8080, "host": "127.0.0.1"},
                "features": ["read", "write"],
                "ratio": 1.5,
            }
        ),
        encoding="utf-8",
    )
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: manifest
    type: json
    path: app.json
    equals:
      name: tiny-app
      server.port: 8080
      features[0]: read
      features.1: write
      ratio: 1.5
    exists:
      - version
      - server.host
""",
    )
    assert report.ok, report.checks[0].message

    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: wrong-type
    type: json
    path: app.json
    equals:
      server.port: "8080"
  - name: missing
    type: json
    path: app.json
    exists: [author]
  - name: whole-object
    type: json
    path: app.json
    equals:
      server:
        host: 127.0.0.1
        port: 8080
""",
    )
    assert not report.checks[0].ok
    assert "expected" in report.checks[0].message
    assert "missing author" in report.checks[1].message
    assert report.checks[2].ok


def test_one_does_not_match_one_point_zero(tmp_path: Path) -> None:
    (tmp_path / "n.json").write_text('{"n": 1.0}\n', encoding="utf-8")
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: n\n    type: json\n    path: n.json\n    equals:\n      n: 1\n",
    )
    assert not report.ok
    assert "1.0" in report.checks[0].message


def test_yaml_bool_and_single_document(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "feature:\n  beta: false\nservice:\n  name: tiny-app\n",
        encoding="utf-8",
    )
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: flag
    type: yaml
    path: config.yaml
    equals:
      feature.beta: false
      service.name: tiny-app
""",
    )
    assert report.ok, report.checks[0].message

    (tmp_path / "multi.yaml").write_text("a: 1\n---\nb: 2\n", encoding="utf-8")
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: multi\n    type: yaml\n    path: multi.yaml\n    exists: [a]\n",
    )
    assert "single YAML document" in report.checks[0].message


def test_missing_and_invalid_json(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: gone\n    type: json\n    path: app.json\n    exists: [name]\n",
    )
    assert "does not exist" in report.checks[0].message
    (tmp_path / "app.json").write_text("{", encoding="utf-8")
    report = run_text(
        tmp_path,
        "version: 1\nchecks:\n  - name: bad\n    type: json\n    path: app.json\n    exists: [name]\n",
    )
    assert "not valid JSON" in report.checks[0].message


def test_index_out_of_range(tmp_path: Path) -> None:
    (tmp_path / "app.json").write_text('{"features": ["read"]}\n', encoding="utf-8")
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: feature
    type: json
    path: app.json
    equals:
      features[3]: write
""",
    )
    assert "out of range" in report.checks[0].message
