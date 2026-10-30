# 已完成样本只读复核记录

这不是最终统计；最终样本数和成绩以 SUMMARY.md、summary.json 及每轮 sample.json 为准。以下 R 为模型请求号，seq 为相应 `evaluation/<task>/development/run.log` 的事件序号。Sol只读复核，未修改运行实现或评测产物。

## 源码01–04

各20次请求，均因 MAX_STEPS_NO_EXTRA_REQUEST 退出；官方读取及首次修改复用检查均为True。

- source-01：只改environ/logger，stats_logger未改；R15/18/19/20继续读取logger；R16/17出现DSML解析错误（seq233/241）。仅R3基线pytest，缺末次测试，0/1。
- source-02：R18三文件最终修改完成（seq285/289/299/303），R20完整pytest成功（seq341）。官方独立功能与日志链路均通过，但未done plan/final_answer；剩余仅finish plan。整题0/1，不等于功能实现失败。
- source-03：只改environ（R11 seq179），随后将replace返回当作含rc字典，引发KeyError（seq183）；R15 DSML解析失败；R19变量log与现有tool冲突（seq293）。R19/20继续三文件全文读取，缺logger/stats及末次测试，0/1。
- source-04：environ/logger已改，stats未改；R7/10 DSML错误（seq117/152）；R14自定义python -c被拒（seq196）；R18第一次logger replace后继续用旧hash，第二次replace失败（seq256）。R19/20读取/搜索，缺末测，0/1。

后两次请求中可见状态已说明 `first_write_reading_required=false`，并处于edit/verify阶段。因此“初读门槛被重新开启”不符合这些日志；反复读取的唯一原因无法仅从行为确定。

## 论文01–04

各40次请求；52/52页已曝光；五主题最终都有笔记；usage完整。

- paper-01：R39 reasoning笔记成功（seq492）后构造report遇到NoneType TypeError（seq495），未写报告；R40读取report及多段PDF，缺写入、末测和done，0/5。另R6 json未import（seq133）。
- paper-02：R39写report（seq502）、pytest成功（seq506）；R40再次pytest成功（seq524）、plan done（seq526），响应seq515含final_answer，正常completed。官方4.5/5：self_consistency_selection答案与原文不一致、quote不是该页原文且缺支撑。前置错误：R4/19未知或过期evidence id（seq117/274），R21 finditer对象混淆（seq296），R27笔记连续原文要求未满足（seq365）。
- paper-03：R35–40持续read_pdf/recall；R36将recall返回当pages取值发生KeyError（seq468）。R39/40状态已phase edit、要求make change，但未写report/末测/done，0/5。另R9笔记连续原文要求（seq167）、R18不存在或过期id（seq267）、R19 json未import（seq277）。
- paper-04：R39写report（seq649）、pytest成功（seq653）；R40 plan done（seq663），响应seq660含final_answer，正常completed。官方4.0/5：categories引用缺关键支持，camel_prompting引用不是页内原文。另R20笔记连续原文错误（seq293）、R28 DSML（seq487）。

paper-02/04是内容与引用质量失败，与paper-01/03未产出报告分开计类。上述原始错误和动作不自动构成因果证明；不据此声称增加提示或扩大预算即可解决。

前8轮共22条Agent错误：6条解析错误、16条执行错误。paper-04在R26/R27的单次模型响应内分别执行15/20次PDF读取，不能将这些本地调用计为35次API请求。

## 新增复核：05–06

- source-05：传输超时。R11请求seq167之后仅model_error seq168（NETWORK_OR_RESPONSE_ERROR/APITimeoutError），无第11次响应；11请求、10响应，usage不全。R9仅env写入seq144/148；R3基线测试seq75，R7/8的read_source参数含整数而要求字符串（seq128/136），R10复读env。R11发送状态仍有9次后续请求，不能归为20步耗尽。官方checks的“服务端真实用量完整=true”与原始审计矛盾，按缺失响应判定未知用量，不补零；无法据此定位具体服务端超时原因。
- source-06：20步耗尽。R11 env写入seq169后误取replace返回的rc导致KeyError seq173；R4读取受限.course/test_logger.py（seq81）、R6缩进错误（seq102）、R9 env_hash未定义（seq141）、R16 Python代码夹DSML字符导致SyntaxError（seq239，原始分类仍是执行错误）。R17搜索、R18范围读/list、R19读env、R20读env/__init__。缺logger/stats修改、末测及收尾；末两状态first_write=false。
- paper-05：40步耗尽，无report。52页与五主题齐。R31 json未import（seq401）、R33无效或过期recall ID（seq424）、R35 repr禁用（seq468）。R36读取报告、元数据及PDF1，R37/38回看多页。R39响应seq516确实包含write_file→pytest→plan→final_answer，但前置检查将整数当作字典下标访问，seq520报错，后续未执行。R40仅读报告seq527。不能声称模型完全未尝试安排收尾。
- paper-06：正常completed但4/5。R39写report seq515、pytest成功seq519；R40计划完成seq529、pytest成功seq533，响应seq526含final_answer，剩余为空。categories、agenda_topics两条quote不是对应页原文，其余八项通过。52页与五主题齐。7条执行错误：R3连续原文要求seq100；R25/30/37 repr禁用seq336/419/497；R26 ls -la禁用seq348；R27 json未import seq360；R31 globals禁用seq427。工具错误与引用不合格均有记录，但不能直接证明前者造成后者。

## 新增复核：07–08

- source-07：R18完成logger五次replace（seq273/277/280/283/286）和stats修改（seq289）；独立回归、运行链路均通过。只有R3基线pytest（seq61），未执行修改后的pytest。R19读取logger后变量log撞工具（seq306），R20继续读logger（seq313）；末段状态明确phase verify。其他错误为R4受限.course测试（seq75）、R16解析错误（seq253）。
- source-08：必须写“末测未通过”，不是“未执行末测”。R19修改stats（seq341）后完整pytest rc=1（seq345）。最终logger仅新增envs导入，预算构造、截断和默认handler接入未实现；R13第一次修改logger（seq246）后第二次使用旧hash失败（seq252），此后未再修复logger。外部regression.log为39 failed/21 passed，主要是构造参数不接受max_message_chars以及配置无法传至formatter。runtime.json：central_configuration=True、ordinary_message_bounded=False、statistics_message_complete=True、shared_original_record_preserved=True，不能概括成所有链路都坏。R20读取/搜索后触碰受限测试（seq369），没有修复。
- paper-07：40次请求，52页和五主题齐，usage完整。R40写report（seq538）后实际跑完整pytest（seq542），rc=1。overview.search_methods和tool_use.toolformer_tools保留page=0、quote为空，报告格式不合格。响应包含条件plan/final_answer，但因测试失败未完成收尾；应归“产物格式错误、成功验证未达成”，不是“未写报告/未运行测试”。R40还批量读取PDF 1–52。此前R23 json未import（seq342），R24/27解析错误（seq351/380），R36 finditer对象混淆（seq481）。
- paper-08：40次请求，52页与五主题齐，usage完整，无file_write。R36 recall 4–11；R37读取12/51–52；R38读取5/12/13/23后repr禁用（seq521）；R39读取9个页；R40 recall10/11/14/15。末段仍phase edit、要求make change。其他错误包括R1缺来源许可文件（seq27）、R17 evidence ID误写（seq253）、R26 repr（seq347）、R30 globals（seq408）、R34 repr（seq464）。不能据此推断52页未送达或初读门禁阻塞。

## 新增复核：09–10

- source-09：功能、链路、补丁及读取复用均通过；R19三文件写入（seq259/266/270/273/276/282）后pytest成功（seq286）。R20响应seq292本含update_plan+final_answer，但前置import os被官方执行器拒绝（seq296），后续收尾未执行。剩余只有finish plan，20步耗尽；不能仅归为忘记调用final。此前R11解析错误（seq162）、R16 python -c禁用（seq223）。
- source-10：18请求严格1/1通过。R6基线pytest rc1（seq95）；R8 env两写（seq122/126）；R13 logger四写（seq186/190/193/196）及stats（seq199）；R17完整pytest成功（seq251）；R18计划done（seq263），响应seq260含final_answer，completed、remaining空。中间R11有一次解析错误（seq162），所有官方检查最终True。
- paper-09：36请求5/5通过，52页与五主题齐。最后outlook笔记seq363；R33/34/35/36共同曝光最新版五笔记（seq404/415/426/443）。R34写报告seq417，R35 pytest成功seq433，R36计划完成seq444、pytest成功seq448，响应seq441含final_answer，remaining空。十问答案/引用全True。中间R2/30/33 repr禁用（seq31/376/409）、R15无效或过期id（seq228）后成功恢复。
- paper-10：40次耗尽，无报告，52页与五主题齐。R36/37仍读13/4/5/46；R38本地处理TypeError整数不可调用（seq497）。R39一响应读取9页（seq504–528），随后re.sub处理None引文报错（seq532）；响应seq501虽含write_file/pytest/plan/final，但均未执行。R40读取51页后repr禁用（seq543），没有写入/末测。另R9连续原文要求（seq166）、R12 globals禁用（seq197）、R28/30无效id（seq367/390）。
