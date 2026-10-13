"""数据统计管线：基础统计量与批处理标准化。"""


def mean(xs):
    if not xs:
        raise ValueError("empty sequence")
    return sum(xs) / len(xs)


def median(xs):
    if not xs:
        raise ValueError("empty sequence")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return s[mid]


def variance(xs):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / len(xs)


def std(xs):
    return variance(xs) ** 0.5


def zscores(xs):
    m = mean(xs)
    sd = std(xs)
    if sd == 0:
        return [0.0 for _ in xs]
    return [(x - m) / sd for x in xs]


def moving_average(xs, k):
    if k <= 0:
        raise ValueError("window must be positive")
    return [mean(xs[i:i + k]) for i in range(len(xs) - k + 1)]


def robust_center(xs):
    """抗离群点的中心估计：中位数。"""
    return median(xs)


def trim_outliers(xs, z=2.0):
    """去掉 |z 分数| 超过阈值的点，返回保留的元素。"""
    zs = zscores(xs)
    return [x for x, zv in zip(xs, zs) if abs(zv) <= z]


def batch_summary(batches):
    """对每个批次输出 (均值, 中位数, 标准差)。"""
    return [(mean(b), median(b), std(b)) for b in batches]
