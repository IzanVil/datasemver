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
