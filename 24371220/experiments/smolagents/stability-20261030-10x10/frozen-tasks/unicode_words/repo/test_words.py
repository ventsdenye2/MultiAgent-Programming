import pytest
from words import word_counts


def test_canonical_equivalence_and_casefold():
    assert word_counts('Café CAFE\u0301 Straße STRASSE') == [('café', 2), ('strasse', 2)]


def test_scripts_numbers_and_boundaries():
    assert word_counts('中文 中文 １２ a_b a-b') == [('中文', 2), ('１２', 1), ('a', 2), ('b', 2)]


def test_input_type():
    with pytest.raises(TypeError):
        word_counts(None)
