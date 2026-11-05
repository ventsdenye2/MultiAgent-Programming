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

源码/论文分别限制 20/40 次实际模型请求，单请求完整 JSON 最多 32,000 字符。当前两题配置为 deepseek-flash、16384 输出上限、thinking enabled、reasoning_effort high；这些是本项目的运行选择，不是题目1、2的硬性限制。采样参数从 config.json 传给官方客户端，未设置的参数沿用服务端默认。只有题目3排名复测由课程代理强制4096及关闭thinking。仍禁用自动重试，避免不可核对的额外请求。

当前配置使用官方 Markdown Python 代码块模式（`use_structured_outputs_internally=False`、`code_block_tags="markdown"`）；模型先简述动作，再输出一个代码块，由官方解析器和执行器处理。开启 `use_structured_outputs_internally=True` 时仍支持官方 `thought/code` JSON，DeepSeek Chat API 通过 `response_format={"type":"json_object"}` 约束有效 JSON；不宣称服务端严格校验 JSON Schema。两种模式都使用对应的课程提示。历史回放恢复原记录的输出模式，不改写已归档响应。允许导入的模块由执行器声明；文件和命令操作通过课程工具完成。

长上下文两题通过官方 `prompt_templates` 扩展点使用课程精简提示，保留所选输出协议、动态工具说明、官方解析与执行。论文先由 Agent 提取所需页码至证据存储，再由上下文管理器按预算发送完整页面；原文按连续页序分批交付，模型可更新相关主题笔记后继续阅读，不要求每页被笔记引用；已确认送达的批次最多在下一次真实请求自动保留一次供恢复，自动恢复不续期；未确认需求继续等待。源码笔记为可选项，满足阅读和基线门槛后可直接依据当前源码开始修改。同一版本中相互包含的源码证据优先发送完整外层范围，避免重复文本挤占预算；各证据仍单独核验实际送达。工具说明明确参数类型和返回字段；主题笔记保留关键结论、页码和必要区别，完整答案及连续原文引用由 save_answer 保存。

DSML 回退兼容默认开启，可在配置中设置 `"dsml_compat": false` 恢复原解析行为。它不改变请求提示或上下文选择：在 HTTP 原始响应已记录后、官方 CodeAgent 补代码围栏之前，将完整 DSML 工具调用转换为所选的 Python Markdown 或 thought/code JSON 动作，再交给原有执行器。详见 [协议兼容说明](DSML_COMPAT.md)。原始响应保留在 `model_response`，转换记录在 `protocol_adapter`；`memory.json` 中的模型动作内容可能是适配后的执行视图，不能代替原始响应作为来源证明。历史对照须使用冻结版本或显式关闭此开关。

发送状态分别展示完整工具读取登记、此前实际曝光，以及本次 Evidence 标头所示范围；写入导致旧证据失效，但不重新开启首次写入前的全文读取要求。请求状态明确本次编号、上限和本次响应之后的余量，全部由 HTTP 审计计数派生。关键写入结果、命令退出码和错误在可选原文之前预留空间，完整日志仍保留。源码和论文默认使用31,800字符软预算，实际HTTP完整JSON仍受32,000字符硬上限约束；额外空间用于保留反馈和整页原文。模型可以在同一动作中运行验证，根据真实结果更新计划并结束；门槛不会因剩余额度而放宽。

论文正常轮先按页码顺序装入未读完整页，再用余量按 FIFO 安排显式回看，两阶段分别处理页面放不下的情况。全部必读正文送达后，显式回看优先，自动携带只在首次或新显式需求完整确认后的下一次请求有效；重复携带和错误恢复不刷新窗口。保留一次不可续期的专用错误恢复机会，空响应等未确认需求不会被窗口删除。

论文专用 `recall_pages(pages=[10, 13])` 将当前版本已提取页排队，旧 `recall(evidence_ids=...)` 保持可用；排队不等于送达。每轮预留简短选入/等待回执，从零显示十问和五章节缺项，并保留简短保存结果。证据充分时可以立即保存答案及章节，无需等全文覆盖。五份最新笔记共同进入后续真实请求的提交门槛保持。尚未加入让 LLM 选择笔记、答案等可选上下文的通用选择功能。

2026-11-05 MVP 验证：[方案与离线回归](CONTEXT_EFFICIENCY_MVP_20261105.md)、[六次真实测试报告](experiments/smolagents/mvp-3x3-20261105/REPORT.md)。离线147项通过；论文客观验收3/3、源码2/3。论文自由文本存在已记录的事实错误，且本组没有同配置旧版对照，不能据此宣称同质量输入节省。

笔记规则按任务类型确定：源码笔记为20～3000字符，记录 `context_note`；论文笔记为20～1500字符，必须指定五个主题之一，记录 `section_note`。可选笔记键不会改变任务类型。
结构化模式写笔记时，`thought`保留笔记的完整原文，`code`把同一文字传给工具，保证课程检查能在真实响应中找到连续原文；不放宽原文、来源版本或先读后写的核验。
Markdown 模式将同一份完整笔记写在代码块前的说明与工具参数中，保持相同的来源核验规则。

## 离线验证

课程源码通过 `replace_text_batch(path, edits, expected_hash)` 对同一版本原文的一组唯一、不重叠文本修改进行原子提交。成功返回 `ok/path/before_hash/file_hash/changed`；`rc` 仅属于命令结果。旧单次替换在底层保留兼容，共用同一实现，源码模型工具列表只公开批量替换及整文件写入。

论文通过 `save_answer` 保存模型选择的答案、问题标识和原文来源，通过 `save_section` 保存摘要与应用，再由 `submit_report` 序列化 report.json。类型、页码、真实曝光版本和连续原文匹配由工具检查；匹配仅证明出处，不证明语义支撑。成果随 evidence.json 保存。原有五主题笔记及最新版本后续共同入模门槛保留。

源码/论文模型显式调用官方 `final_answer` 后，现有完成检查会执行尚缺的当前版本验证，失败返回实际问题，成功才完成计划并允许官方结束。不会自行发起额外模型请求。当前小批量验证及局限见 [接口改进记录](experiments/smolagents/STABILITY-INTERFACES-20261030.md)。

```bash
.venv/bin/python run_smolagents_tests.py
.venv/bin/python evaluate_course.py --preflight-only
```

第一条运行真实官方内核和模拟 HTTP 回归，使用原生 Linux 临时目录，结果保存在 `experiments/smolagents/offline-*/`。第二条验证完整复制后的提交包、源码基线、PDF 提取和归档，默认不调用模型。

实践02材料默认位于工作区的 `题目要求/02/`，可通过 `COURSE_MATERIALS` 指定其绝对路径；实践01运行器使用 `题目要求/01/`。课程运行器与材料测试使用当前工作区布局。

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
| `course_agent/protocol.py` | 严格 DSML 解析、整批参数校验和 Python 动作生成 |
| `course_agent/context.py` | EA-CM 发送视图 |
| `course_agent/evidence.py` | 证据去重、曝光、笔记与版本失效 |
| `course_agent/session.py` | 官方 Tool 接口、课程过程及 final_answer_checks |
| `course_agent/policy.py` | 题型、范围与预算 |
| `course_agent/workspace.py` | 底层文件、命令和补丁操作 |
| `evaluate_course.py` | WSL 原生预检、复制校验、分阶段评测与归档 |
