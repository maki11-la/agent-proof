"""Helpers for spec and git fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_proof.engine import execute
from agent_proof.models import Report
from agent_proof.spec import SpecError, load_spec

REPO = Path(__file__).resolve().parents[1]


def run_text(tmp_path: Path, text: str, *, fail_fast: bool = False) -> Report:
    """Run a spec against `tmp_path` without writing the spec into that tree.

    Git checks would otherwise see the spec file as an untracked change.
    """
    path = tmp_path.parent / f"{tmp_path.name}-proof.yaml"
    path.write_text(text, encoding="utf-8")
    try:
        spec = load_spec(path)
        return execute(
            spec,
            root=tmp_path,
            spec_label="proof.yaml",
            fail_fast=fail_fast or spec.fail_fast,
        )
    finally:
        path.unlink(missing_ok=True)


def spec_errors(tmp_path: Path, text: str, name: str = "proof.yaml") -> list[str]:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SpecError) as caught:
        load_spec(path)
    return caught.value.errors


def git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    for key, value in (
        ("user.email", "dev@example.com"),
        ("user.name", "Dev"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(
            ["git", "config", key, value],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )


def git_commit(path: Path, message: str = "work") -> None:
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
