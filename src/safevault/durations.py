from __future__ import annotations

from datetime import timedelta

from safevault.errors import InvalidDurationError


def parse_duration(value: str) -> timedelta:
    if len(value) < 2:
        raise InvalidDurationError(f"invalid duration: {value}")
    amount_text = value[:-1]
    suffix = value[-1]
    if suffix not in {"m", "h", "d"} or not amount_text.isdigit():
        raise InvalidDurationError(f"invalid duration: {value}")
    amount = int(amount_text)
    if amount <= 0:
        raise InvalidDurationError(f"invalid duration: {value}")
    if suffix == "m":
        return timedelta(minutes=amount)
    if suffix == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)
