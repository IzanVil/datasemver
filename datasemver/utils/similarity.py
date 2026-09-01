"""Similarity measures used to detect renamed columns."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher

NAME_WEIGHT = 0.4
VALUE_WEIGHT = 0.6


def name_similarity(left: str, right: str) -> float:
    """Ratio between two column names, ignoring case and word separators."""
    return SequenceMatcher(None, _normalize(left), _normalize(right)).ratio()


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    """Overlap between two sets of values."""
    left_set, right_set = set(left), set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def column_similarity(
    old_name: str,
    new_name: str,
    old_values: Iterable[str] | None,
    new_values: Iterable[str] | None,
) -> float:
    """Combined name and content similarity between two columns."""
    names = name_similarity(old_name, new_name)
    if old_values is None or new_values is None:
        return names
    return NAME_WEIGHT * names + VALUE_WEIGHT * jaccard(old_values, new_values)


def _normalize(value: str) -> str:
    return value.lower().replace("_", "").replace("-", "").replace(" ", "")
