"""CLI exit codes, discovery, JSON, color, and fail-fast."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_proof.cli import STARTER, main
from agent_proof.spec import load_spec
from tests.conftest import REPO


def test_help_says_command_checks_execute_the_spec(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "Only run a spec you trust" in out
    assert "shell command" in out


def test_run_text_report_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "README.md").write_text("hello agent", encoding="utf-8")
    (tmp_path / "proof.yaml").write_text(
        """\
version: 1
name: demo
checks:
  - name: readme
    type: file
    path: README.md
    contains: hello
  - name: missing
    type: file
    path: gone.txt
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run"]) == 1
    text = capsys.readouterr().out
    assert "Agent Proof" in text
    assert "PASS" in text
    assert "FAIL" in text
    assert "gone.txt does not exist" in text

    assert main(["proof.yaml", "--json", "--quiet"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["tool"] == "agent-proof"
    assert payload["summary"]["failed"] == 1
    assert payload["summary"]["planned"] == 2
    assert payload["checks"][1]["ok"] is False
    assert payload["stopped_early"] is False


def test_fail_fast_skips_later_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "proof.yaml").write_text(
        """\
version: 1
fail_fast: true
checks:
  - name: first
    type: file
    path: missing-a
  - name: second
    type: file
    path: missing-b
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["stopped_early"] is True
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["planned"] == 2
    assert "1 not run" in render_quiet(tmp_path, monkeypatch, capsys)


def render_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> str:
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--color=never"]) == 1
    return capsys.readouterr().out


def test_spec_error_json_and_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "bad.yaml").write_text("version: 9\nchecks: []\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["run", "bad.yaml", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "version" in payload["error"]
    assert payload["checks"] == []

    assert main(["validate", "bad.yaml"]) == 2
    err = capsys.readouterr().err
    assert "spec error" in err


def test_init_validate_and_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    spec = load_spec(tmp_path / "proof.yaml")
    assert spec.checks
    assert "wrote" in capsys.readouterr().out
    assert main(["init"]) == 2
    assert "already exists" in capsys.readouterr().err
    assert main(["validate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checks"] == len(spec.checks)

    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert "agent-proof" in capsys.readouterr().out
    assert STARTER.strip().startswith("version: 1")


def test_color_always_and_no_color(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    (tmp_path / "proof.yaml").write_text(
        "version: 1\nchecks:\n  - name: readme\n    type: file\n    path: README.md\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--color=always"]) == 0
    assert "\033[1;32m" in capsys.readouterr().out
    monkeypatch.setenv("NO_COLOR", "1")
    assert main(["run", "--color=always"]) == 0
    assert "\033[1;32m" in capsys.readouterr().out
    assert main(["run", "--no-color"]) == 0
    assert "\033[" not in capsys.readouterr().out


def test_quiet_hides_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    (tmp_path / "proof.yaml").write_text(
        "version: 1\nname: demo\nchecks:\n  - name: readme exists\n    type: file\n    path: README.md\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run", "-q", "--color=never"]) == 0
    out = capsys.readouterr().out
    assert "readme exists" not in out
    assert "1 passed, 0 failed, 1 total" in out


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err.lower() or "usage" in capsys.readouterr().out.lower()


def test_module_entrypoint_version() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "agent_proof", "--version"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "agent-proof 0.1.0"
