# Code Agent

本目录是 Code Agent 的 Git 主工作目录。实际入口为 [24371220/agent.py](24371220/agent.py)，源码、配置、测试、报告和实验记录均保存在 `24371220/` 内。

工作区导航见 [agent.md](../../agent.md)。课程材料已移到 [实践01](../../题目要求/01/README.md) 和 [实践02](../../题目要求/02/README.md)。

## 版本与入口

| 版本 | 位置与说明 |
| --- | --- |
| legacy | 本目录内的原始自研实现；不设置引擎参数或环境变量时默认使用 |
| v2 | 本目录内的 `24371220/codeagent/`；通过 `--engine v2` 显式启用 |
| smolagents + EA-CM | [实验工作树](../../experiments/code-agent-smolagents/24371220/README.md)，运行其自己的 `agent.py` |

两套工作目录属于同一个 Git 仓库的不同工作树。修改前确认目标目录和分支；本目录的测试与评测结果不能代替实验版本的结果。

## 文件导航

| 路径 | 内容 |
| --- | --- |
| [24371220/agent.py](24371220/agent.py) | CLI 入口、引擎选择、legacy 提示词与循环 |
| [24371220/runtime.py](24371220/runtime.py) | legacy 模型传输、工具执行、日志和补丁 |
| [24371220/context_selection.py](24371220/context_selection.py) | 诊断驱动的上下文选择与压缩 |
| [24371220/codeagent/](24371220/codeagent/) | v2 控制器、证据工作集、模型接口和受限执行器 |
| [24371220/test_agent.py](24371220/test_agent.py)、[tests/](24371220/tests/) | legacy、v2 和评测启动器的离线回归 |
| [24371220/docs/](24371220/docs/) | 架构、修复与验证说明 |
| [24371220/experiments/](24371220/experiments/) | 基础五题、特色对照、长上下文评测及临时运行目录 |
| [24371220/报告.md](24371220/报告.md)、[报告.pdf](24371220/报告.pdf) | 课程报告；`build_report.py` 为生成脚本 |
| `24371220/output/pdf/` | 报告页面预览图 |
| `24371220/report_tools/` | 生成报告使用的本地依赖 |
| `24371220/.venv/`、`wheels/` | WSL Python 环境与离线安装包 |

[实现详细说明](24371220/README.md) 保留了能力和历史实验背景；其中旧课程根目录命令应按本文的新路径执行。

## 环境与配置

使用 WSL/Linux、Python 3.12 和 GNU patch；实践02另需 `pdftotext`（Ubuntu 的 `poppler-utils`）。当前 Python 验证依赖见 [requirements.txt](24371220/requirements.txt)。

以下 Bash 命令均从 WSL 执行：

```bash
cd '/mnt/d/Muiti-Agent Programing/agents/code-agent/24371220'
.venv/bin/python agent.py --help
```

重建环境可运行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

模型配置在入口旁的 `config.json`，填写模型名、API 地址和密钥环境变量名。运行模型前在当前终端设置对应环境变量；密钥不写入源码或文档。迁移后的环境优先直接调用 `.venv/bin/python`；旧激活脚本可能保留原来的绝对路径。

## 离线验证

从 `24371220/` 运行 legacy、v2 和评测启动器测试：

```bash
.venv/bin/python -m pytest -q test_agent.py tests
```

Windows 挂载盘若遇 pytest 临时文件兼容问题，可使用已有的 `run_unit.sh` 在临时 tmpfs 上运行 legacy 测试；该脚本需要 sudo，且不包含全部 v2 测试。以上测试使用模拟模型，不调用付费 API。

## 课程评测

以下正式评测会调用模型，运行前准备环境变量并使用未存在的新输出轮次。

实践01五题评测可从 `24371220/` 启动：

```bash
bash run_public.sh attempt06
```

脚本定位到工作区的 `题目要求/01/`，调用其中的 `run_eval.py`，将结果保存到当前实现的 `experiments/public/attempt06/`。它使用 sudo 挂载临时 tmpfs，退出时卸载。

实践02先执行不调用模型的预检：

```bash
bash run_long_context_v2.sh --preflight-only
```

预检从 `题目要求/02/` 复制材料并检查源码、依赖和 PDF 读取。正式运行：

```bash
bash run_long_context_v2.sh
```

正式运行显式使用 v2/evidence，源码题最多20次模型请求，论文题最多40次，不自动重试。结果归档到 `experiments/long-context/v2-时间戳/`，WSL 原生运行目录同时保留。Windows 入口为 `run_long_context_v2.cmd`。

`experiment.py` / `run_experiment.sh` 用于实践01上下文特色对照；输出轮次仍在脚本中指定，重新运行前先换成新目录。

## 结果与维护

- 基础五题历史记录在 `experiments/public/attempt01`～`attempt05`；特色对照在 `experiments/feature/`。
- v2 长上下文历史记录在 `experiments/long-context/`；以各轮原始结果和过程证据为准。
- [evaluation-reliability.md](24371220/docs/evaluation-reliability.md) 记录已知运行问题与历史复测边界；本次路径调整不重新认定成绩。
- 修改实现保留在 `24371220/`，公共工具使用工作区的 [Agent Inspector](../../tools/agent-inspector/README.md)。
- 保留历史运行日志中的原路径，避免覆盖既有报告和评测输出。
