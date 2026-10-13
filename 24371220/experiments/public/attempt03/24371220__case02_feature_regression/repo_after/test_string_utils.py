import pytest

from string_utils import camel_to_snake, count_words, snake_to_camel


def truncate_middle(*args):
    # 延迟导入，使新增函数缺失时仍可运行既有功能回归。
    from string_utils import truncate_middle as implementation
    return implementation(*args)


# ---- 既有功能回归 ----

def test_snake_to_camel():
    assert snake_to_camel("foo_bar_baz") == "fooBarBaz"


def test_camel_to_snake():
    assert camel_to_snake("fooBar") == "foo_bar"


def test_count_words():
    assert count_words("  hello  world  again ") == 3


# ---- 新增功能规格 ----

def test_truncate_no_op():
    assert truncate_middle("short", 10) == "short"


def test_truncate_exact_length():
    result = truncate_middle("abcdefghijklmnopqrstuvwxyz", 10)
    assert result == "abcd...xyz"
    assert len(result) == 10


def test_truncate_boundary_equal():
    assert truncate_middle("12345", 5) == "12345"


def test_truncate_min_length():
    result = truncate_middle("abcdefghij", 5)
    assert result == "a...j"


def test_truncate_too_small_raises():
    with pytest.raises(ValueError):
        truncate_middle("abcdefghij", 4)
