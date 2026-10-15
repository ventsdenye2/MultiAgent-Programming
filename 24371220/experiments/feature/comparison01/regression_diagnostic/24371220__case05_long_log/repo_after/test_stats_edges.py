import pytest
import stats


@pytest.mark.parametrize("xs,expected", [([2], 2), ([2, 8], 5), ([-8, -2], -5),
                                      ([1, 1, 4, 4], 2.5), ([.1, .7], .4), ([9, 1, 5], 5)])
def test_median_general(xs, expected):
    assert stats.median(xs) == pytest.approx(expected)


def test_median_empty_contract():
    with pytest.raises(ValueError):
        stats.median([])


def test_input_order_preserved():
    xs = [9, 2, 7, 1]
    before = list(xs)
    stats.median(xs)
    stats.robust_center(xs)
    stats.batch_summary([xs])
    assert xs == before


def test_existing_constant_behaviour():
    assert stats.zscores([3, 3, 3]) == [0, 0, 0]
    assert stats.moving_average([1, 2], 3) == []


@pytest.mark.parametrize("k", [0, -1])
def test_invalid_window(k):
    with pytest.raises(ValueError):
        stats.moving_average([1, 2], k)
