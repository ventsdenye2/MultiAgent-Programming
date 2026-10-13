# 任务：新增 truncate_middle 函数，既有功能不许退化

## 背景

`string_utils.py` 是一个字符串工具集，已有命名转换和单词计数三个函数及对应测试。

## 需求

在 `string_utils.py` 中新增函数 `truncate_middle(s, max_len)`，语义如下：

1. 先检查参数：无论 `s` 长短，若 `max_len < 5`，抛出 `ValueError`。
2. 参数有效且 `len(s) <= max_len` 时，原样返回 `s`。
3. 否则把中间截掉，保留头部和尾部，中间用 `...` 连接，返回串长度恰好等于 `max_len`。头部保留长度取 `(max_len - 3 + 1) // 2`，尾部保留剩余部分；按 Python 字符数处理 Unicode 字符串。

示例：`truncate_middle("abcdefghijklmnopqrstuvwxyz", 10)` 返回 `"abcd...xyz"`（长度 10）。

## 要求

1. 只修改 `string_utils.py`，不得修改测试文件。
2. 运行 `python -m pytest -q`，新增的规格测试与既有测试必须全部通过，既有功能不得退化。

## 执行与验证要求

1. 修改前，在工作仓库根目录运行完整 `python -m pytest -q`，保留失败输出。
2. 完成功能后再次运行同一命令，新增测试和既有测试都必须通过，并保留完整输出。不得用 -k 筛选或只运行个别测试。
