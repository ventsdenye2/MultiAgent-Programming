# 五道原创代码题补充稳定性报告

日期：2026-10-30。状态：**5题各3轮，共15轮已全部完成，15/15完整通过**。每轮独立任务副本，未修改Agent或题目，未重试替换样本。全部真实评测现已停止。

## 1. 题目与最终结果

| 题目 | 内容 | 可编辑文件 | 单轮可见＋隐藏测试 | 三轮请求数 | 通过 |
|---|---|---|---:|---|---:|
| config_layers | 递归配置合并、环境变量解析 | merge.py、settings.py | 17 | 7、14、10 | 3/3 |
| csv_ledger | CSV校验、精确Decimal汇总 | ledger.py | 16 | 6、9、14 | 3/3 |
| unicode_words | Unicode类别、规范化词频 | words.py | 10 | 15、8、8 | 3/3 |
| dependency_paths | 相对路径规范化、确定性依赖排序 | paths.py、graph.py | 15 | 13、7、8 | 3/3 |
| ttl_cache | 过期、重入、加载期间失效 | cache.py | 14 | 15、10、10 | 3/3 |

每题3/3的Wilson 95%区间约为43.9%–100%；三次样本不能保证以后必过。72项不同测试重复三轮，共216项全部通过，零失败、错误或跳过；重复测试次数不是216个独立任务。

这些是本轮原创测试题，不是公开标准benchmark。参考实现先经离线验证全部通过，初始实现均不能通过全部测试。题库和冻结清单见[frozen-tasks/manifest.json](frozen-tasks/manifest.json)、[task-bank-sha256.json](task-bank-sha256.json)，原始题库在项目`stability_tasks/`。

## 2. 验收口径与隔离

采用同一冻结Agent实现、模型`deepseek-flash`及相同thinking/reasoning配置，但使用**generic profile**，每轮最多20次模型请求，并显式设置完整pytest验证命令。课程source/paper有专用提示与门槛，generic使用通用CodeAgent提示；因此不能把两类任务视为只换了题面的严格对照实验。

每轮完整通过要求：Agent完成写前基线与最后修改后的完整可见pytest、正常结束；仅修改允许文件；后置验证的可见＋隐藏测试收集数精确匹配清单且零失败/错误/跳过；运行文件哈希一致；服务端usage完整；请求≤20、完整API JSON≤32,000字符。

运行器只把初始repo和task.md提供给Agent。Agent退出之后，在另一个验证副本中加入heldout_tests；参考实现不复制进Agent工作repo。此处是复制与工具边界隔离，不宣称建立了额外操作系统权限沙箱。实际归档中，隐藏测试出现在validation-repo，Agent repo没有隐藏测试或参考解。

这些新增题由自建harness做后置隐藏pytest，HTTP/usage采用Agent SDK审计。课程题另有官方评测器、外部真实请求记录、源码机制或论文引用评分。新增题没有52页送达、五主题笔记共同复用、三指定源码机制等专用要求，结果不能合成为课程得分。

## 3. 逐轮用量与过程

所有15轮Agent及评测退出码均为0，usage均完整，文件范围和运行时哈希检查均通过。耗时从run_start至run_result，不包含全部后置评分/归档。

| 样本 | 请求 | 输入token | 输出token | Agent秒 | 中间解析/执行错误数 |
|---|---:|---:|---:|---:|---:|
| [config_layers-01](samples/extra-config_layers-01/sample.json) | 7 | 29,056 | 3,863 | 161.73 | 0/0 |
| [config_layers-02](samples/extra-config_layers-02/sample.json) | 14 | 60,044 | 6,277 | 55.41 | 2/0 |
| [config_layers-03](samples/extra-config_layers-03/sample.json) | 10 | 41,207 | 7,213 | 58.13 | 1/0 |
| [csv_ledger-01](samples/extra-csv_ledger-01/sample.json) | 6 | 26,110 | 29,031 | 170.67 | 0/2 |
| [csv_ledger-02](samples/extra-csv_ledger-02/sample.json) | 9 | 39,107 | 24,558 | 143.69 | 0/0 |
| [csv_ledger-03](samples/extra-csv_ledger-03/sample.json) | 14 | 62,115 | 16,281 | 123.50 | 1/1 |
| [unicode_words-01](samples/extra-unicode_words-01/sample.json) | 15 | 60,272 | 5,682 | 94.91 | 3/1 |
| [unicode_words-02](samples/extra-unicode_words-02/sample.json) | 8 | 31,502 | 3,702 | 37.11 | 1/0 |
| [unicode_words-03](samples/extra-unicode_words-03/sample.json) | 8 | 30,507 | 3,029 | 32.47 | 1/1 |
| [dependency_paths-01](samples/extra-dependency_paths-01/sample.json) | 13 | 51,243 | 4,663 | 43.92 | 1/0 |
| [dependency_paths-02](samples/extra-dependency_paths-02/sample.json) | 7 | 28,732 | 5,490 | 49.20 | 1/0 |
| [dependency_paths-03](samples/extra-dependency_paths-03/sample.json) | 8 | 33,241 | 3,326 | 33.41 | 1/0 |
| [ttl_cache-01](samples/extra-ttl_cache-01/sample.json) | 15 | 62,907 | 12,037 | 94.27 | 4/1 |
| [ttl_cache-02](samples/extra-ttl_cache-02/sample.json) | 10 | 41,549 | 20,073 | 137.33 | 1/0 |
| [ttl_cache-03](samples/extra-ttl_cache-03/sample.json) | 10 | 43,936 | 13,990 | 98.20 | 3/0 |

合计154次请求、输入641,528/输出159,215 token，usage完整；最大完整API JSON为23,530字符。Agent累计运行1,333.95秒。请求范围6–15次，中间共20条解析错误、6条执行错误，13/15轮曾出现至少一条Agent错误，但最终全部恢复。

## 4. 实际过程核查例子

config_layers-01：R3写前基线pytest失败（seq40），R4写merge/settings（seq55/59），R6最后可见pytest通过（seq86），R7完成计划并正常结束（seq92/95）。后置验证17 passed，包括6项可见测试和11项隐藏测试。归档submission的45个文件独立复算与冻结清单一致；实际预算limit20、used7。

本轮首个成功样本的审查及全部样本的最终批量复核均为只读，不修改产物，不新增付费请求。以每轮`evaluation/run/run.log`为动作证据，`evaluation/grading.log`/`grading.xml`为隐藏验证证据，`sample.json`为结果摘要。

最终独立批量复核15/15通过：逐轮确认写前基线rc1、最后写后pytest rc0、completed/remaining空和实际final_answer；从初始repo与最终repo重算文件变化范围；每个归档submission的45个文件与冻结哈希完全一致；原始请求/响应齐全，服务端usage合计一致；grading.xml收集数精确匹配，零失败/错误/跳过。

## 5. 与课程测试放在一起怎样解释

新增短任务15/15通过，说明该版本能在这些较小的通用代码任务上完成修改、测试与结束，并能恢复部分中间错误。它**不能推翻课程题各1/10的低通过率**，也不能证明长上下文、论文精确引用或复杂仓库任务已经稳定。

两组在任务规模、上下文负载、提示profile、工具/过程门槛及验收方式上都不同。当前数据无法隔离“任务难度”“上下文策略”“专用提示”各自的贡献，需要另行设计对照才可归因。本轮未开展这种消融，也未继续修改Agent。

完整课程结果见[必做题报告](COURSE-REPORT.md)，全部35轮可筛选数据见[RESULTS.csv](RESULTS.csv)与[RESULTS.json](RESULTS.json)。
