import pytest
from words import word_counts


def test_combining_marks_and_emoji():
    assert word_counts('\u0301A\u0301 😀 á\u0301 x\u200dy') == [('á', 1), ('á\u0301', 1), ('x', 1), ('y', 1)]


def test_numbers_casefold_order_and_no_compatibility_fold():
    assert word_counts('Σ σ ς Ⅳ iv ² 2 İ i\u0307') == [
        ('σ', 3), ('ⅳ', 1), ('iv', 1), ('²', 1), ('2', 1), ('i\u0307', 2)]


def test_apostrophes_separators_and_empty():
    assert word_counts("don't DON’T") == [('don', 2), ('t', 2)]
    assert word_counts(' _-😀\u0301') == []
    assert word_counts('') == []


@pytest.mark.parametrize('value', [b'abc', 123, [], {}])
def test_non_text(value):
    with pytest.raises(TypeError):
        word_counts(value)
