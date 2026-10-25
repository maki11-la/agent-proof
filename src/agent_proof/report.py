"""Human-readable and JSON reports."""

from __future__ import annotations

import json
import shutil

from agent_proof import __version__
from agent_proof.models import Report
from agent_proof.util import format_ms, json_safe


class Paint:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def good(self, text: str) -> str:
        return self._wrap("1;32", text)

    def bad(self, text: str) -> str:
        return self._wrap("1;31", text)


def render_human(report: Report, *, color: bool, quiet: bool) -> str:
    paint = Paint(color)
    title = report.name or "proof"
    lines = [
        paint.bold(f"Agent Proof {report.version}"),
        f"{title}  {paint.dim(report.spec)}",
    ]
    if report.description:
        lines.append(paint.dim(" ".join(report.description.split())))
    lines.append("")
    shown = 0
    for item in report.checks:
        if quiet and item.ok:
            continue
        shown += 1
        status = paint.good("PASS") if item.ok else paint.bad("FAIL")
        timing = paint.dim(format_ms(item.duration_ms))
        lines.append(f"  {status}  {item.name}  {timing}")
        for line in item.message.splitlines() or [""]:
            lines.append(f"        {line}")
        lines.append("")
    if shown == 0:
        lines.append("")
    width = min(72, max(24, shutil.get_terminal_size((80, 24)).columns))
    lines.append(paint.dim("─" * width))
    lines.append(_summary(report, paint))
    return "\n".join(lines).rstrip() + "\n"


def _summary(report: Report, paint: Paint) -> str:
    summary = report.summary
    label = paint.good("PASS") if report.ok else paint.bad("FAIL")
    text = (
        f"{label}  {summary.passed} passed, {summary.failed} failed, "
        f"{summary.total} total"
    )
    if report.stopped_early:
        skipped = summary.planned - summary.total
        text += f", {skipped} not run"
    text += f"  in {format_ms(summary.duration_ms)}"
    return text


def report_payload(report: Report) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": report.ok,
        "tool": report.tool,
        "version": report.version,
        "spec": report.spec,
        "name": report.name,
        "description": report.description,
        "root": report.root,
        "stopped_early": report.stopped_early,
        "summary": {
            "passed": report.summary.passed,
            "failed": report.summary.failed,
            "total": report.summary.total,
            "planned": report.summary.planned,
            "duration_ms": report.summary.duration_ms,
        },
        "checks": [
            {
                "name": item.name,
                "type": item.type,
                "ok": item.ok,
                "duration_ms": item.duration_ms,
                "message": item.message,
                "details": json_safe(item.details),
            }
            for item in report.checks
        ],
    }
    if report.error:
        payload["error"] = report.error
    return payload


def render_json(report: Report) -> str:
    return json.dumps(report_payload(report), indent=2, ensure_ascii=False) + "\n"


def error_payload(message: str) -> dict[str, object]:
    return {
        "ok": False,
        "tool": "agent-proof",
        "version": __version__,
        "error": message,
        "checks": [],
    }


def render_error_json(message: str) -> str:
    return json.dumps(error_payload(message), indent=2, ensure_ascii=False) + "\n"
