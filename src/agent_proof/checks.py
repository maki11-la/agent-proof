"""Run one validated check. These functions do not call a model."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from agent_proof.data_path import PathLookupError, lookup
from agent_proof.gitutil import (
    GitError,
    Runtime,
    commit_count,
    repo_relative,
    spec_pathspec,
    status_paths,
)
from agent_proof.models import (
    Check,
    CheckResult,
    CommandCheck,
    DataCheck,
    FileCheck,
    GitCheck,
)
from agent_proof.util import (
    MAX_CAPTURE_CHARS,
    MAX_TEXT_BYTES,
    UserError,
    clip_lines,
    clip_text,
    command_display,
    display_path,
    format_duration,
    format_utc,
    is_inside,
    show_value,
    values_equal,
)


def check_type(check: Check) -> str:
    if isinstance(check, FileCheck):
        return "file"
    if isinstance(check, CommandCheck):
        return "command"
    if isinstance(check, GitCheck):
        return "git"
    return check.format


def run_check(check: Check, runtime: Runtime) -> CheckResult:
    if isinstance(check, FileCheck):
        return _run_file(check, runtime)
    if isinstance(check, CommandCheck):
        return _run_command(check, runtime)
    if isinstance(check, GitCheck):
        return _run_git(check, runtime)
    return _run_data(check, runtime)


def _ok(check: Check, message: str, **details: object) -> CheckResult:
    return _result(check, True, message, details)


def _fail(check: Check, message: str, **details: object) -> CheckResult:
    return _result(check, False, message, details)


def _result(check: Check, ok: bool, message: str, details: dict[str, object]) -> CheckResult:
    return CheckResult(
        name=check.name,
        type=check_type(check),
        ok=ok,
        message=message,
        details={key: value for key, value in details.items() if value is not None},
    )


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except OSError:
        return False
    return True


def _run_file(check: FileCheck, runtime: Runtime) -> CheckResult:
    if check.glob_pattern is not None:
        return _run_glob(check, runtime)
    assert check.path is not None
    path = runtime.root / check.path
    if not is_inside(runtime.root, path):
        return _fail(check, f"{check.path} escapes the project root")
    rel = display_path(runtime.root, path)
    if not _exists(path):
        if check.exists:
            return _fail(check, f"{rel} does not exist", path=rel)
        return _absent(check, runtime, path, rel)
    if not check.exists:
        return _fail(check, f"{rel} exists", path=rel)
    problem = _file_problem(check, path, rel)
    if problem is not None:
        return _fail(check, problem, path=rel)
    if check.in_diff is not None:
        try:
            found = _path_in_diff(runtime, check, path, as_tree=path.is_dir())
        except GitError as exc:
            return _fail(check, str(exc), path=rel)
        if check.in_diff and not found:
            return _fail(check, f"{rel} is not in the git diff against {check.diff_base}", path=rel)
        if not check.in_diff and found:
            return _fail(check, f"{rel} is in the git diff against {check.diff_base}", path=rel)
    details: dict[str, object] = {"path": rel}
    if path.is_file():
        details["bytes"] = path.stat().st_size
    return _ok(check, _file_success(check, path, rel), **details)


def _absent(check: FileCheck, runtime: Runtime, path: Path, rel: str) -> CheckResult:
    message = f"{rel} does not exist"
    if check.in_diff is None:
        return _ok(check, message, path=rel)
    try:
        found = _path_in_diff(runtime, check, path, as_tree=True)
    except GitError as exc:
        return _fail(check, str(exc), path=rel)
    if check.in_diff and not found:
        return _fail(
            check,
            f"{rel} does not exist, but it is not in the git diff against {check.diff_base}",
            path=rel,
        )
    if not check.in_diff and found:
        return _fail(check, f"{rel} is in the git diff against {check.diff_base}", path=rel)
    if check.in_diff:
        message += f" and is in the git diff against {check.diff_base}"
    return _ok(check, message, path=rel)


def _run_glob(check: FileCheck, runtime: Runtime) -> CheckResult:
    assert check.glob_pattern is not None
    pattern = check.glob_pattern
    try:
        found = list(runtime.root.glob(pattern))
    except (OSError, ValueError) as exc:
        return _fail(check, f"glob {pattern!r} could not be expanded: {exc}")
    matches = [path for path in found if path.is_file() and is_inside(runtime.root, path)]
    matches.sort(key=lambda path: path.as_posix())
    if check.in_diff is True:
        try:
            changed = runtime.changed(check.diff_base, check.include_untracked)
            repo = runtime.repo()
        except GitError as exc:
            return _fail(check, str(exc))
        matches = [path for path in matches if repo_relative(repo, path) in changed]
    if not check.exists:
        if matches:
            return _fail(check, _match_list(pattern, matches, runtime))
        return _ok(check, f"no files matched {pattern}")
    minimum = check.min_matches if check.min_matches is not None else 1
    where = f" in the git diff against {check.diff_base}" if check.in_diff else ""
    if len(matches) < minimum:
        noun = "file" if len(matches) == 1 else "files"
        return _fail(
            check,
            f"{len(matches)} {noun} matched {pattern}{where}, expected at least {minimum}",
            match_count=len(matches),
        )
    if check.max_matches is not None and len(matches) > check.max_matches:
        noun = "file" if len(matches) == 1 else "files"
        return _fail(
            check,
            f"{len(matches)} {noun} matched {pattern}, expected at most {check.max_matches}",
            match_count=len(matches),
        )
    for path in matches:
        rel = display_path(runtime.root, path)
        problem = _file_problem(check, path, rel)
        if problem is not None:
            return _fail(check, problem, path=rel)
    if check.in_diff is False:
        try:
            changed = runtime.changed(check.diff_base, check.include_untracked)
            repo = runtime.repo()
        except GitError as exc:
            return _fail(check, str(exc))
        dirty = [path for path in matches if repo_relative(repo, path) in changed]
        if dirty:
            shown = ", ".join(display_path(runtime.root, path) for path in dirty[:8])
            return _fail(check, f"{shown} is in the git diff against {check.diff_base}")
    noun = "file" if len(matches) == 1 else "files"
    message = f"{len(matches)} {noun} matched {pattern}{where}"
    qualifiers = _qualifiers(check)
    if qualifiers:
        message += "; each " + "; each ".join(qualifiers)
    if check.in_diff is False:
        message += f"; not in the git diff against {check.diff_base}"
    shown = [display_path(runtime.root, path) for path in matches[:20]]
    return _ok(check, message, match_count=len(matches), matches=shown)


def _file_problem(check: FileCheck, path: Path, rel: str) -> str | None:
    wants_contents = any(
        (
            check.min_bytes is not None,
            check.contains is not None,
            check.not_contains is not None,
            check.matches is not None,
            check.modified_after is not None,
            check.modified_within is not None,
        )
    )
    if wants_contents and not path.is_file():
        kind = "a directory" if path.is_dir() else "not a file"
        return f"{rel} is {kind}"
    if not path.is_file():
        return None
    size = path.stat().st_size
    if check.min_bytes is not None and size < check.min_bytes:
        return f"{rel} is {size:,} bytes, expected at least {check.min_bytes:,}"
    if check.contains is not None or check.not_contains is not None or check.matches is not None:
        try:
            text = _read_text(path)
        except UserError as exc:
            return f"{rel} {exc}"
        if check.contains is not None and check.contains not in text:
            return f"{rel} does not contain {show_value(check.contains)}"
        if check.not_contains is not None and check.not_contains in text:
            return f"{rel} contains {show_value(check.not_contains)}"
        if check.matches is not None and re.search(check.matches, text, re.MULTILINE) is None:
            return f"{rel} does not match /{check.matches}/"
    if check.modified_after is not None or check.modified_within is not None:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if check.modified_after is not None and mtime <= check.modified_after:
            return (
                f"{rel} was last modified at {format_utc(mtime)}, "
                f"expected after {format_utc(check.modified_after)}"
            )
        if check.modified_within is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=check.modified_within)
            if mtime < cutoff:
                return (
                    f"{rel} was last modified at {format_utc(mtime)}, "
                    f"expected within {format_duration(check.modified_within)}"
                )
    return None


def _file_success(check: FileCheck, path: Path, rel: str) -> str:
    if path.is_dir():
        message = f"{rel} exists (directory)"
    elif path.is_file():
        message = f"{rel} exists ({path.stat().st_size:,} bytes)"
    else:
        message = f"{rel} exists"
    qualifiers = _qualifiers(check, include_size=False)
    if qualifiers:
        message += "; " + "; ".join(qualifiers)
    if check.in_diff is True:
        message += f"; in the git diff against {check.diff_base}"
    elif check.in_diff is False:
        message += f"; not in the git diff against {check.diff_base}"
    return message


def _qualifiers(check: FileCheck, *, include_size: bool = True) -> list[str]:
    parts: list[str] = []
    if include_size and check.min_bytes is not None:
        parts.append(f"is at least {check.min_bytes:,} bytes")
    if check.contains is not None:
        parts.append(f"contains {show_value(check.contains)}")
    if check.not_contains is not None:
        parts.append(f"does not contain {show_value(check.not_contains)}")
    if check.matches is not None:
        parts.append(f"matches /{check.matches}/")
    if check.modified_after is not None:
        parts.append(f"modified after {format_utc(check.modified_after)}")
    if check.modified_within is not None:
        parts.append(f"modified within {format_duration(check.modified_within)}")
    return parts


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UserError(f"could not be read: {exc}") from exc
    if len(data) > MAX_TEXT_BYTES:
        raise UserError(f"is larger than {MAX_TEXT_BYTES:,} bytes; content checks were skipped")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserError("is not valid UTF-8") from exc


def _path_in_diff(runtime: Runtime, check: FileCheck, path: Path, *, as_tree: bool) -> bool:
    changed = runtime.changed(check.diff_base, check.include_untracked)
    rel = repo_relative(runtime.repo(), path)
    if rel in (".", ""):
        return bool(changed) if as_tree else False
    if rel in changed:
        return True
    if not as_tree:
        return False
    prefix = rel.rstrip("/") + "/"
    return any(name.startswith(prefix) for name in changed)


def _match_list(pattern: str, matches: list[Path], runtime: Runtime) -> str:
    shown = ", ".join(display_path(runtime.root, path) for path in matches[:8])
    extra = ""
    if len(matches) > 8:
        extra = f" (+{len(matches) - 8} more)"
    noun = "file" if len(matches) == 1 else "files"
    return f"{len(matches)} {noun} matched {pattern}: {shown}{extra}"


def _run_command(check: CommandCheck, runtime: Runtime) -> CheckResult:
    cwd = runtime.root if check.cwd is None else runtime.root / check.cwd
    if not is_inside(runtime.root, cwd):
        return _fail(check, "cwd escapes the project root")
    if not cwd.is_dir():
        shown = check.cwd or "."
        return _fail(check, f"cwd {shown} does not exist")
    env = os.environ.copy()
    env.update(dict(check.env))
    display = command_display(check.run)
    kwargs: dict[str, object] = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if isinstance(check.run, str):
        command: str | list[str] = check.run
        kwargs["shell"] = True
        if os.name != "nt":
            kwargs["executable"] = "/bin/sh"
    else:
        command = list(check.run)
        kwargs["shell"] = False
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(command, **kwargs)  # noqa: S603
    except FileNotFoundError:
        return _fail(check, f"command not found: {display}", command=display)
    except OSError as exc:
        return _fail(check, f"failed to start command: {exc}", command=display)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=check.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(proc)
        stdout, stderr = proc.communicate()
    stdout = stdout or ""
    stderr = stderr or ""
    if len(stdout) > MAX_CAPTURE_CHARS or len(stderr) > MAX_CAPTURE_CHARS:
        return _fail(
            check,
            f"output exceeded {MAX_CAPTURE_CHARS:,} characters",
            command=display,
            timed_out=timed_out,
        )
    out_clip, out_trunc = clip_text(stdout)
    err_clip, err_trunc = clip_text(stderr)
    details: dict[str, object] = {
        "command": display,
        "exit_code": proc.returncode,
        "expected_exit_code": check.exit_code,
        "timed_out": timed_out,
        "stdout": out_clip,
        "stderr": err_clip,
    }
    if out_trunc:
        details["stdout_truncated"] = True
    if err_trunc:
        details["stderr_truncated"] = True
    if check.cwd is not None:
        details["cwd"] = check.cwd
    if timed_out:
        return _fail(
            check,
            _with_streams(f"timed out after {format_duration(check.timeout)}", stdout, stderr),
            **details,
        )
    if proc.returncode != check.exit_code:
        hint = " (command not found)" if proc.returncode == 127 else ""
        message = f"exited {proc.returncode}, expected {check.exit_code}{hint}"
        return _fail(check, _with_streams(message, stdout, stderr), **details)
    problems = _stream_problems(check, stdout, stderr)
    if problems:
        return _fail(check, _with_streams("; ".join(problems), stdout, stderr), **details)
    bits = [f"exited {proc.returncode}"]
    if check.stdout_contains is not None:
        bits.append(f"stdout contains {show_value(check.stdout_contains)}")
    if check.stdout_matches is not None:
        bits.append(f"stdout matches /{check.stdout_matches}/")
    if check.stderr_contains is not None:
        bits.append(f"stderr contains {show_value(check.stderr_contains)}")
    if check.stderr_matches is not None:
        bits.append(f"stderr matches /{check.stderr_matches}/")
    return _ok(check, "; ".join(bits), **details)


def _stream_problems(check: CommandCheck, stdout: str, stderr: str) -> list[str]:
    problems: list[str] = []
    if check.stdout_contains is not None and check.stdout_contains not in stdout:
        problems.append(f"stdout does not contain {show_value(check.stdout_contains)}")
    if check.stdout_not_contains is not None and check.stdout_not_contains in stdout:
        problems.append(f"stdout contains {show_value(check.stdout_not_contains)}")
    if check.stdout_matches is not None and re.search(check.stdout_matches, stdout, re.MULTILINE) is None:
        problems.append(f"stdout does not match /{check.stdout_matches}/")
    if check.stderr_contains is not None and check.stderr_contains not in stderr:
        problems.append(f"stderr does not contain {show_value(check.stderr_contains)}")
    if check.stderr_not_contains is not None and check.stderr_not_contains in stderr:
        problems.append(f"stderr contains {show_value(check.stderr_not_contains)}")
    if check.stderr_matches is not None and re.search(check.stderr_matches, stderr, re.MULTILINE) is None:
        problems.append(f"stderr does not match /{check.stderr_matches}/")
    return problems


def _with_streams(message: str, stdout: str, stderr: str) -> str:
    parts = [message]
    if stdout.strip():
        parts.append("stdout:")
        parts.append(_indent(clip_lines(stdout)))
    if stderr.strip():
        parts.append("stderr:")
        parts.append(_indent(clip_lines(stderr)))
    return "\n".join(parts)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())


def _kill(proc: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _run_git(check: GitCheck, runtime: Runtime) -> CheckResult:
    try:
        repo = runtime.repo()
        pathspecs = None
        if check.paths is not None:
            pathspecs = [spec_pathspec(runtime.root, repo, item) for item in check.paths]
        good: list[str] = []
        bad: list[str] = []
        changed: list[str] = []
        count: int | None = None
        if check.dirty is not None:
            changed = _unique(status_paths(repo, pathspecs, include_untracked=check.include_untracked))
            scope = _tree_scope(check.paths)
            if check.dirty and not changed:
                bad.append(f"no changes {scope}")
            elif check.dirty:
                noun = "path" if len(changed) == 1 else "paths"
                good.append(f"{len(changed)} changed {noun} {scope}: {_sample(changed)}")
            elif changed:
                bad.append(f"working tree has changes {scope}: {_sample(changed)}")
            else:
                good.append(f"working tree is clean {scope}")
        if check.since is not None:
            count = commit_count(repo, check.since, pathspecs)
            touch = _commit_scope(check.paths)
            if count < check.min_commits:
                bad.append(
                    f"{count} commits since {check.since}{touch}, expected at least {check.min_commits}"
                )
            else:
                noun = "commit" if count == 1 else "commits"
                good.append(f"{count} {noun} since {check.since}{touch}")
    except GitError as exc:
        return _fail(check, str(exc))
    details: dict[str, object] = {}
    if check.dirty is not None:
        details["changed"] = changed[:20]
        details["changed_count"] = len(changed)
    if count is not None:
        details["commits"] = count
    if bad:
        return _fail(check, "; ".join(bad), **details)
    return _ok(check, "; ".join(good), **details)


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _sample(items: list[str], limit: int = 8) -> str:
    shown = ", ".join(items[:limit])
    if len(items) > limit:
        shown += f" (+{len(items) - limit} more)"
    return shown


def _tree_scope(paths: tuple[str, ...] | None) -> str:
    if not paths:
        return "in the working tree"
    return "under " + ", ".join(paths)


def _commit_scope(paths: tuple[str, ...] | None) -> str:
    if not paths:
        return ""
    return " touching " + ", ".join(paths)


def _run_data(check: DataCheck, runtime: Runtime) -> CheckResult:
    path = runtime.root / check.path
    if not is_inside(runtime.root, path):
        return _fail(check, f"{check.path} escapes the project root")
    rel = display_path(runtime.root, path)
    if not path.is_file():
        if path.exists():
            return _fail(check, f"{rel} is not a file", path=rel)
        return _fail(check, f"{rel} does not exist", path=rel)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _fail(check, f"{rel} could not be read: {exc}", path=rel)
    if len(raw) > MAX_TEXT_BYTES:
        return _fail(check, f"{rel} is larger than {MAX_TEXT_BYTES:,} bytes", path=rel)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _fail(check, f"{rel} is not valid UTF-8", path=rel)
    try:
        data = _parse_document(text, check.format, rel)
    except UserError as exc:
        return _fail(check, str(exc), path=rel)
    if data is None:
        return _fail(check, f"{rel} is empty", path=rel)
    problems: list[str] = []
    for key_path in check.exists:
        try:
            lookup(data, key_path)
        except PathLookupError as exc:
            problems.append(exc.message)
    matched: list[str] = []
    for key_path, expected in check.equals:
        try:
            actual = lookup(data, key_path)
        except PathLookupError as exc:
            problems.append(exc.message)
            continue
        if not values_equal(actual, expected):
            problems.append(
                f"{key_path} is {show_value(actual)}, expected {show_value(expected)}"
            )
        else:
            matched.append(key_path)
    if problems:
        return _fail(check, "; ".join(problems), path=rel)
    if len(check.equals) == 1 and not check.exists:
        key_path, expected = check.equals[0]
        return _ok(check, f"{rel}: {key_path} is {show_value(expected)}", path=rel)
    total = len(check.equals) + len(check.exists)
    return _ok(check, f"{rel}: {total} values matched", path=rel, matched=matched)


def _parse_document(text: str, fmt: str, rel: str) -> object:
    if fmt == "json":
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise UserError(f"{rel} is not valid JSON: {exc.msg}") from exc
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise UserError(f"{rel} is not valid YAML: {exc}") from exc
    if len(docs) != 1:
        raise UserError(f"{rel} must contain a single YAML document")
    return docs[0]
