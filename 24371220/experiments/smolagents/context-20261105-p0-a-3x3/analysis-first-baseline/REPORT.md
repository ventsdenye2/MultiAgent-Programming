# Context 对照记录

快照时间：2026-11-05T03:01:50.996744+00:00

仅汇总现有产物；未完成样本不计为失败。成功率分母为已结束样本，缺失 usage 不估算。
日志错误为观测计数，不据此推断失败原因或宣称稳定。字符计量不是 token 计量。

两组仅 static_context_compact 不同：True；context_accounting 配置（缺省为开启）：{'baseline': True, 'static': True}。

| 组 | 题目 | 已结束/计划或观测 | 通过 | 成功率 | 待完成 |
|---|---|---:|---:|---:|---:|
| baseline | paper | 0/3 | 0 | 未知 | 3 |
| baseline | source | 1/3 | 0 | 0.0% | 2 |
| static | paper | 0/3 | 0 | 未知 | 3 |
| static | source | 0/3 | 0 | 未知 | 3 |

| 组 | 请求 | 完整 usage 请求 | 已知 prompt/completion/total tokens | 协议/工具/基础设施错误 |
|---|---:|---:|---|---|
| baseline | 20 | 20 | 176764/27773/204537 | 4/1/0 |
| static | 0 | 0 | 0/0/0 | 0/0/0 |

| 组/样本 | 状态 | 通过/score | 请求 | 首改/末改/末测/结束请求 | paper 页数/主题 |
|---|---|---|---:|---|---|
| baseline/paper-01 | not_recorded | None/None | — | —/—/—/— | —/ |
| baseline/paper-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| baseline/paper-03 | not_recorded | None/None | — | —/—/—/— | —/ |
| baseline/source-01 | failed | False/0 | 20 | 18/19/20/— | 0/ |
| baseline/source-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| baseline/source-03 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/paper-01 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/paper-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/paper-03 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/source-01 | running | None/None | — | —/—/—/— | —/ |
| static/source-02 | not_recorded | None/None | — | —/—/—/— | —/ |
| static/source-03 | not_recorded | None/None | — | —/—/—/— | —/ |

| context 项 | baseline 已知字符合计/缺失请求 | static 已知字符合计/缺失请求 |
|---|---:|---:|
| core | 29140/0 | 0/0 |
| tool | 74680/0 | 0/0 |
| task | 134080/0 | 0/0 |
| status | 25126/0 | 0/0 |
| plan | 7296/0 | 0/0 |
| recent | 34863/0 | 0/0 |
| notes | 0/0 | 0/0 |
| evidence | 242303/0 | 0/0 |
| other | 462/0 | 0/0 |
| json_wrapper_chars | 6769/0 | 0/0 |
| compact_json_chars | 554719/0 | 0/0 |

context_accounting 为 text_json_chars 的逐项归属；JSON 包装单列。每请求原始 text_chars、usage 缺失、页码、主题、错误详情及各项 sum/count/missing/mean/max 见 CONTEXT-COMPARISON.json。

全部已知 tokens：{'prompt_tokens': 176764, 'completion_tokens': 27773, 'total_tokens': 204537, 'prompt_cache_hit_tokens': 81664, 'prompt_cache_miss_tokens': 95100}。
