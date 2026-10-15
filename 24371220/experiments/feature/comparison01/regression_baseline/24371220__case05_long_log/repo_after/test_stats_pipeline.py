from stats import batch_summary, median, trim_outliers

# 长序列：失败时断言差异输出会非常长，撑大失败日志
LONG_1 = list(range(3, 200, 4)) + [7, 55, 91, 123, 33, 171, 45, 88, 12, 140]
LONG_2 = [((i * 37) % 211) + (i % 5) for i in range(80)]
LONG_3 = [50 + ((i * 13) % 97) - (i % 3) * 6 for i in range(64)]


def expected_median(xs):
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def test_median_long_1():
    assert median(LONG_1) == expected_median(LONG_1)


def test_median_long_2():
    assert median(LONG_2) == expected_median(LONG_2)


def test_median_long_3():
    assert median(LONG_3) == expected_median(LONG_3)


def test_batch_summary_medians():
    batches = [LONG_1, LONG_2, LONG_3]
    result = batch_summary(batches)
    medians = [r[1] for r in result]
    assert medians == [expected_median(b) for b in batches]


def test_batch_summary_full_output():
    batches = [LONG_1[:20], LONG_2[:24]]
    result = batch_summary(batches)
    assert len(result) == 2
    for (m, med, sd), b in zip(result, batches):
        assert abs(m - sum(b) / len(b)) < 1e-9
        assert med == expected_median(b)
        assert sd >= 0


def test_trim_outliers_keeps_bulk():
    data = LONG_2 + [10000]
    kept = trim_outliers(data, z=2.0)
    assert 10000 not in kept
    assert len(kept) >= len(data) - 2


def test_trim_outliers_result_length():
    data = LONG_3
    kept = trim_outliers(data, z=1.5)
    assert 0 < len(kept) <= len(data)
