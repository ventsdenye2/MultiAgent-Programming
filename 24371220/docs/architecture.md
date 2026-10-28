# Code Agent v2 架构与运行边界

本文按当前源码说明 v2 的组件分工、状态与证据流。入口位于 `agent.py`，v2 实现位于 `codeagent/`。该实现仍与已评测的 legacy 并存；文档描述代码门禁，不构成真实模型调用、课程评测或提交验收记录。

## 启动与组件

```text
agent.py
  ├─ legacy：原 Agent + runtime.py（默认）
  └─ v2：codeagent.cli
       ├─ policies.load_task：形成 TaskSpec/profile/路径和预算
       ├─ controller.CodeAgent：主循环、工具路由、完成门禁
       ├─ model.ModelClient：唯一模型请求出口、请求/令牌预算
       ├─ context.ContextBuilder：组装消息、证据、历史和字符预算
       ├─ evidence.EvidenceStore：证据来源、版本、呈现与笔记
       ├─ state.StateReducer：当前计划、阶段、读写和验证状态
       ├─ executor.PythonExecutor：受限 AST 解释器和 RPC 工具调用
       ├─ workspace.WorkspaceTools：文件、PDF helper、命令和 patch
       └─ recording.RunLog：追加式 JSONL 审计日志
```

`agent.py` 解析公共 CLI 参数。`--engine` 默认取 `CODE_AGENT_ENGINE`，该环境变量未设置时为 `legacy`；只有指定 `--engine v2` 或环境变量 `CODE_AGENT_ENGINE=v2` 才进入 v2。v2 CLI 从同目录读取 `config.json`，检查模型名，读取任务，解析 profile，要求输出目录位于 repo 之外，并创建 `run.log`。现有 legacy 使用 `runtime.py`，它与 v2 的 workspace、状态机和证据协议不同。

`CodeAgent` 串联每轮流程：刷新证据有效性、构造状态前缀和上下文、提交一个模型请求、记录响应、解释动作、收集工具观察，并将完整请求/响应配对加入历史。JSON 动作模式每次解析一个工具对象；默认 code 模式解析 Python 代码块，由受限执行器解释，其中可按顺序调用多个注册工具。交互模式会对写入、命令等动作征求终端确认，自动模式不读取键盘。

## 状态机与状态归约

`StateReducer` 是当前运行状态的唯一写入者。状态包含 `running/succeeded/incomplete/interrupted`、阶段、计划、完整读取文件、写入数、workspace revision、基线命令结果、当前验证指纹以及关注路径。计划要求 1–10 项，每项标题非空、状态为 `todo/doing/done`；严格模式下计划标题与顺序首次建立后固定。

阶段从 `plan` 到 `explore`；首次发生实际写入后进入 `verify` 并增加 revision、清空旧验证；有写入且验证失败时转入 `repair`，成功验证时处于 `verify`。计划完成本身不会自动等于成功。`finish` 还会检查写入要求、每条验证命令是否在当前文件指纹上通过，以及 profile 专属规则。模型请求数用完、超时、工具/模型错误或用户中断会留下非成功状态；退出码 0 仅对应控制器状态 `succeeded`。

## 证据与模型实际可见范围

读取结果会进入 `EvidenceStore`，记录的共同字段包括 `id`、`content`、`path`、`file_hash`、`kind`、`start_line`、`end_line`、`page`、`status`、`seen_requests`、`successful_requests`、`step_id` 和 `sources`。未使用字段为 null/空集合。文件、范围、符号证据分别记为 `file`、`range`、`symbol`，PDF 页证据记为 `pdf`。笔记另带 `topic`、`version`、`source_paths`、`pages`、`response_id`、`request_id`。工具执行读取不等同于模型已阅读：只有证据内容进入一次成功模型请求后才记为 `successful_requests`。证据刷新时重新计算源文件哈希；源文件变化会使旧证据以及依赖这些证据的笔记失效。`get_evidence(evidence_id)` 可将仍有效的记录 pin 到下一次请求。

`save_note` 要求笔记正文能在当前模型响应中找到，引用的 evidence ID 必须存在、有效，并已在当前请求中成功呈现。Topic note 固定为 `overview`、`reasoning`、`tool_use`、`multi_agent`、`outlook` 五个主题；最终笔记写入前要求五份最新笔记共同进入同一报告决策请求。笔记来源闭包记录源文件与 PDF 页码。

上下文前缀包含系统规则、完整任务、用户追加指令、当前状态、剩余模型请求数和有界证据 catalog。完整原文证据逐条进入上下文；PDF 以完整页面为单位，不切页内容。未呈现的有效来源优先加入，文件全文放不下时只暴露短 catalog，模型可选 `read_range` 或 `read_symbol` 缩小读取。evidence mode 还会复用有效的旧来源证据与有效的最新主题笔记；更新源文件或依赖闭包失效后不再复用。catalog 仅提供受限 metadata（例如路径、字符数、哈希、证据 ID），catalog 本身不是原文证据，也不会计为模型读过。所选历史保留 assistant 动作及其 observation 成对关系，diagnostic 优先近期失败和关注路径；baseline/evidence 按较新历史优先选择，最终仍按原时间顺序发送。

这里的“呈现”是本地记录中的请求组装及 API 成功返回判断，不是人工复核或模型理解正确的证明。`paper_coverage()` 只统计成功呈现且未失效的页证据；分类规则不判断页内容是否充分。

## 请求、上下文和运行预算

`TaskSpec` 默认设置最多 60 个模型请求、30 分钟运行时限、请求软字符上限 30,000、硬上限最多 32,000。配置可收紧这些预算；模型实际剩余请求数放入每次状态中。`ModelClient` 是模型流量唯一出口，在发送前按完整序列化请求 JSON 检查硬字符上限，检查请求配额和 deadline，并对 API 响应校验 usage：prompt、completion、total 必须是非负整数、总和匹配且 total 大于零。缺失/不匹配 usage 使 usage 标为不完整并运行失败，不估算 token。每次发起请求前都会消耗一次 attempted request；有效 usage 才累加到 requests/token totals。

当前没有自动网络重试。网络/HTTP 请求失败会记录 `model_error` 并结束该次运行；usage 无效或响应结构无效也会失败。模型动作格式或工具动作有问题时，控制器会把错误作为 observation 交回后续主循环，模型若再请求一次会消耗新的请求预算；这不是客户端自动重试。

`ContextBuilder` 先保留固定前缀；固定内容超过硬限制或必需证据放不下会直接报错。普通历史和可选 catalog 可以因软/硬预算被舍弃；必需证据不能因预算而静默跳过。不同 context mode 影响证据复用和历史排序，不改变模型请求出口和硬限制。`--efficiency` 是受限实验选项：它只对 `effective_body()` 生成的固定参数投影计算字符预算，不修改 `ModelClient.send()` 实际发送的 body；因此不能把该开关当作已向服务商应用这些参数或已节省 token/cost 的证据。实际 usage 仍以 API 响应为准。

配置入口与优先级：`--engine` 命令行覆盖 `CODE_AGENT_ENGINE`，未提供时默认 legacy。legacy 与 v2 的 context mode 都按 CLI `--context-mode` > `MINI_CONTEXT_MODE` > profile/引擎默认值或 `config.json` 执行；legacy 默认 `baseline`，v2 默认 `config.json:context_mode_v2`，再缺省为 `evidence`。v2 的 action mode 为 CLI > `config.json:action_mode` > `code`。`--efficiency` 只会把 config 的 efficiency 打开，不提供 CLI 关闭项。`--model` 必须等于 config 的 model。task profile 和 `--allow` 由 CLI 参数传给 `load_task()`；repo 中 `run_checks.py`、纸面/source 文件结构也参与 profile 规则和自动识别。

关键 v2 配置键：`model`、`base_url`、`key_env`、`max_steps`、`max_tokens`、`temperature`；可选键还包括 `request_timeout`、`run_timeout`、`request_chars`、`context_chars_v2`、`context_mode_v2`、`action_mode`、`command_timeout`、`command_rules`、`verify_commands`、`editable`、`read_only`、`efficiency`。CLI `--efficiency` 只能开启实验选项。配置项不应保存 API key 本身，只保存环境变量名。

### 工具参数速览

工具参数在入口用 JSON Schema 子集校验对象类型、必需字段、数组项、整数/布尔区别和额外字段；每个工具默认拒绝未声明字段。

| 工具 | 参数 | 结果/行为摘要 |
| --- | --- | --- |
| `list_files` | `path="."`, `limit=200`, `offset=0` | 列出受限目录中的文本文件；有最大 limit 与扫描上限。 |
| `search_code` | `query`, `paths?`, `limit=20` | 原样文本搜索，返回匹配行及 `start_line/end_line`。 |
| `read_file` | `path` | 全文读取，返回 `path/content/file_hash`。 |
| `read_range` | `path`, `start_line`, `end_line` | 闭区间读取，保留原换行，返回实际行界。 |
| `read_symbol` | `path`, `symbol` | Python AST 类/函数完整片段，含装饰器；支持 `Class.method`。 |
| `write_file` | `path`, `content`, `expected_hash` | editable 白名单内按哈希保护、原子写入。 |
| `replace_text` | `path`, `old_text`, `new_text`, `expected_hash` | 哈希匹配且 `old_text` 唯一时替换。 |
| `read_pdf` | `start_page`, `end_page?` | 调 repo 根目录 helper；返回保留的原始 stdout 和解析 JSON 顶层字段。 |
| `run_command` | `argv`, `cwd="."` | shell=False，仅执行白名单完整 argv。 |
| `update_plan` | `items` | 更新 1–10 个计划项；状态为 todo/doing/done。 |
| `save_note` | `content`, `sources`, `topic?` | 保存可追溯模型笔记；正文须出现在当前响应。 |
| `get_evidence` | `evidence_id` | 取回有效证据并 pin 到下一请求。 |
| `finish` | `summary` | 请求结束；由控制器执行最终门禁。 |

工具完整 schema 由 `codeagent.workspace.TOOL_SPECS` 和 `codeagent.controller.EXTRA_SPECS` 提供；实际范围以当前源码为准。

```mermaid
sequenceDiagram
    participant CLI as agent.py / cli.py
    participant C as CodeAgent
    participant X as ContextBuilder
    participant M as ModelClient
    participant P as PythonExecutor
    participant W as WorkspaceTools
    participant E as EvidenceStore / StateReducer
    CLI->>C: TaskSpec + config + output
    C->>E: refresh evidence and state
    C->>X: prefix + history + evidence + budgets
    X-->>C: selected messages + evidence manifest
    C->>M: one request body
    M-->>C: raw response + validated usage
    C->>P: interpret code action (JSON mode skips P)
    P->>C: RPC tool name + arguments
    C->>W: schema checked tool call
    W-->>C: result / full command log
    C->>E: observe, invalidate, reduce state
    C-->>C: append action-observation pair; next request
```

## Python 工具执行安全边界

code mode 的代码由 `executor.py` 解析为 AST，并由自写解释器逐节点解释。支持变量、列表/字典、索引/切片、条件、有限 `for`、基础表达式与运算，以及受限内置函数和注册工具；拒绝 `import`、属性访问、函数/类定义、推导式、`while`、上下文管理器、任意文件/网络 API 等。解释器另有操作数、循环/容器、输出、工具调用和执行时限限制。工具通过父进程 RPC 执行；执行 worker 会清理名称中含 API key、token、secret、password、credential 的环境变量。

这是一种减少任意代码执行能力的语法/解释器限制，不是操作系统沙箱。子进程隔离、资源配额和语法白名单不能证明无解释器缺陷、侧信道、宿主进程风险或所有平台上的强隔离。

`WorkspaceTools` 为读写、搜索和命令执行提供第二道应用层限制：路径相对 repo，解析后不能逃逸；拒绝隐藏路径、`.git`、敏感文件名和二进制内容；遍历跳过常见缓存/虚拟环境目录，并设文件大小、扫描数上限。写入要求路径在 editable 集合内及哈希匹配，写入通过同目录临时文件替换；每次修改使旧内容证据失效。`read_symbol` 通过 Python AST 返回完整类/函数节点（含装饰器），支持类方法限定名并拒绝歧义。

命令以 `shell=False` 运行，环境移除 configured key 及 `*_API_KEY`，设有 timeout 并尝试清理进程树。默认命令仅允许完整 `python -m pytest -q`、仓库存在时的 `python run_checks.py`、严格参数校验的仓库根 `read_pdf.py` / `read_source.py` helper；配置和任务 profile 可再给出精确 argv 命令。所有结果记录 argv、cwd、真实 rc、stdout、stderr 和 timeout 状态。helper 不是可信沙箱边界：其代码本身仍可进行普通 Python 操作；本工具只约束所调用的入口、参数和 cwd。

上述检查是按当前实现的应用层约束，不能替代容器/账户隔离。目录枚举也有文件数截断，搜索范围可能因此不完整；分页用于返回控制，不保证只扫描对应页。

## 课程 profiles 与验证/完成门禁

`load_task()` 支持 `auto`、`basic`、`generic`、`paper`、`source`。`auto` 根据 repo 内的任务文件布局与题面特征选择；也可显式 `--profile`。editable 从 `--allow`、config 或题面约束行提取，路径必须留在 repo 内。

| Profile | 当前规则 |
| --- | --- |
| `basic` | 读取最多两个允许文件；完整 pytest 为基线和验证命令；repo 中有 `run_checks.py` 时再加入该命令。 |
| `generic` | 对已存在的 editable 文件要求完整读取；验证命令取 config 的 `verify_commands`，未配置时可使用完整 pytest。计划标题不强制固定。 |
| `paper` | 以 `report.json` 为 editable；固定要求第 1–52 页和五个主题笔记；模型请求上限收紧到最多 40；finish 检查报告是 JSON 对象。 |
| `source` | 从题面提取 `deepinfer/` Python 源文件；要求先读取所有目标文件；最多 20 次模型请求；首次编辑决策需带上目标来源证据或笔记；finish 要求每个 editable 文件哈希都已变化。 |

`--profile auto` 的 paper/source 识别依赖当前的路径与题面字符串启发式，并非通用任务分类器。任务可显式指定 profile；允许修改列表仍应由题目授权，不要用 profile 绕过题面范围。

首写入门禁要求有计划、所有 required_reads 已完整读取、所有验证命令有基线记录；paper/source 还检查各自要求。每次实际改动会使原验证指纹失效，因此需在新文件哈希上重新通过所有验证命令。finish 再检查所有计划项 done、要求写入的任务确有写入、每个验证命令 rc 为 0 且验证时指纹等于当前 editable 指纹。Source profile 要求目标文件均实际改动；paper profile 仅确认 `report.json` 可解析为对象。

通过这些门禁只代表程序内检查满足。`finish` 会记录 `evaluation_status=not_run`；不会自动调用课程评测器，不证明任务答案正确、公开测试通过或正式课程验收。单元测试可以使用模拟传输，模拟测试不能证明真实 API 行为。

## 日志与产物

输出目录必须在 repo 外，并且不能已有 `run.log`、`patch.diff`、`run-result.json` 或 `evidence.json`；新 `RunLog` 会拒绝覆盖这些历史产物。`RunLog` 以 UTF-8 JSONL 追加并逐行 flush，含时间、run_id、序号、工具调用/结果/错误、模型请求/响应、usage、上下文选择、evidence 与最终状态。配置的密钥值在日志行中替换为 `[REDACTED]`；鉴权头不会写入请求日志。日志记录完整的任务和读取/写入/命令正文，因此输出目录本身应按任务资料的敏感级别保护。

运行结束时产生 `patch.diff`（基于初始化 editable 快照）、`evidence.json` 和 `run-result.json`。补丁和证据目录用于追踪本次本地执行；它们不等同于已应用、已提交或课程评测通过。

普通新增/删除文件在补丁中使用 `/dev/null`。空文件新增/删除使用 Git 扩展头，须通过 `git apply` 应用；不能据此声称纯 GNU unified diff 能还原空文件操作。对应离线测试在临时仓库中运行了真实 `git apply --check`。

## 当前限制与验证状态

- 默认 rollout 仍为 legacy：未设置 `CODE_AGENT_ENGINE` 且未传 `--engine` 时，走 `agent.py` 原 `Agent` / `runtime.py` 路径。v2 只能显式选择，尚未替换 legacy，也没有据此宣称正式课程成绩。
- 自动 profile 识别及 paper/source 门禁偏向现有公开任务目录结构，不能推断其他课程的真实规则。
- AST 解释器只支持刻意缩小的 Python 子集；复杂代码任务可能需要 JSON 动作模式，或超出当前表达能力。
- PDF 提取依赖 repo 内实际 helper；当前门禁按固定页区间及 JSON 结果结构记录证据，不验证 OCR/文本提取质量。
- 文件搜索的大小、目录和扫描数限制会产生截断；未返回命中不代表仓库中不存在匹配内容。
- 模型 token 预算必须有完整 API usage 才可比较。transport mock、无效 usage、API 失败均不能作为真实用量/成功证据。
- 文档与代码审查只说明当前源码设计。真实 API 运行、公开任务评测、Windows/WSL 全平台安全性和课程验收需分别取得独立记录。

### 独立验收清单

这些项目是验证 v2 发布/验收时应分别记录的证据层级，不表示目前均已完成：

1. **源码与接口检查：**检查当前工作树、`--engine` 默认、profile 配置和 editable 清单；执行文档/格式 diff 检查。不能据此声称运行成功。
2. **本地机制测试：**运行 v2 单元测试并确认模拟 transport 标识；记录测试命令、退出码、测试数和任何 skip。模拟通过仅覆盖测试中的机制，不证明网络/API。
3. **真实模型运行：**使用受保护的 API key 环境变量，在全新 repo 外 output 目录运行；保留完整 `run.log`、`run-result.json`、`evidence.json`、`patch.diff`。核对请求数、完整 usage、任务状态与写入/验证指纹；不把 `evaluation_status=not_run` 改述成课程通过。
4. **课程公开评测：**在规定的课程副本与评测器上完整运行目标用例，保留评测器原始结果、每题证据和补丁回放/还原检查。来源必须是实际课程评测运行，不能从单测、模型 `finish` 或 HTTP 成功推断。
5. **部署/平台验收（若适用）：**分别检查目标 Windows/WSL 环境、命令中断清理、文件访问限制和实际 UI/设备流程；单平台安全审阅不能替代其他平台证据。
