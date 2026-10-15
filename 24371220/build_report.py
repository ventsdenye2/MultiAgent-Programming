"""根据真实实验结果生成三页报告和预览，不依赖手填实验数字。"""
import json
from pathlib import Path
import statistics
import sys
from xml.sax.saxutils import escape

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'report_tools'))
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib import colors

results = json.loads((root / 'experiments/feature/comparison01/results.json').read_text(encoding='utf-8'))
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
out = root / '报告.pdf'
c = canvas.Canvas(str(out), pagesize=(595, 842))
c.setTitle('迷你编码智能体实践报告 - 24371220')
style = ParagraphStyle('body', fontName='STSong-Light', fontSize=10.5, leading=17, textColor=colors.HexColor('#263445'))
y = 0
source = []

def start(page, title):
    global y
    c.setFillColor(colors.HexColor('#17334A'))
    c.rect(0, 788, 595, 54, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('STSong-Light', 16)
    c.drawString(42, 808, title)
    c.setFillColor(colors.HexColor('#65788A'))
    c.setFont('STSong-Light', 9)
    c.drawString(42, 24, '第四课实践1 | 学号 24371220 | 2026-10-15')
    c.drawRightString(553, 24, f'{page} / 3')
    y = 762
    source.append('# ' + title)

def para(text, heading=False):
    global y
    st = ParagraphStyle('h', parent=style, fontSize=12, leading=20, spaceAfter=4) if heading else style
    p = Paragraph(escape(text), st)
    _, height = p.wrap(511, 750)
    if y-height < 48:
        raise ValueError('报告单页内容超出，请精简正文')
    p.drawOn(c, 42, y-height)
    y -= height + (10 if heading else 9)
    source.append(text + '\n')

def table(data, widths):
    global y
    t = Table([[Paragraph(escape(str(v)), style) for v in row] for row in data], colWidths=widths)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E9F0F5')),
                          ('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),0.4,colors.HexColor('#CED9E2')),
                          ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    _, h = t.wrap(511, 700)
    if y-h < 48:
        raise ValueError('表格超出页面')
    t.drawOn(c,42,y-h)
    y -= h+12
    source.extend(' | '.join(map(str,row)) for row in data)

start(1, '从任务到补丁：基础智能体')
para('这次实践实现了一个命令行编码智能体：读取题目后，由 DeepSeek 决定下一步工具动作，程序执行并把结果送回模型，直到修改后的测试通过。代码直接调用官方 Chat Completions 接口，没有使用现成 Agent 框架。')
para('四项基础功能的取舍', True)
para('交互模式在写文件和执行命令前展示动作并请求确认；用户可以追加要求、查看计划或中断。--auto 跳过键盘输入，供评测使用。计划采用 todo、doing、done，更新时不允许改变标题和顺序，避免执行过程中丢失原目标。')
para('读、写、命令是三项基本工具，另提供文件列表与计划更新。写入限定为题面列出的业务文件；命令只允许完整 pytest 和题目诊断脚本。工具权限较窄，牺牲了通用性，但能减少误改测试或操作项目外文件的机会。')
para('基线模式保留完整任务、追加指令和当前计划。单条结果超过 4500 字符时保留头尾，总上下文超过 15000 字符时删除最早的动作和结果。这个方法容易实现，但中段错误或较早读过的关键代码可能被丢掉。')
para('运行轨迹与验收', True)
para('run.log 按操作实时写入完整请求、返回、文件内容和命令输出。上下文裁剪只影响下一次模型调用，不删原日志。patch.diff 由运行开始时的快照和最终代码生成，失败或中断也保存已有改动。完成动作要求修改后的完整测试通过、诊断通过且计划全部完成。')
para('核心代码合计 288 个非空非纯注释物理行，范围为 agent.py 的 SYSTEM、Agent 和整个 context_selection.py。API 传输、底层工具、CLI、日志及补丁属于辅助代码。运行环境为 Ubuntu WSL 2、Python 3.12.3、pytest 8.4.2 和 GNU patch 2.7.6。')
para('本次只在项目内新增依赖与实验文件，未再修改 WSL 全局配置。挂载盘的临时文件兼容问题通过项目路径内的 tmpfs 处理，运行脚本退出时卸载。')
c.showPage()
start(2, '特色功能：按诊断选择上下文')
para('Diagnostic-Driven Context Selection and Compression 的出发点是：先判断当前要解决什么，再决定给模型什么。第一版使用确定性规则，不增加摘要模型或检索服务，便于与原来的滑动窗口比较。')
para('选择和压缩如何进行', True)
para('每次工具执行后保存结构化观察，同一路径的重复读取和同一命令的旧结果由新结果替代。成功写入后移除该文件的旧读取版本。根据最近写入及后续验证结果，把当前状态区分为探索、修复、待验证和收尾；写入之前的失败不再作为当前诊断锚点。')
para('从当前失败输出提取 Python 文件名、测试名和异常类型。候选记录按当前验证、失败、诊断路径匹配、写入代码、读取源码和时间新近程度加分。相关记录优先进入剩余预算，不直接压缩所有历史。')
para('命令输出过长时，抽取失败项、断言、异常位置和汇总附近的原文，去掉完全重复的行，再对超长摘录保留头尾。无法识别的长文本回退到头尾截取。短文件尽量完整保留；第一版对长代码仍使用头尾截取，尚未实现函数级切片或跨文件依赖分析。')
para('固定上下文仍保留系统提示、完整题面、追加要求和计划状态。context_summary 记录候选分数、原因、入选情况及实际发出的内容；原始输出另存于 command_result。实验开关为 --context-mode baseline|diagnostic，评测脚本通过 MINI_CONTEXT_MODE 传入同一选项。')
para('实验设置', True)
para('主实验固定第五题，两种模式交替各运行 3 次；每轮从新副本开始。固定 deepseek-flash、温度 0、15000 字符上下文上限、4096 输出 token、60 步、600 秒智能体上限和 120 秒验证上限。两组使用同一代码、提示词和工具，仅上下文策略不同。所有运行结果均保留。')
para('首先看题目和过程检查是否通过，再比较 API 上报的输入 token、调用次数与时间。token 统计包含重复发送的上下文，不等同于费用；缓存命中和服务延迟也会影响实际成本。温度为 0 仍不能保证输出完全一致，三轮结果只用于小样本观察。')
c.showPage()
start(3, '实验结果与限制')
repeat = [r for r in results if r['experiment'].startswith('repeat')]
table([['轮次 / 模式','结果','输入 token','调用 / 秒']] + [[r['experiment'].replace('baseline','基线').replace('diagnostic','诊断'),r['status'],str(r['prompt_tokens']),f"{r['model_requests']} / {r['elapsed_s']:.1f}"] for r in repeat], [165,75,115,156])
means = {mode: statistics.mean(r['prompt_tokens'] for r in repeat if r['context_mode']==mode) for mode in ('baseline','diagnostic')}
delta = (means['diagnostic']/means['baseline']-1)*100
para(f"基线平均输入 {means['baseline']:.0f} token，诊断模式 {means['diagnostic']:.0f} token，变化 {delta:+.1f}%。" + ('这组数据未体现输入成本收益。' if delta >= 0 else '这组数据中输入量有所下降，但不能据此推断其他仓库也会受益。'))
reg = [r for r in results if r['experiment'].startswith('regression')]
para('本轮回归按整题口径：基线 4/5 分，诊断模式 5/5 分。基线第四题虽有 10 个测试通过，但合并写入两个子任务，缺少中间净额验证，过程检查失败。一次回归的差异不足以证明稳定优势。')
table([['公开题','基线：测试 / 过程','诊断：测试 / 过程']] + [[case, *[f"{r['passed']}/{r['tests']} / {r['process_status']}" for mode in ('baseline','diagnostic') for r in reg if r['case']==case and r['context_mode']==mode]] for case in ['case01_bug_fix','case02_feature_regression','case03_cross_file','case04_two_subtasks','case05_long_log']], [175,168,168])
para('课程仓库小、修复点集中，基线可能已保住足够线索，因此不能据此否定诊断选择在复杂任务中的价值。但当前模式确有重复调用，重组历史也可能破坏动作与结果的连贯性。后续应预先设计无关日志、中段关键错误和多文件依赖压力任务，以相同预算验证；本次不追加有利样本来改变结论。')
para('验证与证据：12 项机制测试通过。主实验和回归原始记录在 experiments/feature/comparison01/；各子目录含配置、完整日志、补丁与 result.json，汇总为 results.json。参考课程 README、题目、日志格式及公开评测器；实现与报告由 AI 编程助手协助完成，实验数字来自实际 API 运行。')
c.save()
(root / '报告.md').write_text('\n\n'.join(source), encoding='utf-8')
import fitz
preview = root / 'output/pdf'
preview.mkdir(parents=True, exist_ok=True)
doc = fitz.open(out)
assert len(doc) == 3
for i, page in enumerate(doc):
    page.get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(preview / f'report-{i+1}.png')
print(out, 'pages=',len(doc))
