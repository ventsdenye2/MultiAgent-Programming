# 24371220：迷你编码智能体（基础版本）

仅实现四项基础能力，特色功能、特色对照实验和最终报告待后续阶段完成。
使用标准库直接调用 Chat Completions，自行实现消息组织、JSON 动作解析、计划和执行循环，不使用 Agent 框架。

基础版本已在 WSL 正式评测 `experiments/public/attempt05/` 中全部通过：5/5 分，86/86 个公开测试通过，五题过程、真实日志和补丁还原检查全部合格。另有 10/10 项基础机制单元测试通过。

## 环境

已在 Ubuntu WSL 2 验证 Python 3.12.3，项目内虚拟环境为 `.venv`，pytest 8.4.2，GNU patch 来自 Ubuntu 已有安装。
智能体本身没有第三方依赖；pytest 是验证依赖。`wheels/` 保存离线安装包。
Git 不跟踪虚拟环境、下载包和本机 WSL 配置备份。新克隆若缺少 `wheels/`，可先在 Windows 的课程根目录下载：`python -m pip download --no-cache-dir --dest 24371220/wheels pip pytest==8.4.2`，然后执行下面的 WSL 环境重建步骤。
首次重建环境（在本目录执行）：

```bash
python3 -m venv --without-pip .venv
.venv/bin/python setup_wsl.py
source .venv/bin/activate
patch --version
```

本机 WSL 网络原为 Mirrored，启动时失败并回退为无网络。经用户授权，用户级 `.wslconfig` 仅将 `networkingMode=mirrored` 改为 `networkingMode=nat`，其余选项保留；原始配置备份为 `wslconfig.original`。
虚拟环境、下载包、评测副本和临时目录均位于本项目。不要提交 `.venv/`。

## 模型配置

入口同目录 `config.json` 使用 `deepseek-flash`、官方根地址 `https://api.deepseek.com`、密钥环境变量名 `DEEPSEEK_API_KEY`。
`--model` 必须与配置一致。密钥仅存于进程环境，不写入任何项目文件。运行前在 WSL 终端输入：

```bash
read -rsp 'DeepSeek API Key: ' DEEPSEEK_API_KEY; echo
export DEEPSEEK_API_KEY
```

默认最多 60 轮，温度 0，单次输出预算 4096 token，网络超时 90 秒，工具命令超时 120 秒。预算耗尽、模型失败或验证失败返回非零。

## 使用

从课程根目录创建新副本，再进入其 `run` 目录运行入口。每次必须使用新的启动目录，不覆盖已有日志或补丁：

```bash
source 24371220/.venv/bin/activate
python tools/check_submission.py --case case01_bug_fix --prepare 24371220/experiments/public/manual01
cd 24371220/experiments/public/manual01/run
python ../../../../agent.py --task ../work/task.md --repo ../work/repo --model deepseek-flash --auto
```

不加 `--auto` 则交互执行：每轮可以输入新指令；`/add 指令` 追加要求，`/status` 查看计划，`/quit` 或 Ctrl+C 中断。
写入前显示完整新内容，命令执行前显示参数，输入 `y` 确认或 `n` 拒绝。追加指令会取消当前待确认动作，让模型重新决定。
自动模式全程不读取键盘。允许修改的文件从题面“只修改/只允许修改”行提取；其他格式的任务可显式使用 `--allow file.py`。

工具：`list` 列目录，`read` 完整读取，`write` 完整写入允许文件，`command` 执行完整 pytest 或 `run_checks.py`，`plan` 更新状态，`finish` 提交完成结果。
写入限制在 `--repo` 内，拒绝越界、隐藏路径、测试文件和符号链接越界。不提供 shell、任意 Python 脚本或删除命令。
程序要求先计划、读业务文件、运行基线测试再写入；写入后重置验证状态，最后只有测试、诊断和全部计划完成才退出 0。
第四题的独立写入、净额中间验证与计划更新顺序由任务/系统提示约束，并由课程评测器核验。

## 上下文与日志

每次请求保留系统提示、完整题面、追加指令和当前计划/验证状态。单条结果超过 4500 字符时保留头尾；总 content 超过 15000 字符时从最早的动作/结果对开始移除，硬上限 16000。
优先保留当前失败线索和原始目标；头尾裁剪可能丢失中段关键线索，模型可再次读取文件。
`context_clip` 记录原长度、保留文本及舍弃中段；`context_drop` 记录移除消息和保留消息。完整原输出始终在日志中。

`run.log` 是逐操作刷盘的 UTF-8 JSONL。`model_request.body` 为真实请求，不含鉴权头；`model_response.response` 为完整返回（含 reasoning_content）；`usage` 原样使用 API 上报字段及实际模型，不估算缺失值。
`file_read/file_write` 包含完整路径和内容，`command_result` 包含真实解释器 argv、rc、完整 stdout/stderr，`plan.items` 包含标题和 todo/doing/done。
追加指令、工具错误、中断和预算耗尽使用附加事件。日志保存在启动目录，不写入业务仓库。
`patch.diff` 基于运行开始快照生成统一 diff，支持 GNU patch `-p1`，失败和中断也保存已有改动。

核心范围：`agent.py` 的 `SYSTEM` 和 `Agent`（初始化、消息组织、上下文处理、动作解析、计划调度、交互和循环），194 个非空非纯注释物理行。`main` 的参数/配置解析和 `runtime.py` 底层传输、日志、文件、命令及补丁为辅助代码。

## 验证

单元测试明确使用模拟模型测试协议，不冒充模型轨迹或公开题成绩：

```bash
bash run_unit.sh
```

从课程根目录执行五题正式评测，临时目录也限定在项目内：

```bash
bash 24371220/run_public.sh new_attempt
```

项目位于 Windows 挂载盘：pytest 默认 fd 捕获与此盘上的临时文件出现 `FileNotFoundError`。评测器会清除 PYTEST_ADDOPTS，因而不能靠改变捕获方式解决。运行脚本在项目内的 `experiments/linux_tmp` 挂载最多 256MB 的 tmpfs，子进程在同一挂载环境中运行，结束自动卸载。需要 sudo 挂载权限，临时文件仍位于项目路径，不修改评测器或测试；单元测试脚本使用独立的 128MB 临时挂载。

`--out` 必须不存在。成绩和每题过程证据见相应轮次的 `summary.md`、`result.json`、`evidence.json`；完整模型日志和补丁随该轮保留。`attempt01` 是 Windows 尝试，课程评测器因 POSIX `os.killpg` 不兼容 Windows 中断，不能视为五题成绩；`attempt02` 至 `attempt04` 均因挂载盘临时文件兼容问题或挂载命名空间问题中断，保留原记录；`attempt05` 开始使用同一进程环境内的 tmpfs 正式运行。

实现依据：课程题目、README、日志格式说明和公开工具协议。尚未完成的特色功能及报告不宣称已完成。
