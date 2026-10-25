"""Shared data types for specs, check results, and the run report."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Union


@dataclass(frozen=True)
class FileCheck:
    name: str
    path: str | None
    glob_pattern: str | None
    exists: bool
    min_bytes: int | None
    min_matches: int | None
    max_matches: int | None
    contains: str | None
    not_contains: str | None
    matches: str | None
    modified_after: datetime | None
    modified_within: float | None
    in_diff: bool | None
    diff_base: str
    include_untracked: bool


@dataclass(frozen=True)
class CommandCheck:
    name: str
    run: str | tuple[str, ...]
    cwd: str | None
    exit_code: int
    timeout: float
    env: tuple[tuple[str, str], ...]
    stdout_contains: str | None
    stdout_not_contains: str | None
    stdout_matches: str | None
    stderr_contains: str | None
    stderr_not_contains: str | None
    stderr_matches: str | None


@dataclass(frozen=True)
class GitCheck:
    name: str
    paths: tuple[str, ...] | None
    dirty: bool | None
    include_untracked: bool
    since: str | None
    min_commits: int


@dataclass(frozen=True)
class DataCheck:
    name: str
    format: str  # "json" or "yaml"
    path: str
    equals: tuple[tuple[str, Any], ...]
    exists: tuple[str, ...]


Check = Union[FileCheck, CommandCheck, GitCheck, DataCheck]


@dataclass
class Spec:
    version: int
    name: str | None
    description: str | None
    root: str | None
    fail_fast: bool
    checks: list[Check]
    path: Path


@dataclass
class CheckResult:
    name: str
    type: str
    ok: bool
    message: str
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Summary:
    passed: int
    failed: int
    total: int
    planned: int
    duration_ms: int


@dataclass
class Report:
    ok: bool
    tool: str
    version: str
    spec: str
    name: str | None
    description: str | None
    root: str
    summary: Summary
    checks: list[CheckResult]
    stopped_early: bool
    error: str | None = None
