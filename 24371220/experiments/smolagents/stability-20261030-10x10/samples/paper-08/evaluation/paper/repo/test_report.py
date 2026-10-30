"""只检查报告结构；事实、引用和真实阅读过程由 eval_paper.py 核对。"""
import json
from pathlib import Path


def test_report_format():
    report = json.loads(Path("report.json").read_text(encoding="utf-8"))
    assert isinstance(report.get("overview"), str), "缺少 overview 总览"
    assert 0 < len(report["overview"].strip()) <= 600, "总览不能为空，且不能超过 600 字符"
    sections = report.get("sections")
    assert isinstance(sections, list), "sections 应为五个主题的数组"
    assert [x.get("id") for x in sections] == ["overview", "reasoning", "tool_use", "multi_agent", "outlook"]
    for section in sections:
        assert isinstance(section.get("summary"), str) and 0 < len(section["summary"].strip()) <= 600, "主题总结不能为空，最多 600 字符"
        assert isinstance(section.get("application"), str) and 0 < len(section["application"].strip()) <= 300, "联系自己的 agent 不能为空，最多 300 字符"
        assert isinstance(section.get("answers"), dict), "answers 应为对象"
        assert isinstance(section.get("evidence"), list) and len(section["evidence"]) == 2
        for source in section["evidence"]:
            assert type(source.get("page")) is int and 1 <= source["page"] <= 52
            assert isinstance(source.get("question"), str)
            assert 20 <= len(source.get("quote", "").strip()) <= 1500
