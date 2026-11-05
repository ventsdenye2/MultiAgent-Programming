# Context 对照记录

快照时间：2026-11-05T03:13:48.224086+00:00

仅汇总现有产物；未完成样本不计为失败。用户主动暂停单独统计，不当作失败，不计入成功率分母。成功率分母为已结束评测样本，缺失 usage 不估算。
日志错误为观测计数，不据此推断失败原因或宣称稳定。字符计量不是 token 计量。

两组仅 static_context_compact 不同：True；context_accounting 配置（缺省为开启）：{'baseline': True, 'static': True}。

| 组 | 题目 | 已结束/计划或观测 | 通过 | 成功率 | 已暂停 | 待完成 |
|---|---|---:|---:|---:|---:|---:|
| baseline | paper | 0/3 | 0 | 未知 | 1 | 2 |
| baseline | source | 1/3 | 0 | 0.0% | 0 | 2 |
| static | paper | 1/3 | 0 | 0.0% | 0 | 2 |
| static | source | 1/3 | 1 | 100.0% | 0 | 2 |

| 组 | 请求 | 完整 usage 请求 | 已知 prompt/completion/total tokens | 协议/工具/基础设施错误 |
|---|---:|---:|---|---|
| baseline | 20 | 20 | 176764/27773/204537 | 4/1/0 |
| static | 59 | 59 | 491849/45454/537303 | 5/3/0 |

| 组/样本 | 状态 | 通过/score | 请求 | 首改/末改/末改后末测/结束请求 | paper 页数/主题 |
|---|---|---|---:|---|---|
| baseline/paper-01 | user_paused_before_request | None/None | — | —/—/—/— | —/ |
| baseline/paper-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| baseline/paper-03 | not_recorded | None/None | — | —/—/—/— | —/ |
| baseline/source-01 | failed | False/0 | 20 | 18/19/20/— | 0/ |
| baseline/source-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| baseline/source-03 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/paper-01 | failed | False/0.0 | 40 | —/—/—/— | 52/overview, reasoning, tool_use |
| static/paper-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/paper-03 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/source-01 | passed | True/1 | 19 | 12/19/19/19 | 0/ |
| static/source-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/source-03 | not_recorded | None/None | — | —/—/—/— | —/ |

| context 项 | baseline 已知字符合计/缺失请求 | static 已知字符合计/缺失请求 |
|---|---:|---:|
| core | 29140/0 | 66788/0 |
| tool | 74680/0 | 220858/0 |
| task | 134080/0 | 418805/0 |
| status | 25126/0 | 60271/0 |
| plan | 7296/0 | 26313/0 |
| recent | 34863/0 | 109662/0 |
| notes | 0/0 | 34270/0 |
| evidence | 242303/0 | 684033/0 |
| other | 462/0 | 7024/0 |
| json_wrapper_chars | 6769/0 | 21172/0 |
| compact_json_chars | 554719/0 | 1649196/0 |

context_accounting 为 text_json_chars 的逐项归属；JSON 包装单列。每请求原始 text_chars、usage 缺失、页码、主题、错误详情及各项 sum/count/missing/mean/max 见 CONTEXT-COMPARISON.json。

全部已知 tokens：{'prompt_tokens': 668613, 'completion_tokens': 73227, 'total_tokens': 741840, 'prompt_cache_hit_tokens': 324480, 'prompt_cache_miss_tokens': 344133}。
