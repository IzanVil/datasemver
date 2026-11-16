"""Similarity measures used to detect renamed columns."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from difflib import SequenceMatcher

NAME_WEIGHT = 0.4
VALUE_WEIGHT = 0.6

# Pairing every removed column with every added one is a product, and the product is what a
# file chooses: a 20 kB header of 2,000 columns renamed wholesale is four million pairs, and
# took eighty seconds. Past this many the pairing is not attempted, since no one reads four
# hundred renames as a rename either.
MAX_RENAME_PAIRS = 250_000
# Floating point has the last word on a score that lands exactly on a threshold, so a bound
# derived from it is given this much room rather than ruling out a pair by one ulp.
_EPSILON = 1e-9


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


def rename_candidates(
    old: Mapping[str, Sequence[str] | None],
    new: Mapping[str, Sequence[str] | None],
    threshold: float,
) -> list[tuple[float, str, str]]:
    """Every pair of an old and a new column that scores at least `threshold`.

    Scores exactly what `column_similarity` does, to the last digit, for every pair that
    reaches the threshold; it only avoids the work of the pairs that cannot. A name is the
    expensive half, so the cheap half goes first: the values of each column are made a set once
    rather than once per pair, and from them the lowest name score that could still reach the
    threshold is known, which most pairs fail on the two bounds `SequenceMatcher` gives for
    nothing before the ratio itself is computed.

    The mappings are column name to the values that were kept for it, or `None` for a column
    that has too many to be a signal.
    """
    old_names = {name: _normalize(name) for name in old}
    old_values = {name: None if values is None else set(values) for name, values in old.items()}
    candidates: list[tuple[float, str, str]] = []

    for new_name, raw_values in new.items():
        new_values = None if raw_values is None else set(raw_values)
        matcher = SequenceMatcher(None)
        matcher.set_seq2(_normalize(new_name))
        for old_name, left in old_values.items():
            if left is None or new_values is None:
                overlap = None
                needed = threshold
            else:
                overlap = _overlap(left, new_values)
                needed = (threshold - VALUE_WEIGHT * overlap) / NAME_WEIGHT
            if needed > 1.0 + _EPSILON:
                continue
            matcher.set_seq1(old_names[old_name])
            if matcher.real_quick_ratio() < needed - _EPSILON:
                continue
            if matcher.quick_ratio() < needed - _EPSILON:
                continue
            names = matcher.ratio()
            score = names if overlap is None else NAME_WEIGHT * names + VALUE_WEIGHT * overlap
            if score >= threshold:
                candidates.append((score, old_name, new_name))
    return candidates


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
