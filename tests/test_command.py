"""Command checks: exit code, streams, env, cwd, timeout."""

import sys
from pathlib import Path

from tests.conftest import run_text


def test_exit_code_stdout_and_stderr(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        f"""\
version: 1
checks:
  - name: marker
    type: command
    run: [{sys.executable!r}, -c, "import sys; print('agent-proof-ok'); sys.stderr.write('note')"]
    stdout_contains: agent-proof-ok
    stdout_matches: "ok$"
    stderr_contains: note
    stderr_not_contains: traceback
""",
    )
    assert report.ok, report.checks[0].message
    assert report.checks[0].details["exit_code"] == 0


def test_nonzero_exit_is_a_failure_unless_expected(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        f"""\
version: 1
checks:
  - name: boom
    type: command
    run: [{sys.executable!r}, -c, "import sys; print('nope'); sys.exit(3)"]
    stdout_contains: passed
""",
    )
    assert not report.ok
    assert "exited 3, expected 0" in report.checks[0].message
    assert "nope" in report.checks[0].message

    report = run_text(
        tmp_path,
        f"""\
version: 1
checks:
  - name: expected
    type: command
    run: [{sys.executable!r}, -c, "import sys; sys.exit(3)"]
    exit_code: 3
""",
    )
    assert report.ok


def test_env_and_cwd(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    report = run_text(
        tmp_path,
        f"""\
version: 1
checks:
  - name: env
    type: command
    run: [{sys.executable!r}, -c, "import os; print(os.environ['PROOF_MARK'])"]
    env:
      PROOF_MARK: alpha
    stdout_contains: alpha
    cwd: sub
""",
    )
    assert report.ok, report.checks[0].message


def test_timeout_kills_the_process(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        f"""\
version: 1
checks:
  - name: slow
    type: command
    run: [{sys.executable!r}, -c, "import time; time.sleep(5)"]
    timeout: 0.4
""",
    )
    assert not report.ok
    assert "timed out" in report.checks[0].message
    assert report.checks[0].details["timed_out"] is True


def test_shell_string_and_missing_command(tmp_path: Path) -> None:
    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: shell
    type: command
    run: "echo agent-proof-shell"
    stdout_contains: agent-proof-shell
""",
    )
    assert report.ok, report.checks[0].message

    report = run_text(
        tmp_path,
        """\
version: 1
checks:
  - name: missing
    type: command
    run: ["agent-proof-missing-command"]
""",
    )
    assert not report.ok
    assert "command not found" in report.checks[0].message
