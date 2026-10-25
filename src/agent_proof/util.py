"""Small helpers shared by the spec loader, checks, and report."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_CHARS = 2_000_000
DETAIL_TEXT_CHARS = 16_000

_DURATION = re.compile(r"^(?P<num>\d+(?:\.\d+)?)(?P<unit>ms|s|m|h|d)?$")


class UserError(Exception):
    """A single, already-written message for a check that cannot proceed."""


def parse_duration(value: object, *, require_unit: bool = False) -> float:
    """Return seconds. Bare numbers are seconds unless `require_unit` is set."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("expected a duration")
    if isinstance(value, (int, float)):
        if require_unit:
            raise ValueError("expected a duration like 30s, 5m, 2h, or 1d")
        seconds = float(value)
    else:
        match = _DURATION.fullmatch(value.strip())
        if match is None:
            raise ValueError("expected a duration like 30s, 5m, 2h, or 1d")
        unit = match.group("unit")
        if require_unit and unit is None:
            raise ValueError("expected a duration like 30s, 5m, 2h, or 1d")
        amount = float(match.group("num"))
        multiplier = {None: 1, "ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        seconds = amount * multiplier
    if seconds < 0:
        raise ValueError("duration must not be negative")
    return seconds


def format_duration(seconds: float) -> str:
    if seconds >= 1 and seconds % 86400 == 0:
        return f"{int(seconds // 86400)}d"
    if seconds >= 1 and seconds % 3600 == 0:
        return f"{int(seconds // 3600)}h"
    if seconds >= 1 and seconds % 60 == 0:
        return f"{int(seconds // 60)}m"
    if 0 < seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds == int(seconds):
        return f"{int(seconds)}s"
    return f"{seconds:g}s"


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc)


def coerce_datetime(value: object) -> datetime:
    """Accept an ISO-8601 string, a datetime, or a date (midnight UTC)."""
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(
                "expected an ISO-8601 timestamp such as 2026-10-24T00:00:00Z"
            ) from exc
        return as_utc(parsed)
    raise ValueError("expected an ISO-8601 timestamp such as 2026-10-24T00:00:00Z")


def format_utc(value: datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def require_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    if "\x00" in value or "\\" in value:
        raise ValueError(f"{field} must use forward slashes and must not contain NUL")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError(f"{field} must be a relative path")
    if any(part == ".." for part in posix.parts):
        raise ValueError(f"{field} must not contain '..'")
    return value


def is_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError:
        return False
    return True


def display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def show_value(value: object, limit: int = 180) -> str:
    if isinstance(value, datetime):
        text = format_utc(value)
    elif isinstance(value, date):
        text = value.isoformat()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def command_display(run: str | tuple[str, ...]) -> str:
    if isinstance(run, str):
        return run
    return " ".join(_display_arg(part) for part in run)


def _display_arg(part: str) -> str:
    if part and all(char.isalnum() or char in "._/:=+@,-" for char in part):
        return part
    return json.dumps(part, ensure_ascii=False)


def values_equal(actual: object, expected: object) -> bool:
    """Structural equality that does not treat bools as integers or 1 as 1.0."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if isinstance(expected, int) and not isinstance(expected, bool):
        return type(actual) is int and actual == expected
    if isinstance(expected, float):
        return type(actual) is float and actual == expected
    if expected is None:
        return actual is None
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(values_equal(left, right) for left, right in zip(actual, expected))
        )
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return False
        return all(values_equal(actual[key], expected[key]) for key in expected)
    if isinstance(expected, datetime) or isinstance(actual, datetime):
        return isinstance(actual, datetime) and isinstance(expected, datetime) and as_utc(actual) == as_utc(expected)
    return actual == expected


def clip_text(text: str, limit: int = DETAIL_TEXT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def clip_lines(text: str, limit: int = 8) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    if len(lines) <= limit:
        return "\n".join(lines)
    extra = len(lines) - limit
    return "\n".join([*lines[:limit], f"… ({extra} more lines)"])


def format_ms(duration_ms: int) -> str:
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    return f"{duration_ms / 1000:.2f}s"
