# 工作区归档：2026-11-05

本次提交保留此前未归档的离线运行记录及 DSML 实现验证。历史失败和不完整运行保持原样，不重新判定成功。所有带 summary.json 的下列离线运行均记录 provider_calls=0。

| 运行 | 退出码 | 日志结果 |
|---|---:|---|
| [offline-20261029-123636](offline-20261029-123636/pytest.log) | 未记录 | 无完整结果；保留原始片段 |
| [offline-20261029-141841](offline-20261029-141841/pytest.log) | 1 | 1 failed, 41 passed in 175.33s (0:02:55) |
| [offline-20261029-142426](offline-20261029-142426/pytest.log) | 1 | 1 failed, 41 passed in 183.82s (0:03:03) |
| [offline-20261105-103840](offline-20261105-103840/pytest.log) | 1 | 1 failed, 8 passed in 118.43s (0:01:58) |
| [offline-20261105-103935](offline-20261105-103935/pytest.log) | 2 | 1 error in 2.42s |
| [offline-20261105-104033](offline-20261105-104033/pytest.log) | 1 | 2 failed, 3 passed in 64.77s (0:01:04) |
| [offline-20261105-104132](offline-20261105-104132/pytest.log) | 0 | 6 passed in 56.72s |
| [offline-20261105-150315](offline-20261105-150315/pytest.log) | 0 | 55 passed in 36.66s |
| [offline-20261105-150511](offline-20261105-150511/pytest.log) | 0 | 117 passed in 161.44s (0:02:41) |
| [offline-20261105-150743](offline-20261105-150743/pytest.log) | 1 | 2 failed, 27 passed in 95.35s (0:01:35) |
| [offline-20261105-150905](offline-20261105-150905/pytest.log) | 0 | 39 passed in 26.39s |
| [offline-20261105-151023](offline-20261105-151023/pytest.log) | 0 | 2 passed in 22.47s |

DSML 实现、验证顺序和边界见 [DSML_COMPAT.md](../../DSML_COMPAT.md)。150743 的两项失败是测试会话复用日志目录；夹具改用独立目录后，151023 两项重测通过。

[2026-11-04 预检](smolagents-20261104-183816-936615/protocol.json)记录 preflight_only=true、status=preflight_passed、results 为空；不代表真实模型验收。

保留每批 pytest.log、junit.xml、summary.json，以及预检顶层记录。重复的 offline-*/test-artifacts/ 和预检 workspace/ 保留在本地并由 .gitignore 排除；此前已跟踪的历史产物不撤销跟踪、不移动或删除。没有恢复暂停的真实评测。
