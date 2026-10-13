# 基础版本验证记录

2026-10-13，Ubuntu WSL 2，Python 3.12.3，pytest 8.4.2，GNU patch 2.7.6。

单元测试命令：`bash run_unit.sh`（通过 WSL root 启动以挂载项目内临时目录）。
真实输出：`10 passed in 6.40s`。
测试涵盖路径越界、修改范围、命令白名单、写入前置条件、计划标题稳定、完成验证、上下文裁剪与完整日志、追加指令与拒绝、中断、符号链接越界、动作解析。
这些是本地单元测试，模拟模型测试不作为公开题模型轨迹或评分依据。

正式公开题证据位于 `public/attempt05/`，使用真实 DeepSeek 官方 API、固定 `deepseek-flash`、温度 0。
最终成绩以该目录 `summary.md` 和每题 `result.json` 为准。
先前各轮环境异常/中断记录均保留，未改写为成功记录。

正式评测结果：全部通过，5/5 分，86/86 个测试通过；五题日志、修改范围、过程要求及补丁还原检查均通过。

| 题目 | 功能测试 | 得分 |
| --- | --- | --- |
| case01_bug_fix | 11/11 | 1 |
| case02_feature_regression | 23/23 | 1 |
| case03_cross_file | 14/14 | 1 |
| case04_two_subtasks | 10/10 | 1 |
| case05_long_log | 28/28 | 1 |
