"""Find numbers in text and in fact values, so generated text can be checked against the facts.

Signs and comma decimals are kept. Digits inside ids (`case_1`, `merra2_t2m`, `v1.2`) are not numbers.
"""

from __future__ import annotations

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
