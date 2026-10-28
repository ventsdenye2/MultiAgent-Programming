# v2 离线验证记录

2026-10-28，Windows，Python 3.13.9。

运行：`python -X utf8 -m pytest test_agent.py tests -q -rs --basetemp=.pytest-v2-delivery`。

结果：**62 passed，2 skipped，退出码 0**。两项符号链接测试因 Windows 创建符号链接权限不足跳过。pytest 结束后，环境中的 pyreadline3 在 Console 析构时打印了一条清理异常；测试退出码仍为 0，完整输出保存在 [verification-output.txt](verification-output.txt)，运行元数据见 [verification.json](verification.json)。测试临时目录已清理。

覆盖 legacy 回归、受限执行器与跨轮变量、工具边界与补丁、证据失效和上下文预算、模型 usage 与失败路径、Python/JSON 动作完整控制器流程，以及读取/写入/基线/最终验证门禁。模型传输使用模拟响应；验证命令与空文件补丁的 `git apply --check` 在临时仓库实际执行。`agent.py --help` 和 `git diff --check` 亦通过。

本轮没有真实模型 API 调用、课程评测或输入 token 效率结论。WSL 命令返回 `Wsl/E_ACCESSDENIED`，因此不宣称 WSL/Python 3.12 已验证。v2 保持显式启用，legacy 默认不变。

## 后续课程评测环境预检

同日通过沙箱外 WSL 调用解决访问限制，在 Ubuntu / Python 3.12.3 / pytest 8.4.2 下再次运行完整回归，结果 **64 passed**，含两项符号链接测试。原始输出见 [wsl-preflight.txt](wsl-preflight.txt)。课程论文依赖 poppler-utils 已安装；这一步仍是离线预检，不是正式模型评测成绩。
