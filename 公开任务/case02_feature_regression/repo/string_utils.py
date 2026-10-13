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
