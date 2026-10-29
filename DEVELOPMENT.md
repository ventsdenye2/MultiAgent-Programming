# Code Agent 重开发分支

本工作目录从 `b5d2181` 创建，分支为 `rebuild/smolagents-eacm`。原工作区及其未提交文件保留，备份位于工作区的 `archive/code-agent-checkpoints/20261028-before-smolagents-rebuild/`。

当前入口是 [24371220/agent.py](24371220/agent.py)，默认运行内置的 smolagents 官方内核。安装、命令和验证边界见 [实现说明](24371220/README.md)，详细复用边界见 [架构说明](24371220/SMOLAGENTS_REBUILD.md)。

当前最终作业范围、已通过结果与正在运行的评测见 [当前验收进度](24371220/experiments/smolagents/CURRENT-STATUS.md)。

修改集中在 `24371220/course_agent/`。`24371220/vendor/smolagents/` 是已校验的官方源码，保持原样。不要把修复写进第三方目录；先检查是否可通过官方 Tool、回调、模型客户端参数或记忆转换接口完成。

每个独立的修复或验证阶段提交一次 Git commit。提交前运行相关离线回归、`verify_vendor.py` 和 `git diff --cached --check`。真实模型评测使用新的输出目录，保留失败轮次，不自动重试付费请求。
