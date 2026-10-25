"""Minimal JSON/YAML paths: dots, `[index]`, and digits-as-indexes on lists."""

from __future__ import annotations

from typing import Any


class PathLookupError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def parse_data_path(path: str) -> list[tuple[str, object]]:
    """Parse `server.port`, `items[0].name`, or `items.0.name`.

    A numeric dot-segment stays a key token. At lookup time it is an index
    when the current value is a list, and a string key when it is an object.
    Bracket indexes are always indexes.
    """
    if not isinstance(path, str) or path == "":
        raise ValueError("path must be a non-empty string")
    tokens: list[tuple[str, object]] = []
    index = 0
    size = len(path)
    if path[0] == "[":
        index = _read_index(path, index, tokens)
    elif path[0] == ".":
        raise ValueError(f"invalid path {path!r}")
    else:
        index = _read_key(path, index, tokens)
    while index < size:
        char = path[index]
        if char == "[":
            index = _read_index(path, index, tokens)
            continue
        if char == ".":
            index += 1
            if index >= size or path[index] in ".[":
                raise ValueError(f"invalid path {path!r}")
            index = _read_key(path, index, tokens)
            continue
        raise ValueError(f"invalid path {path!r}")
    if not tokens:
        raise ValueError(f"invalid path {path!r}")
    return tokens


def _read_key(path: str, index: int, tokens: list[tuple[str, object]]) -> int:
    start = index
    size = len(path)
    while index < size and path[index] not in ".[":
        index += 1
    if index == start:
        raise ValueError(f"invalid path {path!r}")
    tokens.append(("key", path[start:index]))
    return index


def _read_index(path: str, index: int, tokens: list[tuple[str, object]]) -> int:
    if index >= len(path) or path[index] != "[":
        raise ValueError(f"invalid path {path!r}")
    end = path.find("]", index + 1)
    if end < 0:
        raise ValueError(f"invalid path {path!r}")
    body = path[index + 1 : end]
    if not body.isdigit():
        raise ValueError(f"invalid path {path!r}")
    tokens.append(("index", int(body)))
    return end + 1


def lookup(data: object, path: str) -> Any:
    """Walk `data` by `path`. Raise PathLookupError when it cannot be walked."""
    current: Any = data
    position = ""
    for kind, value in parse_data_path(path):
        as_index = kind == "index" or (
            kind == "key"
            and isinstance(current, list)
            and isinstance(value, str)
            and value.isdigit()
        )
        if as_index:
            index = value if isinstance(value, int) else int(str(value))
            if not isinstance(current, list):
                target = position or "root"
                raise PathLookupError(f"{path}: {target} is not a list")
            if index >= len(current):
                raise PathLookupError(
                    f"{path}: index {index} is out of range (length {len(current)})"
                )
            current = current[index]
            position = f"{position}[{index}]"
            continue
        key = str(value)
        if not isinstance(current, dict):
            target = position or "root"
            raise PathLookupError(f"{path}: {target} is not an object")
        if key in current:
            chosen: object = key
        elif key.isdigit() and int(key) in current:
            chosen = int(key)
        else:
            raise PathLookupError(f"missing {path}")
        current = current[chosen]
        position = key if not position else f"{position}.{key}"
    return current
