"""字符串工具集。"""


def snake_to_camel(s):
    """下划线命名转小驼峰：foo_bar -> fooBar。"""
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def camel_to_snake(s):
    """驼峰转下划线：fooBar -> foo_bar。"""
    out = []
    for ch in s:
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out).lstrip("_")


def count_words(s):
    """按空白统计单词数。"""
    return len(s.split())


def truncate_middle(s, max_len):
    """中间截断：保留首尾，中间以 ``...`` 连接，结果长度恰为 max_len。

    若 max_len < 5 抛出 ValueError；若 len(s) <= max_len 原样返回。
    """
    if max_len < 5:
        raise ValueError("max_len must be at least 5")
    if len(s) <= max_len:
        return s
    head_len = (max_len - 3 + 1) // 2
    tail_len = max_len - 3 - head_len
    return s[:head_len] + "..." + s[len(s) - tail_len:]
