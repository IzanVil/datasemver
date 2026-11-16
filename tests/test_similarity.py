from datasemver.utils.similarity import column_similarity, jaccard, name_similarity


def test_name_similarity_ignores_case_and_separators():
    assert name_similarity("user_name", "UserName") == 1.0
    assert name_similarity("user-name", "user name") == 1.0
    assert name_similarity("country", "score") <= 0.5


def test_jaccard_of_disjoint_and_identical_sets():
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0
    assert jaccard(["a", "b"], ["c"]) == 0.0
    assert jaccard(["a", "b"], ["b", "c"]) == 1 / 3


def test_jaccard_of_an_empty_side_is_zero():
    assert jaccard([], ["a"]) == 0.0
    assert jaccard(["a"], []) == 0.0


def test_column_similarity_without_values_uses_the_name_only():
    assert column_similarity("user_name", "username", None, None) == 1.0
    assert column_similarity("user_name", "username", ["ana"], None) == 1.0


def test_column_similarity_weighs_values_more_than_the_name():
    same_values = column_similarity("legacy_code", "tag", ["a", "b"], ["a", "b"])
    same_name = column_similarity("legacy_code", "legacy_code", ["a"], ["z"])

    assert same_values > same_name


def test_the_fast_pairing_scores_every_pair_exactly_as_the_slow_one_does():
    """`rename_candidates` is only allowed to be quicker, never to disagree."""
    import random

    from datasemver.utils.similarity import rename_candidates

    random.seed(20260116)
    alphabet = "abcde_- "

    def name():
        return "".join(random.choice(alphabet) for _ in range(random.randint(1, 9)))

    def values():
        pool = ["a", "b", "c", "d", "e", "f"]
        return None if random.random() < 0.3 else random.sample(pool, random.randint(0, 5))

    old = {f"{name()}{index}": values() for index in range(60)}
    new = {f"{name()}{index}": values() for index in range(60)}

    for threshold in (0.3, 0.55, 0.7, 0.9):
        slow = {
            (left, right): column_similarity(left, right, old[left], new[right])
            for left in old
            for right in new
        }
        expected = {pair: score for pair, score in slow.items() if score >= threshold}

        found = {
            (left, right): score for score, left, right in rename_candidates(old, new, threshold)
        }

        assert found == expected, threshold
