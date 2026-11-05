# DSML 兼容层

2026-11-05：针对归档中的九条 DSML 响应实现回退适配，保留 smolagents 1.26.0 的官方解析器、执行器、主循环和结束检查。未修改 EA-CM 上下文选择、Recall、carry、任务阶段或预算。

## 行为

- 默认 `dsml_compat=true`；设为 false 可做旧行为对照。兼容当前非流式 CodeAgent 入口，不实现原生 Function Calling。
- 正常 Python/JSON 响应原样通过；其中字符串携带的 DSML 不作为第二套动作执行。
- 只接受完整的 `<｜｜DSML｜｜ calls>` 信封，内部为顺序 invoke/parameter；属性形式采用历史样本中的 name、string 顺序。不猜测缺失标签，不处理 XML 实体或表达式，不从解释文字中抽取调用。混合原生动作和 DSML、截断响应、重复参数、重复 JSON 键、未知工具和不合法参数均拒绝。
- `string="true"` 的正文逐字保留，包括空格、换行、引号、反斜线和实体样式文本。`string="false"` 仅按 JSON 数据解析，拒绝非有限数字。最多 200,000 字符、32 个调用；含歧义 DSML 定界符的字符串不支持，模型可使用原有 Python 路径。
- 整批动作先按当前注册工具及其参数 Schema 校验，再通过 Python AST 生成调用。参数不会作为模型提供的 Python 表达式执行。工具返回值通过 print 进入官方 Observation。
- 验证通过的动作按顺序在原有执行器运行，不创建额外持久变量，也不解释跨调用返回值引用。Python 路径原有变量仍保留。
- 参数校验失败时整批零执行；运行中失败时先前成功动作保留、后续动作不执行，没有自动重放或额外模型请求。
- final_answer 只能在批次末尾，走官方结束信号及原有验收检查。文件权限、先读后写、版本哈希、命令规则、笔记来源和论文引用检查均留在原工具层执行。

## 审计与恢复

HTTP 钩子先保存 model_response、usage 和 Evidence 送达事实；适配器仅复制 SDK 消息形成执行视图，不修改 RequestAudit.last_response 或 EvidenceStore.last_response。

每次识别到 DSML 时记录 protocol_adapter，包含 request number、版本 dsml-v1、原始正文、解析调用、生成代码、适配正文、adapted/rejected 状态和拒绝原因。该事件表示转换结果，不代表工具已执行成功；执行结果仍以 tool_result/tool_error/agent_step 为准。

拒绝后向官方解析器提供明确的非代码诊断 DSML_REJECTED，由原有 AgentParsingError 路径恢复。原始响应仍在审计日志中，既不计为网络错误，也不偷偷发起修复请求。官方 memory.json 保存的是执行视图，原始证据应查 model_response。

## 验证

`test_fixtures/dsml_responses.json` 从 ec7235b 归档的 context-20261105-p0-a-3x3 原始 model_response 提取：baseline/source R5/7/9/10、static/source R10、static/paper R24/26/35/36。没有复制错误消息中由框架追加的代码围栏。

`test_protocol.py` 使用 MockTransport 和真实 CodeAgent/SDK/Python Executor 验证这些响应，并覆盖参数数据、拒绝分支、批次部分执行、变量持久化、写入门槛、笔记来源、答案引用和最终结束检查。完整离线入口已包含专项测试：

```bash
.venv/bin/python run_smolagents_tests.py
```

历史九条只包含 read_range、read_file 和 task_status；恢复这些调用不意味着历史任务会完成。离线测试不替代真实模型完成率实验，本次不恢复暂停的付费评测。

本次验证记录（均为 0 次 Provider 请求）：

- [默认完整回归](experiments/smolagents/offline-20261105-150511/pytest.log)：117 项通过。
- [最终协议专项](experiments/smolagents/offline-20261105-150905/pytest.log)：39 项通过，包含最后补充的 Markdown/XML 字符串定界符转义回归及九条历史响应的实际工具执行。
- [附加静态提示及计量回归](experiments/smolagents/offline-20261105-150743/pytest.log)：27 项通过、2 项因测试夹具复用日志目录而失败。将每次构建的会话日志目录隔离后，[两项重测](experiments/smolagents/offline-20261105-151023/pytest.log)通过；产品日志覆盖保护未改动。
- 官方 vendor 文件校验 24/24 一致；git diff --check 通过。原有工作区材料路径修改保留。
