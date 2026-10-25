"""Command-line interface for Agent Proof."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent_proof import __version__
from agent_proof.engine import execute
from agent_proof.report import render_error_json, render_human, render_json
from agent_proof.spec import SpecError, discover_spec, load_spec, resolve_root

STARTER = """\
version: 1
name: project proof
checks:
  - name: readme exists
    type: file
    path: README.md
    exists: true
    min_bytes: 1

  - name: tests pass
    type: command
    run: [python, -m, pytest, -q]
    timeout: 300
    stdout_contains: passed
"""

COMMANDS = {"run", "validate", "init"}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)
    argv = _insert_default_command(argv)
    parser = _parser()
    if not argv:
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return _init(args)
        if args.command == "validate":
            return _validate(args)
        return _run(args)
    except SpecError as exc:
        return _fail_spec(exc, json_output=getattr(args, "json", False))
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except BrokenPipeError:
            pass
        return 0


def _insert_default_command(argv: list[str]) -> list[str]:
    """Treat `agent-proof proof.yaml` as `agent-proof run proof.yaml`."""
    if not argv or argv[0].startswith("-") or argv[0] in COMMANDS:
        return argv
    return ["run", *argv]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-proof",
        description=(
            "Mechanically verify an agent's work against a declarative spec. "
            "No model calls."
        ),
        epilog=(
            "security: a command check runs the command in the spec, as you. "
            "A string run is a shell command (sh -c on macOS and Linux). "
            "Only run a spec you trust.\n"
            "exit codes: 0 all checks passed, 1 a check failed, "
            "2 the spec or the command line is invalid.\n"
            "examples:\n"
            "  agent-proof run proof.yaml\n"
            "  agent-proof proof.yaml --json\n"
            "  agent-proof init"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"agent-proof {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run the checks in a proof spec")
    _add_spec_argument(run)
    _add_run_flags(run)

    validate = sub.add_parser("validate", help="parse a spec without running checks")
    _add_spec_argument(validate)
    validate.add_argument("--json", action="store_true", help="print JSON instead of text")
    validate.add_argument("--root", help="project root for relative paths (overrides the spec)")

    init = sub.add_parser("init", help="write a starter proof.yaml")
    init.add_argument(
        "-o",
        "--output",
        default="proof.yaml",
        help="path to write (default: proof.yaml)",
    )
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    return parser


def _add_spec_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "spec",
        nargs="?",
        help=(
            "path to a proof spec (.yaml, .yml, or .json). "
            "Defaults to proof.yaml, proof.yml, .agent-proof.yaml, or agent-proof.yaml "
            "in the current directory."
        ),
    )


def _add_run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print a JSON report on stdout")
    parser.add_argument("--root", help="project root for relative paths (overrides the spec)")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop after the first failed check",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="in the text report, hide checks that passed",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize the text report (default: auto)",
    )
    parser.add_argument("--no-color", action="store_true", help="synonym for --color=never")


def _run(args: argparse.Namespace) -> int:
    spec_path, label = _locate(args.spec)
    spec = load_spec(spec_path)
    root = _ensure_root(spec, spec_path, args.root)
    report = execute(
        spec,
        root=root,
        spec_label=label,
        fail_fast=bool(args.fail_fast or spec.fail_fast),
    )
    if args.json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(
            render_human(report, color=_color_enabled(args), quiet=bool(args.quiet))
        )
    return 0 if report.ok else 1


def _validate(args: argparse.Namespace) -> int:
    spec_path, label = _locate(args.spec)
    spec = load_spec(spec_path)
    root = _ensure_root(spec, spec_path, args.root)
    if args.json:
        payload = {
            "ok": True,
            "tool": "agent-proof",
            "version": __version__,
            "spec": label,
            "name": spec.name,
            "root": str(root),
            "checks": len(spec.checks),
            "fail_fast": spec.fail_fast,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        title = spec.name or "proof"
        print(f"ok  {title}")
        print(f"spec: {label}")
        print(f"checks: {len(spec.checks)}")
        print(f"root: {root}")
    return 0


def _init(args: argparse.Namespace) -> int:
    dest = Path(args.output).expanduser()
    if not dest.is_absolute():
        dest = Path.cwd() / dest
    if dest.exists() and not args.force:
        print(f"{dest} already exists (use --force to overwrite)", file=sys.stderr)
        return 2
    if dest.parent != Path(".") and not dest.parent.is_dir():
        print(f"directory does not exist: {dest.parent}", file=sys.stderr)
        return 2
    dest.write_text(STARTER, encoding="utf-8")
    print(f"wrote {dest}")
    return 0


def _locate(spec: str | None) -> tuple[Path, str]:
    if spec:
        return Path(spec), spec
    found = discover_spec()
    try:
        label = found.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        label = str(found)
    return found, label


def _ensure_root(spec, spec_path: Path, override: str | None):
    root = resolve_root(spec, spec_path, override)
    if not root.is_dir():
        raise SpecError([f"root does not exist: {root}"])
    return root


def _fail_spec(exc: SpecError, *, json_output: bool) -> int:
    message = "\n".join(exc.errors)
    if json_output:
        sys.stdout.write(render_error_json(message))
    else:
        print("agent-proof: spec error", file=sys.stderr)
        print(message, file=sys.stderr)
    return 2


def _color_enabled(args: argparse.Namespace) -> bool:
    if args.no_color or args.color == "never":
        return False
    if args.color == "always":
        return True
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()
