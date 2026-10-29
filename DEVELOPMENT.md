# Code Agent 开发导航

这是当前长期维护的编码 agent。日常开发代码位于 [24371220/](24371220/)，该目录的学号名称继续保留，以兼容课程提交和原有实验记录。

## 从哪里开始

| 位置 | 内容 |
| --- | --- |
| [24371220/agent.py](24371220/agent.py) | CLI 入口、系统提示与 agent 主循环 |
| [24371220/runtime.py](24371220/runtime.py) | 模型传输、工具执行、日志和补丁 |
| [24371220/context_selection.py](24371220/context_selection.py) | 上下文选择与压缩 |
| [24371220/test_agent.py](24371220/test_agent.py) | 使用模拟模型的本地单元测试 |
| [24371220/README.md](24371220/README.md) | 当前实现能力、环境配置与运行方式 |
| [24371220/experiments/](24371220/experiments/) | 历史公开评测、对照实验及结果 |
| [README.md](README.md) | 原始课程与基础评测说明 |
| [../../materials/long-context/README.md](../../materials/long-context/README.md) | 下一阶段的长论文、源码阅读与长上下文评测 |
| [../../tools/agent-inspector/README.md](../../tools/agent-inspector/README.md) | 查看真实运行日志与模型输入输出 |

## 本地验证

在 WSL 中进入本仓库的 24371220/，执行已有的单元测试脚本：

```bash
cd '/mnt/d/Muiti-Agent Programing/agents/code-agent/24371220'
sudo -v
bash run_unit.sh
```

该脚本直接使用项目内的 `.venv/bin/python`，并为测试临时挂载 tmpfs，需要 sudo 的挂载权限。测试使用模拟模型。

直接检查 CLI 参数可以执行：

```bash
.venv/bin/python agent.py --help
```

目录迁移保留了原虚拟环境。其 activate、pip 等脚本可能包含旧的绝对路径；使用上面的直接解释器方式。如需通过 activate 激活，先参照实现 README 在新位置重建环境。

## 后续开发的放置方式

当前实现持续在 24371220/ 内迭代；配置与辅助模块从入口旁加载。项目专用测试、实验、日志和报告也留在本仓库中，沿用既有 experiments/ 结构。新增评测使用新的输出轮次。

长上下文实践的评测命令在 materials/long-context/ 中执行，
`--agent` 指向 `../../agents/code-agent/24371220/agent.py`。评测器需要的参数与依赖见对应材料说明。

共享工具统一从工作区 tools/ 使用；后续另一个 agent 放在 agents/ 下独立目录。

本次整理保留 agent 源码、评测器、模型配置和历史结果；未提交或推送代码。迁移详情见 [工作区目录说明](../../docs/FOLDER_LAYOUT.md)。
