# 上下文简化设计与验收

## 开始状态与证据

工作树：experiments/code-agent-smolagents，分支 rebuild/smolagents-eacm，开始 HEAD 9b45f75。开始时 README/config、context/evidence/session/prompts/engine、inspect_evaluation 和两个测试文件已有未提交修改；继续保留并集成，主目录 main 不修改。

当前 context.py 用 exposed−summarized 取代待发送论文页，evidence.py 又将逐页笔记列为完成条件。历史 smolagents-20261029-121218-999886 的 context_exposure 第27至40次只包含35、38、41页，尚有页面待发送。报告写入触发 invalidate 清除 full_reads，而 paper 的 missing 每次要求初始报告阅读，导致输出修改使初始流程失效。源码已有 source_reused/source_priorities 原文路径，保留。

参数核对取自实际 model_request.body：上述旧论文轮为4096输出、thinking disabled、JSON响应；smolagents-20261029-122406-868556源码轮为16384输出、thinking enabled、reasoning_effort high、JSON响应，存在5次解析错误及1次执行错误，20次请求未产生写入。当前未提交配置采用官方Markdown代码块，不能用旧轮评价新配置。

## 设计（生产修改前已向用户说明）

保留官方 CodeAgent 主循环、解析器、执行器、工具与HTTP审计。删除逐页 summarized 状态、选择阻塞、完成门槛和冲突提示。EvidenceStore 管原文、来源版本、pending、真实 exposed/current 和模型笔记；实际HTTP请求与非空响应确认曝光，不代表材料已处理。官方 ActionStep 的错误和上一发送manifest提供失败恢复依据，不新增理解标记或第二套状态机。

同一构造器按完整JSON预算排列任务、状态、必要笔记、原文及最近反馈。源码保留完整机制工作集，可直接首写；相邻原文按显式读取复用。论文按连续页序组成批次，首个放不下的页结束批次，后续留队列。模型可同一动作写相关主题笔记并继续请求原文，不强制每页引用。失败保留当前批次和错误；本地读取、实际入模、生成笔记各自记录。五份最终笔记共同进入后续真实请求才能生成报告。

报告初始读取仅为首次写前要求，之后正常失效旧报告证据；PDF来源版本、52页覆盖和有效五主题笔记仍检查。TaskProgress 继续作为统一只读进度投影，session负责工具写入与完成门禁。

不修改 vendor、官方评测器、题面或业务工作副本答案。没有自动修复模型调用、备用解析协议或新增付费重试。

## 分工与验收

- 主Agent：确认证据、设计接口、审查集成、统一运行真实评测与本地提交。当前会话模型不能主动切换。
- GPT-6.1 Terra / medium：唯一生产核心负责人，context.py、evidence.py、session.py、prompts.py。
- GPT-6.1 Sol / medium：实际课程要求核查、相关离线测试；不修改共享核心。

先离线验证新页推进、真实曝光及失败恢复、无笔记源码首写、五笔记联合复用、报告写后验证和结束，校验vendor24文件及diff。再新目录串行源码题20次以内、论文题40次以内，每次完整紧凑API JSON不超过32000字符。原版课程评测决定成绩，模拟测试不视为作业通过。最终记录真实usage、覆盖、笔记、报告、修改、测试和补丁；不自动推送。

## 结果

离线全套49项通过：offline-20261029-150141；针对满长笔记容量复核1项通过：offline-20261029-150459。52页在27次模拟阅读请求送达，五份各1500字符笔记共同复用，最大完整请求29865字符。vendor24/24一致。smolagents-20261029-150442-720283运行包预检通过，三次完整PDF提取一致，源码基线正常运行（缺少待开发功能，退出1）。这些均未调用付费模型，真实验收尚待执行。

审查还修正笔记更新的复用资格：更新后从 current_notes 移除，必须由后续实际请求重新确认，防止同动作更新笔记并立即生成报告。
