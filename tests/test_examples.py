"""The published examples and the repository proof run end to end."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_proof.cli import main
from agent_proof.spec import load_spec
from tests.conftest import REPO

HEADINGS = (
    "## Security",
    "## Why it exists",
    "## How it differs",
    "## Install",
    "## Quick start",
    "## Example spec",
    "## Example output",
    "## Check reference",
    "## CI",
    "## Use with AI agents",
    "## Roadmap",
    "## Contributing",
    "## Sponsors",
)


def test_readme_has_the_required_sections_and_the_quickstart_spec() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for heading in HEADINGS:
        assert heading in readme
    spec = (REPO / "examples/quickstart/proof.yaml").read_text(encoding="utf-8").strip()
    assert spec in readme
    assert "pipx install" in readme
    assert "Only run a spec you trust" in readme
    assert "Traceplain" in readme
    assert "judge the trace" not in readme
    assert "AgentLens" in readme
    assert "AgentCron" in readme


def test_example_specs_parse() -> None:
    for path in (
        REPO / "proof.yaml",
        REPO / "examples" / "quickstart" / "proof.yaml",
        REPO / "examples" / "tiny-app" / "proof.yaml",
        REPO / "examples" / "git-gate" / "proof.yaml",
    ):
        spec = load_spec(path)
        assert spec.checks


def test_repository_examples_pass(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(REPO)
    assert main(["run", "proof.yaml", "--color=never"]) == 0
    assert "FAIL" not in capsys.readouterr().out
    assert main(["run", "examples/quickstart/proof.yaml"]) == 0
    assert main(["run", "examples/tiny-app/proof.yaml", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out


def test_module_runs_tiny_app() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "agent_proof", "run", "examples/tiny-app/proof.yaml"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout
    assert "tiny-app" in proc.stdout
