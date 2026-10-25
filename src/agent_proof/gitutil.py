"""Git operations used by file and git checks. No network, no prompts."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GitError(Exception):
    """The check cannot be decided because git itself failed."""


def git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    return env


def git_bytes(repo: Path, args: list[str]) -> bytes:
    if shutil.which("git") is None:
        raise GitError("git is not installed")
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            check=False,
            env=git_env(),
        )
    except OSError as exc:
        raise GitError(f"failed to run git: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(err or f"git exited {proc.returncode}")
    return proc.stdout


def find_repo(start: Path) -> Path:
    if shutil.which("git") is None:
        raise GitError("git is not installed")
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            check=False,
            env=git_env(),
            text=True,
        )
    except OSError as exc:
        raise GitError(f"failed to run git: {exc}") from exc
    if proc.returncode != 0:
        raise GitError(f"{start} is not inside a git repository")
    return Path(proc.stdout.strip())


def ensure_ref(repo: Path, ref: str) -> None:
    if shutil.which("git") is None:
        raise GitError("git is not installed")
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        check=False,
        env=git_env(),
    )
    if proc.returncode != 0:
        raise GitError(f"git ref {ref!r} was not found")


def _split_z(blob: bytes) -> list[str]:
    if not blob:
        return []
    parts = blob.split(b"\0")
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    return [part.decode("utf-8", "replace") for part in parts if part != b""]


def changed_paths(repo: Path, base: str, *, include_untracked: bool) -> set[str]:
    """Paths that differ from `base` in the index or worktree, plus untracked files."""
    ensure_ref(repo, base)
    names: set[str] = set()
    names.update(
        _split_z(git_bytes(repo, ["diff", "--name-only", "--no-renames", "-z", base]))
    )
    names.update(
        _split_z(
            git_bytes(repo, ["diff", "--name-only", "--cached", "--no-renames", "-z", base])
        )
    )
    if include_untracked:
        names.update(
            _split_z(
                git_bytes(repo, ["ls-files", "--others", "--exclude-standard", "-z"])
            )
        )
    return names


def status_paths(repo: Path, pathspecs: list[str] | None, *, include_untracked: bool) -> list[str]:
    """Repo-relative paths with staged, unstaged, or (optionally) untracked changes."""
    untracked = "all" if include_untracked else "no"
    args = ["status", "--porcelain=v1", "-z", f"--untracked-files={untracked}", "--"]
    if pathspecs:
        args.extend(pathspecs)
    return _parse_porcelain_z(git_bytes(repo, args))


def _parse_porcelain_z(blob: bytes) -> list[str]:
    """Return every path mentioned in `git status --porcelain=v1 -z` output.

    Renames and copies contribute both the old and the new path. A path is
    enough for the dirty check; the XY status is not part of the spec.
    """
    paths: list[str] = []
    index = 0
    size = len(blob)
    while index < size:
        if index + 3 > size:
            break
        status = blob[index : index + 2].decode("utf-8", "replace")
        if blob[index + 2 : index + 3] != b" ":
            break
        index += 3
        end = blob.find(b"\0", index)
        if end < 0:
            paths.append(blob[index:].decode("utf-8", "replace"))
            break
        paths.append(blob[index:end].decode("utf-8", "replace"))
        index = end + 1
        if "R" in status or "C" in status:
            end = blob.find(b"\0", index)
            if end < 0:
                paths.append(blob[index:].decode("utf-8", "replace"))
                break
            paths.append(blob[index:end].decode("utf-8", "replace"))
            index = end + 1
    return paths


def commit_count(repo: Path, ref: str, pathspecs: list[str] | None) -> int:
    ensure_ref(repo, ref)
    args = ["rev-list", "--count", f"{ref}..HEAD"]
    if pathspecs:
        args.append("--")
        args.extend(pathspecs)
    out = git_bytes(repo, args).decode("utf-8", "replace").strip()
    try:
        return int(out)
    except ValueError as exc:
        raise GitError(f"unexpected git rev-list output: {out!r}") from exc


def repo_relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise GitError(f"{path} is outside the git repository ({repo})") from exc


def spec_pathspec(root: Path, repo: Path, spec_path: str) -> str:
    full = (root / spec_path).resolve(strict=False)
    try:
        rel = full.relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise GitError(f"{spec_path!r} is outside the git repository ({repo})") from exc
    return "." if rel == "" else rel


@dataclass
class Runtime:
    """Per-run cache so several checks share one `git diff`."""

    root: Path
    _repo: Path | None = None
    _repo_error: GitError | None = None
    _changed: dict[tuple[str, bool], set[str]] = field(default_factory=dict)

    def repo(self) -> Path:
        if self._repo_error is not None:
            raise self._repo_error
        if self._repo is None:
            try:
                self._repo = find_repo(self.root)
            except GitError as exc:
                self._repo_error = exc
                raise
        return self._repo

    def changed(self, base: str, include_untracked: bool) -> set[str]:
        key = (base, include_untracked)
        cached = self._changed.get(key)
        if cached is None:
            cached = changed_paths(self.repo(), base, include_untracked=include_untracked)
            self._changed[key] = cached
        return cached
