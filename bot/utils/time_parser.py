"""Time-string parsing utilities (e.g. ``1h30m``)."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"(?P<value>\d+)(?P<unit>[smhdw])")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str | None) -> int | None:
    """Return seconds, or None if input is empty/invalid."""
    if not text:
        return None
    text = text.strip().lower()
    if text.isdigit():
        return int(text)
    total = 0
    matched = False
    for m in _PATTERN.finditer(text):
        total += int(m.group("value")) * _UNITS[m.group("unit")]
        matched = True
    return total if matched else None


def humanize_seconds(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    parts: list[str] = []
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        qty, seconds = divmod(seconds, size)
        if qty:
            parts.append(f"{qty}{unit}")
    return " ".join(parts) or "0s"
