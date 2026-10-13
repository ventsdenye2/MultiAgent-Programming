# 第四课实践1：迷你编码智能体

你要自行实现一个命令行智能体，让它读取题目、修改代码、运行测试，并保存操作记录和代码补丁。先读 [课程题目](题目/实践01-迷你编码智能体-题目.md)，再按以下顺序完成：

1. 按[实践要求](#实践要求)实现智能体，提供符合[接口要求](#统一提交接口)的 `agent.py`。
2. [安装环境](#环境配置)，在入口旁配置 `config.json`，并[设置 API 密钥](#模型接入)。
3. 按[自测步骤](#公开任务自测)运行自己的代码：可以一次跑五题，也可以逐题手动运行。
4. 根据测试输出和日志修正实现，整理[提交材料](#提交材料)。

下文命令都从课程材料根目录执行，也就是放有本文件和 `run_eval.py` 的目录。手动自测中需要切换目录的地方会单独说明。

## 快速开始

```bash
# 在本 README 所在目录打开终端，以下步骤在同一终端执行
# 自测记录保存每轮的任务副本、日志和补丁，脚本会自动创建目录
# 先准备自己的 agent.py 和同目录 config.json，配置格式见下文“模型接入”

# 首次创建环境；已有 mini-agent 环境时跳过创建命令
conda create -n mini-agent -c conda-forge python=3.12 pip patch -y
conda activate mini-agent
python -m pip install -r requirements.txt
# 自己的程序如需其他第三方包，还须安装相应依赖

# 以下以 DeepSeek 为例，config.json 的 key_env 填 DEEPSEEK_API_KEY
# 已设置密钥环境变量时，跳过下面两行
read -rsp 'API Key: ' DEEPSEEK_API_KEY; echo
export DEEPSEEK_API_KEY
```

```bash
# 方式一：一次评测五题（与方式二任选其一）
# 替换入口绝对路径；输出目录须不存在，重测时换成 五题_attempt02
python run_eval.py --agent '/绝对路径/20260001/agent.py' --out 自测记录/五题_attempt01

# 查看是否全部通过、总分及每题详情
cat 自测记录/五题_attempt01/summary.md
```

```bash
# 方式二：逐题自测（不自动限制运行时间），下面以第一题为例
# 替换入口绝对路径；--model 须与 config.json 一致
# 每轮使用新目录；重测时把本段所有 attempt01 一起改为 attempt02
python tools/check_submission.py --case case01_bug_fix --prepare 自测记录/case01_attempt01
cd 自测记录/case01_attempt01/run
python '/绝对路径/20260001/agent.py' --task ../work/task.md --repo ../work/repo --model deepseek-flash --auto
agent_exit_code=$?  # 紧接上一条命令保存退出码，中间不要执行其他命令
printf 'agent 退出码：%s（0 为成功）\n' "$agent_exit_code"

# 返回课程材料根目录，检查功能测试和运行产物
cd ../../..
python -m pytest -q 自测记录/case01_attempt01/work/repo
python tools/check_submission.py --case case01_bug_fix --attempt 自测记录/case01_attempt01 --agent-exit-code "$agent_exit_code"
# 本题通过须同时满足：agent 退出0、11 passed、产物自检通过
```

## 目录与任务

```text
第四课实践1-评测/
├── README.md                 # 从这里开始
├── requirements.txt          # 自测依赖：pytest
├── run_eval.py               # 可选：一次评测全部五题
├── 题目/                     # 课程题目与提交要求
├── 公开任务/
│   └── case*/
│       ├── task.md           # 本题要做什么、允许改哪些文件
│       └── repo/             # 初始代码、公开测试和诊断脚本
├── 说明/
│   └── 日志格式.md           # 写 run.log 时查阅
└── tools/
    ├── check_connection.py   # 可选：检查模型接入
    ├── check_submission.py   # 创建单题副本、检查日志和补丁
    ├── contracts.py          # 日志与过程检查
    ├── evaluator.py          # 五题评测使用的检查代码
    └── public_rules.json     # 各题允许修改的文件与过程要求
```

| 题目目录 | 主要任务 | 公开测试数 |
| --- | --- | ---: |
| [case01_bug_fix](公开任务/case01_bug_fix/task.md) | 单文件修复 | 11 |
| [case02_feature_regression](公开任务/case02_feature_regression/task.md) | 添加功能，保持既有功能正确 | 23 |
| [case03_cross_file](公开任务/case03_cross_file/task.md) | 跨文件定位问题 | 14 |
| [case04_two_subtasks](公开任务/case04_two_subtasks/task.md) | 按先后顺序完成两个子任务 | 10 |
| [case05_long_log](公开任务/case05_long_log/task.md) | 从长日志中定位问题 | 28 |

共五题、86个测试。**初始代码有测试失败是正常的，这正是要修复的问题。**不要直接修改这里的初始代码，自测时使用工作副本。

## 实践要求

自行实现150～300行 Python 核心循环，不使用现成 Agent 框架。智能体须具备：

- 用户交互：能接收任务、追加指令、查看进度和中断执行。交互模式下，写文件和执行命令前默认展示动作并请求确认。
- 上下文管理：组织对话历史，至少实现一种超长处理方法，例如裁剪、滑动窗口或摘要。
- 任务管理：把多步任务拆成子目标，记录待做、进行中和已完成的状态。
- 工具调用：至少能读文件、写文件和执行命令；工具的内部设计由你决定。

另外，自行提出并实现一项特色功能。固定题目、模型、预算和其他配置，关闭和开启特色功能各运行至少3次，保留每次结果。没有收益也如实记录，并说明原因和限制。

## 环境配置

使用 Linux/WSL、Python 3.12 和 GNU patch。任选下面一种方式，环境只需创建一次。

Conda：

```bash
conda create -n mini-agent -c conda-forge python=3.12 pip patch -y
conda activate mini-agent
python -m pip install -r requirements.txt
```

如果 `conda activate` 提示未初始化，运行 `conda init bash` 后重开终端。系统已有 Python 3.12 和 GNU patch 时，也可以用 venv：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

以后使用时先激活环境。这里的 requirements.txt 只安装 pytest；自己的代码用了其他第三方包，还需要安装相应依赖。

## 模型接入

在自己的 `agent.py` 同目录放置 `config.json`，填写三个必需字段：

| 字段 | 填什么 |
| --- | --- |
| model | 实际请求的模型名：`deepseek-flash`、`deepseek-v4-flash` 或 `qwen3.8-flash`；所用接口须支持该模型 |
| base_url | API 根地址，如课程中转地址或官方 API 地址，不填官网网页地址 |
| key_env | 存放密钥的环境变量名；这里写变量名，不写密钥值 |

使用 DeepSeek 官网 API 时，优先选择 `deepseek-flash`；`deepseek-v4-flash` 是保留的兼容名称，见[官方接入说明](https://api-docs.deepseek.com/)。配置示例：

```json
{
  "model": "deepseek-flash",
  "base_url": "https://api.deepseek.com",
  "key_env": "DEEPSEEK_API_KEY"
}
```

使用课程中转或 Qwen 时，按对应的接入信息替换这三个字段。接入方式和模型选定后保持固定，特色对照实验也使用相同配置。API 调用可用标准库或 SDK，自行实现。

在运行智能体的同一终端设置密钥。环境中已经有对应变量时，不用重复输入：

```bash
read -rsp 'API Key: ' DEEPSEEK_API_KEY; echo
export DEEPSEEK_API_KEY
```

如果 key_env 填的是其他名称，替换上面的两处变量名。密钥不写入代码、配置、日志或提交文件。

可选的连通检查：

如果想先检查模型是否能正常调用，可以使用下面的程序，也可以参考所用模型服务的官方示例或采用其他方式，不必使用本工具。

```bash
python tools/check_connection.py --config '/绝对路径/20260001/config.json'
```

替换为自己的配置路径。这个工具只适用于兼容 Chat Completions 的接口；返回0表示收到有效响应且生成了非空文本，1表示接入失败或文本为空，2表示参数或配置错误。它默认允许输出128 token。若请求成功却没有文本，先看 finish_reason 和 usage；服务支持时可加 `--thinking disabled`，也可用 `--max-tokens` 增加输出预算。

## 统一提交接口

无论内部代码怎样组织，都要提供名为 `agent.py` 的启动文件，并支持以下命令：

```bash
python agent.py --task /path/to/task.md --repo /path/to/repo --model deepseek-flash --auto
```

| 命令部分 | 含义与要求 |
| --- | --- |
| `python` | 使用当前环境中的 Python 解释器运行程序。 |
| `agent.py` | 你自行编写的智能体启动文件，负责接收这些参数并启动智能体。其他实现代码可以拆分到多个文件中。 |
| `--task /path/to/task.md` | 告诉智能体要读取哪一份题目文件，填写本轮题目文件的实际路径。 |
| `--repo /path/to/repo` | 告诉智能体在哪个文件夹读代码、改代码、运行测试，填写本轮自测副本中的代码文件夹路径。 |
| `--model deepseek-flash` | 指定本次调用的模型。将示例中的 `deepseek-flash` 换成自己选定的模型名，须与 `config.json` 中的 `model` 及实际请求的模型一致。 |
| `--auto` | 开启自动运行模式，不需要在后面填写值。开启后全程自动执行，不等待键盘输入或人工确认。 |

`/path/to/task.md` 和 `/path/to/repo` 是路径示例，运行时要换成实际路径。`agent.py` 也可以写成它的绝对路径；相对路径以当前终端所在目录为准。

正常完成返回退出码0，失败返回非零值。`agent.py` 从自身所在目录找配置和实现文件，不能假定当前目录就是提交目录。

改动写到 --repo 指定的仓库；在**启动目录**生成 `run.log`（真实操作记录）和 `patch.diff`（能还原本轮改动的补丁）。

这两个文件由你实现的智能体程序生成，`run_eval.py` 和 `check_submission.py` 负责检查。`run.log` 使用 JSONL 格式，每行一个 JSON 对象；事件名称和字段要求见 [日志格式说明](说明/日志格式.md)。

日志由程序随真实操作逐条保存，执行题目时不必再通过写文件工具另建、覆盖或补写日志文件。日志和补丁都保存在启动目录，业务仓库中只修改题面允许的文件。

## 必须遵守的规则

1. **只改允许的业务文件。**每题 task.md 会列出范围。不要改初始任务、测试、诊断脚本或评测工具；只改本轮工作副本。
2. **修改前后都由智能体运行完整测试。**在工作仓库根目录执行 `python -m pytest -q`，保存完整输出。不能用 -k 筛选、只跑某个测试或忽略失败。你手工补跑的测试不能代替智能体自己的过程记录。
3. **按实际操作写日志。**模型请求、完整响应、读写文件、命令参数和完整输出都要记录。不要伪造、事后补写，或人工改好代码后冒充自动完成。
4. **第三题先读再改。**首次修改前，完整读取至少两个业务 Python 文件。
5. **第四题先修净额，再做 CSV。**修改前，计划的前两项依次为净额修复和 CSV 导出；更新状态时保持标题和顺序一致。先修净额并运行完整测试，记录结果、将第一项标为 done，再开始实现 CSV，最后将计划全部标为 done。中间因 CSV 尚未实现而出现失败是正常的，但净额对应的测试必须通过；最终必须全量通过。评测会检查文件写入、中间测试和计划更新的先后顺序，不能用最终测试代替中间验证。
6. **第五题要处理长输出。**修改前后都运行 `python run_checks.py`；修改前的失败输出至少12000字符，修改后退出0。每次模型请求的消息 content 合计不超过16000字符。日志中保留完整原输出，发给模型的内容可以裁剪或摘要，但要记录处理方法和保留、舍弃的内容，不能把日志一起截短。

每题 `task.md` 的“执行与验证要求”列出本题必须执行的步骤。实现智能体时，把通用规则加入程序执行流程或系统提示词，并由程序统一保存日志。评测工作副本只包含本题 task.md 和业务仓库，不包含课程 README 或日志说明；不要依赖模型在临时目录中查阅这些说明。

使用 `run_eval.py` 时，默认每题智能体最多运行600秒（含网络等待），最终 pytest 验证最多120秒。逐题手动自测的命令不会自动施加这两个时间上限，需要自行控制运行时间，必要时按 Ctrl+C 中断。课程公布其他上限时按公布的预算执行。特色对照实验的时间、调用次数、token预算、温度等设置须保持一致。

## 公开任务自测

先完成自己的程序和配置，安装依赖，设置密钥。下面两种方式任选：**逐题调试用方法二，想一次查看五题结果用方法一。**它们检查相同的题目和过程要求。

示例中的 `自测记录` 用于保存每轮自测的任务副本、日志和补丁，脚本会自动创建目录。重测时将 `attempt01` 换成 `attempt02` 等新编号。

### 方法一：一次评测五题

从课程材料根目录执行，替换入口路径：

```bash
python run_eval.py --agent '/绝对路径/20260001/agent.py' --out 自测记录/五题_attempt01
```

脚本会依次启动五次智能体，每题使用全新的工作副本，然后运行完整公开测试、检查日志和补丁、汇总得分。某题失败后会继续评测后面的题。模型默认从入口同目录的 config.json 读取；评测器本身不调用模型，你的智能体会按自己的实现使用 API。

--out 必须是尚不存在的目录。修正实现后，换成 `五题_attempt02` 重测，保留上轮结果。相对输出路径以当前终端目录为准。

评测结束时，终端会直接显示 **【全部通过】、【未全部通过】或【评测未完成】**，以及通过题数和总分。每题结束时也会显示“通过 / 未通过 / 待复测”，后面保留详细状态和测试数量。“待复测”表示验证未完成，不能当作通过或判为0分。

提交代码引入的语法、导入或运行错误，经复核确认后判为未通过、记0分。环境或评测工具异常、验证超时，或者无法确认错误来源时，才提示待复测。

运行后先打开 `自测记录/五题_attempt01/summary.md`，顶部有同样的中文结论，表格列出每题结果；详细 JSON、CSV、日志和测试输出仍保留：

```text
自测记录/五题_attempt01/
├── summary.md                # 五题状态、得分和总分
├── summary.json              # 同一结果的 JSON 格式
├── summary.csv               # 逐题明细
└── 20260001__case*/           # 前缀是入口所在目录名
    ├── run.log、patch.diff    # 智能体生成的记录与补丁
    ├── agent_stderr.txt       # 智能体的错误输出
    ├── repo_after/            # 本题运行后的代码
    ├── pytest_output.txt      # 最终测试输出
    ├── validation_baseline_output.txt  # 出现收集或运行错误时的初始代码复核输出；仅复核时生成
    ├── evidence.json          # 过程检查详情
    └── result.json            # 本题状态与原因
```

五题验证完成后，summary.json 的 total_score 是0～5。验证异常或 Ctrl+C 中断时，总分为 null，不能把这个结果当成完整成绩；排查后用新目录重测。Ctrl+C 会结束当前题，保留已经完成的结果。

脚本退出0表示五题全部通过；退出1表示五题评测结束但有题未通过；退出2表示参数、环境或验证问题；退出130表示手动中断。

### 方法二：逐题手动自测

下面以 case01 和配置中的 `deepseek-flash` 为例。**从课程材料根目录开始，在同一终端按顺序执行。**使用其他模型时，把 --model 改成 config.json 的 model。

第一步，创建副本：

```bash
python tools/check_submission.py --case case01_bug_fix --prepare 自测记录/case01_attempt01
```

这条命令不调用模型，创建 before/（初始题目）、work/（可修改的副本）和 run/（日志与补丁的保存位置）。目录已存在时换新编号，不要修改 before/。

第二步，进入 run/，启动自己的智能体并立即保存退出码：

```bash
cd 自测记录/case01_attempt01/run
python '/绝对路径/20260001/agent.py' --task ../work/task.md --repo ../work/repo --model deepseek-flash --auto
agent_exit_code=$?
printf 'agent 退出码：%s（0 为成功）\n' "$agent_exit_code"
```

替换入口绝对路径。上面的命令可以在**同一个终端中逐句执行**：先运行智能体，等待它结束，再执行 `agent_exit_code=$?`，最后执行 `printf` 查看退出码。

`$?` 表示上一条命令的退出码，因此在智能体结束与保存退出码之间，**可以停顿，但不要执行其他命令**，例如 `cd`、`ls`、`echo`，否则保存的会是那些命令的退出码。

`agent_exit_code=$?` 没有输出是正常的；它把退出码保存到变量中，供第三步的自检使用。`printf` 只是显示保存的值，可以省略。第三步也须在这个终端中继续执行，才能使用该变量。

第三步，返回课程材料根目录，检查代码和产物：

```bash
cd ../../..
python -m pytest -q 自测记录/case01_attempt01/work/repo
python tools/check_submission.py --case case01_bug_fix --attempt 自测记录/case01_attempt01 --agent-exit-code "$agent_exit_code"
```

自检会先显示 **【产物自检通过】或【产物自检未通过】**，再显示完整 JSON；检查过程中出现参数、文件或环境问题时，会提示【自检未完成】。**“产物自检通过”只代表日志、过程、修改范围和补丁检查合格，还须确认功能测试通过。**

case01 成功时应同时满足：**agent 退出0、测试显示11 passed、自检 JSON 中 ok 为 true**。自检退出0表示检查通过，1表示发现问题，2表示参数或环境问题；它不替你运行功能测试。

其他题目按目录表替换 `tools/check_submission.py` 的 --case 和本轮自测目录名，再重复上述步骤。每轮使用新副本；最终报告记录五题的结果。

### 遇到问题看哪里

| 现象或状态 | 怎么处理 |
| --- | --- |
| agent 退出非零或 agent_timeout | 看 run.log 和错误输出，检查异常、网络等待及循环退出条件 |
| validation_failed / pytest 有失败、代码错误或跳过 | 本题记0分；看完整测试输出，按题面修正代码 |
| process_failed | 看 evidence.json 的 failed_checks，补齐智能体自身的过程步骤；第四题还须检查中间测试和计划更新顺序 |
| invalid_submission / 自检 ok=false | 看 result.json 的 note，或自检的 errors、process；检查日志格式、补丁和修改范围 |
| validation_error / validation_timeout / evaluator_error | 暂不判分；检查错误输出、依赖和环境。若有 validation_baseline_output.txt，也查看初始代码复核结果；排查后用新目录重测 |
| 模型接入失败 | 检查 base_url、key_env、模型名和网络；401/403先检查密钥及权限 |

自动检查只能核对可见的代码和记录。交互演示、特色实验、报告和日志真实性也须满足课程要求。

## 五分制评分

总分5分，每题通过得1分，未通过得0分，不按通过了多少个测试折算部分分。

每题通过须同时满足：入口退出0、完整测试全部通过、日志和补丁有效、只改允许文件、题目规定的过程检查合格。一次五题评测中的 passed 就表示这些自动检查通过。验证器本身出错时先排查重测，暂不判分。

交互演示、特色实验和报告必须完成，但不单独计分。伪造轨迹或人工代改冒充自动产出，按课程规则记零分。

## 提交材料

以本人学号命名提交目录，放齐程序运行所需的文件。下面以 `20260001` 为例，其他实现文件按自己的代码结构放置即可：

```text
20260001/
├── agent.py                  # 智能体启动文件，接收参数并启动程序
├── config.json               # 模型名、API 地址和密钥环境变量名，不填写密钥值
├── README.md                 # 说明如何安装依赖、配置、运行和使用程序
├── requirements.txt          # 列出第三方 Python 包及版本；仅用标准库时可不提供
├── 其他实现文件/              # 自己编写的模块及程序运行所需的资源
├── 报告.pdf                  # 设计说明、特色实验和五题成绩，正文不超过3页
└── experiments/              # 保存自测与特色对照实验的记录
    ├── public/               # 公开题的运行日志、代码补丁和自测结果
    └── feature/              # 特色功能开启、关闭时的对照实验记录
        ├── off/              # 关闭特色功能，保留至少3轮的配置、日志、补丁和结果
        └── on/               # 开启特色功能，保留至少3轮的配置、日志、补丁和结果
```

提交 README 写清环境与依赖、配置方法、启动和交互操作、特色开关、日志字段映射，以及核心文件/函数的范围和行数。使用标准库时说明即可；使用第三方包时列出实际依赖及版本。

报告正文不超过3页，特色说明约占其中1页；包括设计取舍、四项基线功能、特色对照结果、五题成绩、限制和参考来源。日志、补丁和实验数据作为附件，不计入正文页数；用相对路径注明证据位置。

至少提交一轮公开题的完整 `run.log`（模型对话、工具调用与结果）和对应 `patch.diff`（本轮代码改动），建议五题都保留。特色实验保留开、关各至少3轮的配置、日志、补丁和结果，不挑选成功轮次。

核心150～300行按 Python 非空、非纯注释的物理行统计，跨文件合计。消息组织、动作解析、循环控制、计划调度和上下文处理属于核心；API 传输、底层文件/命令操作、日志与补丁保存、CLI 参数解析属于辅助代码。不把核心决策挪到辅助模块或把多条语句挤在一行来减少计数。
