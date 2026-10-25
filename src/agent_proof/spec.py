"""Load and validate a proof spec. Invalid specs fail closed."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

from agent_proof.data_path import parse_data_path
from agent_proof.models import (
    Check,
    CommandCheck,
    DataCheck,
    FileCheck,
    GitCheck,
    Spec,
)
from agent_proof.util import coerce_datetime, parse_duration, require_relative_path

SPEC_NAMES = ("proof.yaml", "proof.yml", ".agent-proof.yaml", "agent-proof.yaml")
FILE_FIELDS = {
    "name",
    "type",
    "path",
    "glob",
    "exists",
    "min_bytes",
    "min_matches",
    "max_matches",
    "contains",
    "not_contains",
    "matches",
    "modified_after",
    "modified_within",
    "in_diff",
    "diff_base",
    "include_untracked",
}
COMMAND_FIELDS = {
    "name",
    "type",
    "run",
    "cwd",
    "exit_code",
    "timeout",
    "env",
    "stdout_contains",
    "stdout_not_contains",
    "stdout_matches",
    "stderr_contains",
    "stderr_not_contains",
    "stderr_matches",
}
GIT_FIELDS = {
    "name",
    "type",
    "paths",
    "dirty",
    "include_untracked",
    "since",
    "min_commits",
}
DATA_FIELDS = {"name", "type", "path", "equals", "exists"}
TOP_FIELDS = {"version", "name", "description", "root", "fail_fast", "checks"}
CHECK_TYPES = {"file", "command", "git", "json", "yaml"}


class SpecError(Exception):
    """The spec cannot be run. `errors` is safe to show to a person."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


class _StrictLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys."""


def _strict_mapping(loader: yaml.SafeLoader, node: yaml.Node) -> dict[object, object]:
    loader.flatten_mapping(node)  # type: ignore[no-untyped-call]
    pairs = loader.construct_pairs(node)
    mapping: dict[object, object] = {}
    for key, value in pairs:
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                node.start_mark,
            )
        mapping[key] = value
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _strict_mapping,
)


def discover_spec(start: Path | None = None) -> Path:
    directory = (start or Path.cwd()).resolve()
    for name in SPEC_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    looked = ", ".join(SPEC_NAMES)
    raise SpecError(
        [
            f"no proof spec found in {directory}",
            f"looked for: {looked}",
            "create one with: agent-proof init",
        ]
    )


def load_spec(path: Path) -> Spec:
    if not path.is_file():
        raise SpecError([f"spec not found: {path}"])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError([f"could not read {path}: {exc}"]) from exc
    if path.suffix.lower() == ".json":
        data = _load_json(text)
    else:
        data = _load_yaml(text)
    return parse_spec(data, path=path)


def parse_spec(data: object, *, path: Path) -> Spec:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise SpecError(["spec must be a mapping"])
    unknown = sorted(set(data) - TOP_FIELDS)
    for key in unknown:
        errors.append(f"unknown field {key!r}")
    version = data.get("version")
    if version != 1:
        errors.append("version must be 1")
    name = _optional_text(data.get("name"), "name", errors) if "name" in data else None
    description = (
        _optional_text(data.get("description"), "description", errors)
        if "description" in data
        else None
    )
    root = None
    if "root" in data:
        root = _root_value(data.get("root"), errors)
    fail_fast = False
    if "fail_fast" in data:
        parsed = _bool_value(data.get("fail_fast"), "fail_fast", errors)
        fail_fast = False if parsed is None else parsed
    checks_raw = data.get("checks")
    checks: list[Check] = []
    if not isinstance(checks_raw, list) or not checks_raw:
        errors.append("checks must be a non-empty list")
    else:
        seen: set[str] = set()
        for index, item in enumerate(checks_raw):
            check = _parse_check(item, index, errors)
            if check is None:
                continue
            if check.name in seen:
                errors.append(f"checks[{index}] ({check.name}): duplicate check name")
                continue
            seen.add(check.name)
            checks.append(check)
    if errors:
        raise SpecError(errors)
    return Spec(
        version=1,
        name=name,
        description=description,
        root=root,
        fail_fast=fail_fast,
        checks=checks,
        path=path,
    )


def resolve_root(spec: Spec, spec_path: Path, override: str | None) -> Path:
    """Project root for paths in the spec.

    `--root` wins. Otherwise `root:` is resolved from the spec file's directory.
    With neither, the root is the current working directory.
    """
    if override is not None:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve()
    if spec.root is not None:
        return (spec_path.resolve().parent / spec.root).resolve()
    return Path.cwd().resolve()


def _load_yaml(text: str) -> object:
    if text.strip() == "":
        raise SpecError(["spec is empty"])
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506  # trusted local spec, safe loader
    except yaml.YAMLError as exc:
        raise SpecError([f"invalid YAML: {exc}"]) from exc


def _load_json(text: str) -> object:
    if text.strip() == "":
        raise SpecError(["spec is empty"])

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        mapping: dict[str, object] = {}
        for key, value in items:
            if key in mapping:
                raise SpecError([f"duplicate key {key!r}"])
            mapping[key] = value
        return mapping

    try:
        return json.loads(text, object_pairs_hook=pairs)
    except SpecError:
        raise
    except json.JSONDecodeError as exc:
        raise SpecError([f"invalid JSON: {exc}"]) from exc


def _parse_check(item: object, index: int, errors: list[str]) -> Check | None:
    if not isinstance(item, dict):
        errors.append(f"checks[{index}] must be a mapping")
        return None
    name = item.get("name")
    label = f"checks[{index}]"
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{label}: name must be a non-empty string")
        name_text = None
    else:
        name_text = name
        label = f"checks[{index}] ({name})"
    kind = item.get("type")
    if kind not in CHECK_TYPES:
        expected = ", ".join(sorted(CHECK_TYPES))
        errors.append(f"{label}: type must be one of: {expected}")
        return None
    if name_text is None:
        return None
    if kind == "file":
        return _parse_file(item, name_text, label, errors)
    if kind == "command":
        return _parse_command(item, name_text, label, errors)
    if kind == "git":
        return _parse_git(item, name_text, label, errors)
    return _parse_data(item, name_text, kind, label, errors)


def _parse_file(item: dict[str, Any], name: str, label: str, errors: list[str]) -> FileCheck | None:
    _reject_unknown(item, FILE_FIELDS, label, errors)
    before = len(errors)
    path = _optional_path(item, "path", label, errors)
    pattern = _optional_path(item, "glob", label, errors)
    if pattern is not None:
        pattern = _normalize_glob(pattern, label, errors)
    has_path = "path" in item
    has_glob = "glob" in item
    if has_path == has_glob:
        if not has_path:
            errors.append(f"{label}: set path or glob")
        else:
            errors.append(f"{label}: set path or glob, not both")
    exists = True
    if "exists" in item:
        parsed = _bool_value(item.get("exists"), f"{label}: exists", errors)
        if parsed is not None:
            exists = parsed
    min_bytes = _optional_int(item, "min_bytes", label, errors, minimum=0)
    min_matches = _optional_int(item, "min_matches", label, errors, minimum=1)
    max_matches = _optional_int(item, "max_matches", label, errors, minimum=1)
    contains = _optional_text_field(item, "contains", label, errors)
    not_contains = _optional_text_field(item, "not_contains", label, errors)
    matches = _optional_text_field(item, "matches", label, errors)
    if matches is not None:
        _compile(matches, label, "matches", errors)
    modified_after = None
    if "modified_after" in item:
        try:
            modified_after = coerce_datetime(item.get("modified_after"))
        except ValueError as exc:
            errors.append(f"{label}: modified_after {exc}")
    modified_within = None
    if "modified_within" in item:
        try:
            modified_within = parse_duration(item.get("modified_within"), require_unit=True)
        except ValueError as exc:
            errors.append(f"{label}: modified_within {exc}")
    in_diff = None
    if "in_diff" in item:
        in_diff = _bool_value(item.get("in_diff"), f"{label}: in_diff", errors)
    diff_base = "HEAD"
    if "diff_base" in item:
        diff_base = _git_ref(item.get("diff_base"), f"{label}: diff_base", errors) or "HEAD"
        if "in_diff" not in item:
            errors.append(f"{label}: diff_base requires in_diff")
    include_untracked = True
    if "include_untracked" in item:
        parsed = _bool_value(item.get("include_untracked"), f"{label}: include_untracked", errors)
        if parsed is not None:
            include_untracked = parsed
        if "in_diff" not in item:
            errors.append(f"{label}: include_untracked requires in_diff")
    content_fields = [
        name
        for name, present in (
            ("min_bytes", "min_bytes" in item),
            ("contains", "contains" in item),
            ("not_contains", "not_contains" in item),
            ("matches", "matches" in item),
            ("modified_after", "modified_after" in item),
            ("modified_within", "modified_within" in item),
            ("min_matches", "min_matches" in item),
            ("max_matches", "max_matches" in item),
        )
        if present
    ]
    if not exists and content_fields:
        joined = ", ".join(content_fields)
        errors.append(f"{label}: {joined} cannot be set when exists is false")
    if not exists and in_diff is not None and pattern is not None:
        errors.append(f"{label}: in_diff with exists false requires path, not glob")
    if pattern is None and (min_matches is not None or max_matches is not None):
        errors.append(f"{label}: min_matches and max_matches require glob")
    if pattern is not None and exists and min_matches is None and "min_matches" not in item:
        min_matches = 1
    if (
        min_matches is not None
        and max_matches is not None
        and max_matches < min_matches
    ):
        errors.append(f"{label}: max_matches must be >= min_matches")
    if len(errors) != before:
        return None
    return FileCheck(
        name=name,
        path=path,
        glob_pattern=pattern,
        exists=exists,
        min_bytes=min_bytes,
        min_matches=min_matches,
        max_matches=max_matches,
        contains=contains,
        not_contains=not_contains,
        matches=matches,
        modified_after=modified_after,
        modified_within=modified_within,
        in_diff=in_diff,
        diff_base=diff_base,
        include_untracked=include_untracked,
    )


def _parse_command(
    item: dict[str, Any], name: str, label: str, errors: list[str]
) -> CommandCheck | None:
    _reject_unknown(item, COMMAND_FIELDS, label, errors)
    before = len(errors)
    run = _parse_run(item.get("run"), label, errors) if "run" in item else None
    if "run" not in item:
        errors.append(f"{label}: run is required")
    cwd = _optional_path(item, "cwd", label, errors)
    exit_code = 0
    if "exit_code" in item:
        parsed = _int_value(item.get("exit_code"), f"{label}: exit_code", errors)
        if parsed is not None:
            exit_code = parsed
    timeout = 60.0
    if "timeout" in item:
        try:
            timeout = parse_duration(item.get("timeout"))
        except ValueError as exc:
            errors.append(f"{label}: timeout {exc}")
        else:
            if timeout <= 0 or timeout > 86400:
                errors.append(f"{label}: timeout must be greater than 0 and at most 86400 seconds")
    env = _parse_env(item.get("env"), label, errors) if "env" in item else ()
    stdout_contains = _optional_text_field(item, "stdout_contains", label, errors)
    stdout_not_contains = _optional_text_field(item, "stdout_not_contains", label, errors)
    stdout_matches = _optional_text_field(item, "stdout_matches", label, errors)
    stderr_contains = _optional_text_field(item, "stderr_contains", label, errors)
    stderr_not_contains = _optional_text_field(item, "stderr_not_contains", label, errors)
    stderr_matches = _optional_text_field(item, "stderr_matches", label, errors)
    if stdout_matches is not None:
        _compile(stdout_matches, label, "stdout_matches", errors)
    if stderr_matches is not None:
        _compile(stderr_matches, label, "stderr_matches", errors)
    if len(errors) != before or run is None:
        return None
    return CommandCheck(
        name=name,
        run=run,
        cwd=cwd,
        exit_code=exit_code,
        timeout=timeout,
        env=env,
        stdout_contains=stdout_contains,
        stdout_not_contains=stdout_not_contains,
        stdout_matches=stdout_matches,
        stderr_contains=stderr_contains,
        stderr_not_contains=stderr_not_contains,
        stderr_matches=stderr_matches,
    )


def _parse_git(item: dict[str, Any], name: str, label: str, errors: list[str]) -> GitCheck | None:
    _reject_unknown(item, GIT_FIELDS, label, errors)
    before = len(errors)
    paths = None
    if "paths" in item:
        raw = item.get("paths")
        if not isinstance(raw, list) or not raw:
            errors.append(f"{label}: paths must be a non-empty list")
        else:
            collected: list[str] = []
            valid = True
            for entry in raw:
                try:
                    collected.append(require_relative_path(entry, "paths"))
                except ValueError as exc:
                    errors.append(f"{label}: {exc}")
                    valid = False
            if valid:
                paths = tuple(collected)
    dirty = None
    if "dirty" in item:
        dirty = _bool_value(item.get("dirty"), f"{label}: dirty", errors)
    since = None
    if "since" in item:
        since = _git_ref(item.get("since"), f"{label}: since", errors)
    if "dirty" not in item and "since" not in item:
        errors.append(f"{label}: set dirty, since, or both")
    min_commits = 1
    if "min_commits" in item:
        if "since" not in item:
            errors.append(f"{label}: min_commits requires since")
        parsed = _int_value(item.get("min_commits"), f"{label}: min_commits", errors, minimum=1)
        if parsed is not None:
            min_commits = parsed
    include_untracked = True
    if "include_untracked" in item:
        if "dirty" not in item:
            errors.append(f"{label}: include_untracked requires dirty")
        parsed = _bool_value(item.get("include_untracked"), f"{label}: include_untracked", errors)
        if parsed is not None:
            include_untracked = parsed
    if len(errors) != before:
        return None
    return GitCheck(
        name=name,
        paths=paths,
        dirty=dirty,
        include_untracked=include_untracked,
        since=since,
        min_commits=min_commits,
    )


def _parse_data(
    item: dict[str, Any], name: str, kind: str, label: str, errors: list[str]
) -> DataCheck | None:
    _reject_unknown(item, DATA_FIELDS, label, errors)
    before = len(errors)
    path = _optional_path(item, "path", label, errors)
    if "path" not in item:
        errors.append(f"{label}: path is required")
    equals: list[tuple[str, object]] = []
    if "equals" in item:
        raw = item.get("equals")
        if not isinstance(raw, dict) or not raw:
            errors.append(f"{label}: equals must be a non-empty mapping")
        else:
            for key, value in raw.items():
                if not isinstance(key, str) or not key:
                    errors.append(f"{label}: equals keys must be non-empty strings")
                    continue
                try:
                    parse_data_path(key)
                except ValueError as exc:
                    errors.append(f"{label}: equals key {key!r}: {exc}")
                else:
                    equals.append((key, value))
    exists: list[str] = []
    if "exists" in item:
        raw_exists = item.get("exists")
        if not isinstance(raw_exists, list) or not raw_exists:
            errors.append(f"{label}: exists must be a non-empty list of paths")
        else:
            for entry in raw_exists:
                if not isinstance(entry, str) or not entry:
                    errors.append(f"{label}: exists entries must be non-empty strings")
                    continue
                try:
                    parse_data_path(entry)
                except ValueError as exc:
                    errors.append(f"{label}: exists path {entry!r}: {exc}")
                else:
                    exists.append(entry)
    if "equals" not in item and "exists" not in item:
        errors.append(f"{label}: set equals, exists, or both")
    if len(errors) != before or path is None:
        return None
    return DataCheck(
        name=name,
        format=kind,
        path=path,
        equals=tuple(equals),
        exists=tuple(exists),
    )


def _parse_run(value: object, label: str, errors: list[str]) -> str | tuple[str, ...] | None:
    if isinstance(value, str):
        if not value.strip():
            errors.append(f"{label}: run must not be empty")
            return None
        return value
    if isinstance(value, list):
        if not value:
            errors.append(f"{label}: run must not be empty")
            return None
        parts: list[str] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                errors.append(f"{label}: run entries must be strings or numbers")
                return None
            if isinstance(item, str):
                parts.append(item)
            else:
                parts.append(str(item))
        return tuple(parts)
    errors.append(f"{label}: run must be a string or a list")
    return None


def _parse_env(value: object, label: str, errors: list[str]) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        errors.append(f"{label}: env must be a mapping")
        return ()
    pairs: list[tuple[str, str]] = []
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            errors.append(f"{label}: env keys must be non-empty strings")
            continue
        if isinstance(item, bool):
            pairs.append((key, "true" if item else "false"))
        elif isinstance(item, (int, float)):
            pairs.append((key, str(item)))
        elif isinstance(item, str):
            pairs.append((key, item))
        else:
            errors.append(f"{label}: env.{key} must be a string, number, or boolean")
    return tuple(pairs)


def _reject_unknown(item: dict[str, Any], allowed: set[str], label: str, errors: list[str]) -> None:
    for key in sorted(set(item) - allowed):
        errors.append(f"{label}: unknown field {key!r}")


def _optional_path(item: dict[str, Any], field: str, label: str, errors: list[str]) -> str | None:
    if field not in item:
        return None
    try:
        return require_relative_path(item.get(field), field)
    except ValueError as exc:
        errors.append(f"{label}: {exc}")
        return None


def _optional_text(value: object, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")
        return None
    return value


def _optional_text_field(item: dict[str, Any], field: str, label: str, errors: list[str]) -> str | None:
    if field not in item:
        return None
    value = item.get(field)
    if not isinstance(value, str) or value == "":
        errors.append(f"{label}: {field} must be a non-empty string")
        return None
    return value


def _optional_int(
    item: dict[str, Any],
    field: str,
    label: str,
    errors: list[str],
    *,
    minimum: int,
) -> int | None:
    if field not in item:
        return None
    return _int_value(item.get(field), f"{label}: {field}", errors, minimum=minimum)


def _int_value(
    value: object, label: str, errors: list[str], *, minimum: int | None = None
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{label} must be an integer")
        return None
    if minimum is not None and value < minimum:
        errors.append(f"{label} must be >= {minimum}")
        return None
    return value


def _bool_value(value: object, label: str, errors: list[str]) -> bool | None:
    if not isinstance(value, bool):
        errors.append(f"{label} must be a boolean")
        return None
    return value


def _git_ref(value: object, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        errors.append(f"{label} must be a non-empty git ref")
        return None
    if value.startswith("-") or "\n" in value or "\x00" in value:
        errors.append(f"{label} is not a valid git ref")
        return None
    return value


def _compile(pattern: str, label: str, field: str, errors: list[str]) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        errors.append(f"{label}: {field} is not a valid regular expression ({exc})")


def _normalize_glob(pattern: str, label: str, errors: list[str]) -> str | None:
    parts = tuple(part for part in PurePosixPath(pattern).parts if part != ".")
    if not parts:
        errors.append(f"{label}: glob must match something under the project root")
        return None
    return str(PurePosixPath(*parts))


def _root_value(value: object, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\\" in value or "\x00" in value:
        errors.append("root must be a relative path")
        return None
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        errors.append("root must be a relative path")
        return None
    return value
