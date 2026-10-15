from stats import (batch_summary, mean, median, moving_average, robust_center,
                   std, trim_outliers, variance, zscores)

SERIES_A = [12, 7, 3, 19, 25, 8, 14, 30, 22, 5, 17, 9, 28, 11, 2, 26, 15, 20, 6, 13]
SERIES_B = [101, 87, 94, 76, 110, 99, 83, 105, 92, 68, 115, 88, 97, 104, 79, 90]


def test_mean_series_a():
    assert mean(SERIES_A) == sum(SERIES_A) / len(SERIES_A)


def test_median_even_length():
    # 排序后中间两数为 13 和 14，中位数应为 13.5
    assert median(SERIES_A) == 13.5


def test_median_even_length_b():
    s = sorted(SERIES_B)
    expected = (s[7] + s[8]) / 2
    assert median(SERIES_B) == expected


def test_median_odd_length():
    assert median([5, 1, 9, 3, 7]) == 5


def test_median_two_elements():
    assert median([10, 20]) == 15.0


def test_variance_known():
    data = [2, 4, 4, 4, 5, 5, 7, 9]
    assert variance(data) == 4.0


def test_std_known():
    data = [2, 4, 4, 4, 5, 5, 7, 9]
    assert std(data) == 2.0


def test_robust_center_uses_median():
    data = [10, 11, 12, 13, 14, 15, 16, 200]
    assert robust_center(data) == 13.5


def test_zscores_zero_mean():
    zs = zscores(SERIES_A)
    assert abs(sum(zs)) < 1e-9


def test_moving_average_window3():
    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert moving_average(xs, 3) == [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
