"""真实结果驱动的三页报告：基础设计、诊断流程、实验结论。"""
import json
from pathlib import Path
import statistics
import sys
from xml.sax.saxutils import escape

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'report_tools'))
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib import colors
import fitz

rows = json.loads((root / 'experiments/feature/comparison01/results.json').read_text(encoding='utf-8'))
assert len(rows) == 16, '实验未完整，停止生成最终报告'
for name, filename in [('Body', 'msyh.ttc'), ('Bold', 'msyhbd.ttc')]:
    pdfmetrics.registerFont(TTFont(name, 'C:/Windows/Fonts/' + filename, subfontIndex=0))
INK, MUTED, TEAL, LINE, PAPER = map(colors.HexColor, ['#182E3A', '#60747D', '#177D83', '#D9E3E5', '#F0F5F5'])
out = root / '报告.pdf'
c = canvas.Canvas(str(out), pagesize=(595, 842))
c.setTitle('迷你编码智能体实践报告 | 24371220')
base = ParagraphStyle('body', fontName='Body', fontSize=9.5, leading=16, textColor=INK, wordWrap='CJK')
small = ParagraphStyle('small', parent=base, fontSize=8.2, leading=13)
source, y = [], 0


def pbox(text, x, top, width, style=base):
    p = Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    _, height = p.wrap(width, 800)
    p.drawOn(c, x, top-height)
    return height


def start(page, title, subtitle):
    global y
    c.setFillColor(TEAL)
    c.rect(38, 782, 25, 4, fill=1, stroke=0)
    c.setFont('Body', 8)
    c.setFillColor(MUTED)
    c.drawString(72, 781, 'CODING AGENT  /  实践报告')
    c.setFont('Bold', 21)
    c.setFillColor(INK)
    c.drawString(38, 744, title)
    pbox(subtitle, 38, 727, 519, small)
    c.setStrokeColor(LINE)
    c.line(38, 694, 557, 694)
    c.line(38, 42, 557, 42)
    c.setFillColor(MUTED)
    c.setFont('Body', 8)
    c.drawString(38, 26, '学号 24371220  ·  第四课实践1  ·  2026-10-15')
    c.drawRightString(557, 26, f'{page} / 3')
    y = 677
    source.extend(['# ' + title, subtitle, ''])


def heading(number, title):
    global y
    c.setFillColor(TEAL)
    c.setFont('Bold', 10)
    c.drawString(38, y-11, number)
    c.setFillColor(INK)
    c.setFont('Bold', 11)
    c.drawString(64, y-11, title)
    y -= 29
    source.append('## ' + title)


def para(text, compact=False):
    global y
    h = pbox(text, 38, y, 519, small if compact else base)
    y -= h + 12
    if y < 52:
        raise ValueError('正文溢出页面')
    source.extend([text, ''])


def table(data, widths, compact=False):
    global y
    cell = small if compact else base
    header = ParagraphStyle('head', parent=cell, fontName='Bold')
    t = Table([[Paragraph(escape(str(v)).replace('\n', '<br/>'), header if i == 0 else cell)
                for v in row] for i, row in enumerate(data)], colWidths=widths)
    t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), PAPER),
        ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LINEBELOW', (0,0), (-1,-1), .45, LINE),
        ('LEFTPADDING', (0,0), (-1,-1), 9), ('RIGHTPADDING', (0,0), (-1,-1), 9),
        ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8)]))
    _, h = t.wrap(519, 800)
    t.drawOn(c, 38, y-h)
    y -= h+16
    if y < 52:
        raise ValueError('表格溢出页面')
    source.append('| ' + ' | '.join(data[0]) + ' |')
    source.append('| ' + ' | '.join('---' for _ in data[0]) + ' |')
    source.extend('| ' + ' | '.join(map(str, r)) + ' |' for r in data[1:])
    source.append('')


def flow(labels, descriptions):
    global y
    count = len(labels)
    gap = 15
    width = (519-gap*(count-1))/count
    height = 79
    for i, (label, description) in enumerate(zip(labels, descriptions)):
        x = 38+i*(width+gap)
        c.setFillColor(PAPER)
        c.roundRect(x, y-height, width, height, 5, fill=1, stroke=0)
        pbox(label, x+9, y-10, width-18, ParagraphStyle('label', parent=base, fontName='Bold', fontSize=10))
        pbox(description, x+9, y-35, width-18, small)
        if i < count-1:
            c.setStrokeColor(TEAL)
            c.line(x+width+3, y-height/2, x+width+12, y-height/2)
            c.line(x+width+9, y-height/2+3, x+width+12, y-height/2)
            c.line(x+width+9, y-height/2-3, x+width+12, y-height/2)
    y -= height+17
    source.append(' → '.join(labels))
    source.extend(f'- {a}：{b}' for a,b in zip(labels, descriptions))
    source.append('')


def note(title, text):
    global y
    h = 36 + Paragraph(escape(text), small).wrap(495,800)[1]
    c.setFillColor(PAPER)
    c.rect(38,y-h,519,h,fill=1,stroke=0)
    c.setFillColor(TEAL)
    c.rect(38,y-h,3,h,fill=1,stroke=0)
    pbox(title,50,y-9,495,ParagraphStyle('note',parent=base,fontName='Bold'))
    pbox(text,50,y-31,495,small)
    y -= h+16
    source.extend(['**'+title+'**',text,''])


start(1, '迷你编码智能体：从任务到补丁', '自行实现模型、工具与执行器的最小闭环；不使用现成 Agent 框架。')
heading('01', '整体执行闭环')
flow(['读取任务', '模型决策', '执行工具', '验证交付'],
     ['保留题面与约束', '每轮一个 JSON 动作', '读写文件、运行测试', '真实日志与代码补丁'])
para('模型决定下一步做什么，程序负责参数检查、工具执行和状态更新。写入后重新验证；测试、诊断及计划全部完成，才允许正常结束。')
heading('02', '四项基础能力与取舍')
table([['能力','实现方式','边界 / 取舍'],
    ['用户交互','追加指令、查看计划、随时中断；\n写入和命令默认确认，--auto 自动执行。','人工可干预，评测不等待输入。'],
    ['上下文管理','固定保留题面和状态；基线对单条结果\n保留头尾，超预算删除最早动作与结果。','4500 字符单条阈值；\n15000 字符请求预算。'],
    ['任务管理','子目标跟踪 todo / doing / done；\n更新时固定标题和顺序。','执行先后仍依赖模型遵守，\n最终由课程过程检查核验。'],
    ['基础工具','完整读文件、写业务文件、执行命令；\n另提供文件列表与计划更新。','只写允许文件，只运行完整\npytest 或题目诊断脚本。']], [78,278,163], True)
heading('03', '轨迹与代码规模')
para('run.log 实时记录完整请求、响应、文件内容和命令输出；上下文压缩不会删除原日志。patch.diff 根据初始快照生成，失败或中断也保存已有改动。')
note('288 行核心代码 · 12 项机制测试通过',
     '核心包含 agent.py 的 SYSTEM、Agent 和全部 context_selection.py，按非空、非纯注释物理行计数；CLI、API 传输、日志和底层工具另计。环境：WSL 2 / Python 3.12.3 / pytest 8.4.2 / GNU patch 2.7.6。')
c.showPage()

start(2, '特色功能：先选信息，再压缩', 'Diagnostic-Driven Context Selection and Compression  /  确定性规则，无额外模型调用。')
heading('01', '一次模型请求前，做四步处理')
flow(['观察去重','诊断定位','相关性排序','预算内组装'],
     ['更新命令结果；\n写入使旧源码失效', '识别当前阶段；\n提取文件、测试、异常', '验证、失败、路径\n匹配与近期代码优先', '摘录诊断行、去重；\n超长内容再保留头尾'])
heading('02', '当前状态决定优先保留什么')
table([['状态','判断依据','优先信息'],
    ['探索定位','尚未形成有效诊断','题面、文件列表、已读业务代码'],
    ['修复失败','当前 pytest 或诊断返回失败','失败测试、异常位置、相关代码'],
    ['修改后验证','已写入，尚未完成测试验证','最近改动、待验证项、历史失败参考'],
    ['收尾','最近完整测试已通过','验证结果、计划完成状态']], [88,176,255])
para('状态用于信息排序，不代替完成检查。收尾时仍须满足诊断通过、计划全部 done；写入前的失败不再作为当前诊断锚点。', True)
heading('03', '预算和证据保持一致')
table([['固定保留','按相关性填入','始终保留在日志中'],
    ['系统提示、完整题面、\n追加要求、计划与验证状态','当前诊断摘录、相关源码、\n最近修改和必要工具结果','完整原输出；候选分数、\n选择原因与实际请求内容']], [173,173,173], True)
para('长命令输出抽取失败、断言及汇总附近原文，合并重复行。识别失败时退回头尾裁剪；长代码暂未实现函数级切片。baseline 与 diagnostic 共享提示词、工具和字符预算，仅改变上下文构造方式。')
note('同题、同模型、同预算，交替各跑 3 次',
     '主实验固定第五题，每轮使用新副本；再分别跑五题回归。deepseek-flash，温度 0，上下文 15000 字符，输出 4096 token，最多 60 步；智能体 600 秒、最终验证 120 秒。开关：--context-mode baseline|diagnostic。')
c.showPage()

start(3, '实验结果：通过了，成本未下降', '16 次真实运行全部保留；功能测试与过程检查分别报告，避免把代码正确等同于整题通过。')
repeat = [r for r in rows if r['experiment'].startswith('repeat')]
means = {mode: statistics.mean(r['prompt_tokens'] for r in repeat if r['context_mode']==mode) for mode in ('baseline','diagnostic')}
delta = (means['diagnostic']/means['baseline']-1)*100
heading('01', '第五题对照：两组均为 3 / 3 通过')
data = [['轮次','输入 token：基线 / 诊断','调用次数：基线 / 诊断','耗时秒：基线 / 诊断']]
for i in range(1,4):
    pair = [next(r for r in repeat if r['experiment']==f'repeat{i}_{mode}') for mode in ('baseline','diagnostic')]
    data.append([str(i),' / '.join(f"{r['prompt_tokens']:,}" for r in pair),
                 ' / '.join(str(r['model_requests']) for r in pair),
                 ' / '.join(f"{r['elapsed_s']:.1f}" for r in pair)])
table(data,[42,169,151,157],True)
para(f"平均输入量：基线 {means['baseline']:,.0f} token，诊断 {means['diagnostic']:,.0f} token（{delta:+.1f}%）。诊断模式三轮调用均更多，本次未观察到稳定的成本收益。输入 token 包含重复上下文，并不等于实际费用。")
heading('02', '五题回归：功能全过，过程仍有波动')
reg = [r for r in rows if r['experiment'].startswith('regression')]
labels = ['折扣修复','新增功能与回归','跨文件定位','净额修复 + CSV','长日志定位']
data = [['公开题','基线：测试 / 过程','诊断：测试 / 过程']]
for case,label in zip(['case01_bug_fix','case02_feature_regression','case03_cross_file','case04_two_subtasks','case05_long_log'],labels):
    pair = [next(r for r in reg if r['case']==case and r['context_mode']==mode) for mode in ('baseline','diagnostic')]
    data.append([label,*[f"{r['passed']}/{r['tests']}  /  {'通过' if r['process_status']=='passed' else '未通过'}" for r in pair]])
table(data,[173,173,173],True)
para('整题得分为基线 4/5、诊断 5/5。基线第四题合并写入两个子任务，跳过净额修复后的中间验证；最终 10 个功能测试虽通过，过程仍不合格。一次回归的差异不足以说明诊断模式更稳定。', True)
heading('03', '如何理解这组结果')
para('课程仓库小、修复点集中，基线可能已经保住足够线索，任务难度未必能体现智能选择的优势。但当前诊断模式确有重复调用，重组历史也可能削弱动作与结果的连贯性。这两种可能需要分开验证。', True)
para('下一步可预先设计无关日志、中段关键错误和多文件依赖压力任务，再按相同预算比较；本次不追加有利样本。温度 0 也不保证完全复现，三轮仅支持小样本观察。', True)
para('证据：experiments/feature/comparison01/ 下的 protocol.json、results.json 及各轮配置、完整日志、补丁。参考：课程 README、题目、日志规范和公开评测器。实现与报告由 AI 编程助手协助完成，数字来自真实 API 运行。', True)
c.save()
(root / '报告.md').write_text('\n\n'.join(source), encoding='utf-8')
preview = root / 'output/pdf'
preview.mkdir(parents=True, exist_ok=True)
doc = fitz.open(out)
assert len(doc) == 3
for i,page in enumerate(doc):
    page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(preview / f'report-{i+1}.png')
print(out, 'pages=',len(doc))
