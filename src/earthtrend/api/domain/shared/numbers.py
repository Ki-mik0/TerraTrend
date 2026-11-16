"""Find numbers in text and in fact values, so generated text can be checked against the facts.

Signs and comma decimals are kept. Digits inside ids (`case_1`, `merra2_t2m`, `v1.2`) are not numbers.
"""

from __future__ import annotations

import math
import re
from typing import Any

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")


def normalize_number(token: str) -> str:
    token = token.replace(",", ".")
    if "." in token:
        text = format(float(token), "f").rstrip("0").rstrip(".")
    else:
        text = str(int(token))
    return "0" if text == "-0" else text


def numbers_in(text: str) -> set[str]:
    return {normalize_number(token) for token in _NUMBER.findall(text)}


def collect_numbers(value: Any) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return {normalize_number(str(value))}
    if isinstance(value, str):
        return numbers_in(value)
    if isinstance(value, dict):
        return set().union(*(collect_numbers(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return set().union(*(collect_numbers(item) for item in value)) if value else set()
    return set()


def with_roundings(numbers: set[str], max_decimals: int = 6) -> set[str]:
    """The numbers plus every rounding of them to 0..max_decimals places, so prose may round a fact."""
    out = set(numbers)
    for token in numbers:
        value = float(token)
        for places in range(max_decimals + 1):
            out.add(normalize_number(f"{round(value, places):.{places}f}"))
    return out


def readable(value: float) -> str:
    """A fact rounded for prose: two decimals, or three significant figures for small values."""
    if value == 0 or abs(value) >= 0.1:
        return normalize_number(f"{value:.2f}")
    places = min(6, 2 - math.floor(math.log10(abs(value))))
    return normalize_number(f"{value:.{places}f}")
