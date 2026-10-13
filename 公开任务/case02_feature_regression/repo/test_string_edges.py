import pytest
import string_utils as strings


@pytest.mark.parametrize("s,max_len", [("", 0), ("", 4), ("x", 4), ("abc", 3), ("abcdef", -1)])
def test_invalid_limit_precedes_noop(s, max_len):
    with pytest.raises(ValueError):
        strings.truncate_middle(s, max_len)


@pytest.mark.parametrize("s,limit", [("", 5), ("x", 5), ("abcdef", 6), ("你好世界", 5)])
def test_short_and_equal(s, limit):
    assert strings.truncate_middle(s, limit) == s


@pytest.mark.parametrize("limit,expected", [(5, "a...z"), (6, "ab...z"), (7, "ab...yz"),
                                         (8, "abc...yz"), (11, "abcd...wxyz")])
def test_both_sides_and_balance(limit, expected):
    assert strings.truncate_middle("abcdefghijklmnopqrstuvwxyz", limit) == expected


def test_unicode_truncation():
    assert strings.truncate_middle("甲乙丙丁戊己庚辛壬癸", 6) == "甲乙...癸"
