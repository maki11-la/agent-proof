"""Run every check in a spec and collect a report."""

from __future__ import annotations

import time

from agent_proof import __version__
from agent_proof.checks import check_type, run_check
from agent_proof.gitutil import Runtime
from agent_proof.models import CheckResult, Report, Spec, Summary


def execute(
    spec: Spec,
    *,
    root,
    spec_label: str,
    fail_fast: bool = False,
) -> Report:
    runtime = Runtime(root=root)
    started = time.perf_counter()
    results: list[CheckResult] = []
    stopped = False
    for check in spec.checks:
        mark = time.perf_counter()
        try:
            result = run_check(check, runtime)
        except Exception as exc:  # noqa: BLE001  # a check bug must fail the proof, not crash it
            text = str(exc).strip() or type(exc).__name__
            result = CheckResult(
                name=check.name,
                type=check_type(check),
                ok=False,
                message=f"internal error: {text}",
            )
        result.duration_ms = max(0, int((time.perf_counter() - mark) * 1000))
        results.append(result)
        if not result.ok and fail_fast:
            stopped = True
            break
    failed = sum(1 for item in results if not item.ok)
    passed = len(results) - failed
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    return Report(
        ok=failed == 0,
        tool="agent-proof",
        version=__version__,
        spec=spec_label,
        name=spec.name,
        description=spec.description,
        root=str(root),
        summary=Summary(
            passed=passed,
            failed=failed,
            total=len(results),
            planned=len(spec.checks),
            duration_ms=duration_ms,
        ),
        checks=results,
        stopped_early=stopped,
    )
