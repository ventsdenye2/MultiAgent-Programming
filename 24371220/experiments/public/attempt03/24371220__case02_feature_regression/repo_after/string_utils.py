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
    """把字符串中间截掉，保留头尾并用 ``...`` 连接。

    ``max_len`` 小于 5 时抛出 ``ValueError``；否则当 ``len(s) <= max_len``
    时原样返回 ``s``，否则返回长度恰好为 ``max_len`` 的截断串。
    """
    if max_len < 5:
        raise ValueError("max_len must be at least 5")
    if len(s) <= max_len:
        return s
    head = (max_len - 3 + 1) // 2
    tail = max_len - 3 - head
    return s[:head] + "..." + (s[len(s) - tail:] if tail else "")
