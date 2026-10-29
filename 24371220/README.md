# Code Agent：smolagents 官方内核 + EA-CM

默认入口直接使用内置的 **smolagents 1.26.0** 官方代码。自研部分负责上下文管理及课程工具适配。原版本保留为 `--engine legacy`，历史说明见 [README.legacy.md](README.legacy.md)。

详细来源、复用边界与验证口径见 [SMOLAGENTS_REBUILD.md](SMOLAGENTS_REBUILD.md)。

## 安装与校验

使用 WSL、Python 3.12、GNU patch 和 poppler-utils。将下面命令中的路径切换到当前提交目录。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python verify_vendor.py
.venv/bin/python lock_dependencies.py
```

Ubuntu 缺少 venv/ensurepip 时，先安装对应的 `python3.12-venv` 系统包；已有带 pip 的课程环境也可以用 `python -m pip --python 新环境/bin/python install -r requirements.txt` 安装到独立环境。依赖较多，建议将环境和运行副本放在 WSL 原生文件系统；数据结果会归档回项目。

`requirements.txt` 固定本轮实际验证的 37 项依赖。无需另外安装全局 smolagents；内置包包含官方提示词与许可证，启动时检查实际导入路径和版本。不要编辑 vendor 目录。

## 运行

配置文件仅保留模型、服务地址和密钥环境变量名，密钥通过环境变量提供。

```bash
.venv/bin/python agent.py --task /path/task.md --repo /path/repo --model deepseek-flash --auto
```

保持课程四参数接口。默认 `--context-mode evidence`；追加 `--context-mode upstream` 可使用官方完整记忆组织，其他课程约束和预算不变。追加 `--engine legacy` 运行旧入口；其上下文参数仍为 `baseline|diagnostic`。

默认自动识别基础题、源码题和论文题。普通工作副本可使用 `--profile generic --allow file.py` 明确范围。移除 `--auto` 后，写入和命令会展示动作并等待确认，可输入 `/status`、`/add 指令` 或 `/quit`。

输出目录为启动目录，必须使用新目录。生成：

- `run.log`：完整实际模型请求/响应、工具调用与结果、计划、阅读、笔记、上下文选择和 usage。
- `patch.diff`：与启动时允许编辑文件快照的实际差异。
- `run-result.json`：完成状态、失败原因、已知用量及完整性、未完成条件。
- `memory.json`：完整官方步骤记忆。
- `evidence.json`：来源、版本、范围、原文、笔记和实际呈现记录。

源码/论文分别限制 20/40 次实际模型请求，单请求完整 JSON 最多 32,000 字符。首轮固定 deepseek-flash、4096 输出、关闭思考与自动重试。

默认开启官方 `use_structured_outputs_internally=True`：模型返回官方定义的 `thought/code` JSON，Python动作仍由官方解析器和执行器处理。DeepSeek Chat API通过 `response_format={"type":"json_object"}` 约束有效JSON；不宣称服务端严格校验JSON Schema。Markdown代码块配置保留给官方代码提取和历史回放。历史回放恢复原记录的输出模式，不改写已归档响应。允许导入的模块由执行器声明；文件和命令操作通过课程工具完成。

长上下文两题通过官方 `prompt_templates` 扩展点使用课程精简提示，保留 `thought/code` 协议、动态工具说明、官方解析与执行。论文每批原文在总结前保持可见，先更新主题笔记再继续阅读。

笔记规则按任务类型确定：源码笔记为20～3000字符，记录 `context_note`；论文笔记为20～1500字符，必须指定五个主题之一，记录 `section_note`。可选笔记键不会改变任务类型。
结构化模式写笔记时，`thought`保留笔记的完整原文，`code`把同一文字传给工具，保证课程检查能在真实响应中找到连续原文；不放宽原文、来源版本或先读后写的核验。

## 离线验证

```bash
.venv/bin/python run_smolagents_tests.py
.venv/bin/python evaluate_course.py --preflight-only
```

第一条运行真实官方内核和模拟 HTTP 回归，使用原生 Linux 临时目录，结果保存在 `experiments/smolagents/offline-*/`。第二条验证完整复制后的提交包、源码基线、PDF 提取和归档，默认不调用模型。

课程材料默认位于工作区的 `materials/long-context/`。测试异地复制时可通过 `COURSE_MATERIALS` 指定其绝对路径。课程运行器在当前工作区布局下使用同一份材料。

## 分阶段真实验收

以下命令会使用付费 Provider，应在确认运行阶段后执行；每次建立新输出目录，不自动重试：

```bash
.venv/bin/python evaluate_course.py --run-paid --stage smoke
.venv/bin/python evaluate_course.py --run-paid --stage basic
.venv/bin/python evaluate_course.py --run-paid --stage source
.venv/bin/python evaluate_course.py --run-paid --stage paper
```

smoke 为基础第 1 题；basic 为基础五题。结果归档在 `experiments/smolagents/smolagents-*/`，原生目录也保留。过程检查、功能得分和真实用量分别查看，不把离线测试通过记为课程通过。

可追加 `--request-limit N`，限制当前整批真实请求；基础五题共享这个计数，各题原有上限仍生效。结果中保存 `request-budget.json`。评测器拒绝同一项目并发运行；官方步骤回调观察到连续六步缺少实质进展且重复至多两种动作时提前退出，保留失败轨迹。不同动作构建执行器变量的正常过程仍可继续。

## 文件职责

| 文件 | 职责 |
|---|---|
| `agent.py` | 新旧引擎入口选择 |
| `course_agent/engine.py` | 官方 CodeAgent 接入、上下文钩子与禁止超额收尾请求 |
| `course_agent/progress.py` | 不可变任务状态；编辑门槛、状态显示和最终检查共享要求 |
| `course_agent/audit.py` | 官方 OpenAIModel/SDK 的 HTTP 审计与预算 |
| `course_agent/context.py` | EA-CM 发送视图 |
| `course_agent/evidence.py` | 证据去重、曝光、笔记与版本失效 |
| `course_agent/session.py` | 官方 Tool 接口、课程过程及 final_answer_checks |
| `course_agent/policy.py` | 题型、范围与预算 |
| `course_agent/workspace.py` | 底层文件、命令和补丁操作 |
| `evaluate_course.py` | WSL 原生预检、复制校验、分阶段评测与归档 |
