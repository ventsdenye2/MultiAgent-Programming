"""对拍脚本：把 stats.py 的输出与内置参考实现逐项比对，打印完整差异报告。

用法：python run_checks.py
退出码 0 表示全部一致，1 表示存在不一致。
"""
import stats


def ref_median(xs):
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def ref_mean(xs):
    return sum(xs) / len(xs)


def main():
    mismatches = 0
    checks = 0
    for seed in range(120):
        # 确定性伪随机序列，长度有奇有偶
        n = 6 + (seed * 7) % 30
        xs = [((seed * 31 + i * 17) % 89) + (i % 4) * 0.5 for i in range(n)]
        got = stats.median(xs)
        want = ref_median(xs)
        checks += 1
        if got != want:
            mismatches += 1
            print(f"[MISMATCH] batch={seed:03d} len={n} "
                  f"median got={got!r} want={want!r} input={xs!r}")
        got_mean = stats.mean(xs)
        want_mean = ref_mean(xs)
        checks += 1
        if abs(got_mean - want_mean) > 1e-9:
            mismatches += 1
            print(f"[MISMATCH] batch={seed:03d} mean got={got_mean!r} "
                  f"want={want_mean!r}")
        summary = stats.batch_summary([xs])[0]
        checks += 1
        if summary[1] != want:
            mismatches += 1
            print(f"[MISMATCH] batch={seed:03d} batch_summary median "
                  f"got={summary[1]!r} want={want!r}")
    print(f"\n共 {checks} 项检查，{mismatches} 项不一致")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
