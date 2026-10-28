import hashlib
import json
from pathlib import Path

import pytest

from codeagent.context import ContextBuilder
from codeagent.evidence import EvidenceStore


def _prepare(messages):
    return {"messages": messages, "model": "test"}


def test_symbol_observation_keeps_exact_source_and_exposure_gate(tmp_path):
    src = "@decorator\ndef f():\n    return '原样'\n"
    store = EvidenceStore(lambda *a, **k: None, tmp_path)
    ids = store.observe("read_symbol", {"path": "a.py", "symbol": "f"},
                        {"path": "a.py", "content": src, "file_hash": "h", "start_line": 1, "end_line": 3}, "s1")
    assert store.records[ids[0]]["content"] == src
    with pytest.raises(ValueError, match="successfully exposed"):
        store.save_note("A sufficiently long note derived from source evidence.", ids, "overview", "r", "A sufficiently long note derived from source evidence.", "r")
    store.mark_sent("r", ids)
    store.mark_response("r", True)
    note = "A sufficiently long note derived from source evidence."
    assert store.save_note(note, ids, "overview", "resp1", json.dumps({"text": note}, ensure_ascii=False), "r")["version"] == 1


def test_escaped_response_text_accepted_but_fabrication_rejected(tmp_path):
    s = EvidenceStore(None, tmp_path)
    ids = s.observe("read_range", {"path": "x.py"}, {"path": "x.py", "content": "abc", "file_hash": "h"}, 1)
    s.mark_sent("q", ids); s.mark_response("q")
    note = "这是一条基于证据并且长度超过二十个字符的事实笔记"
    assert s.save_note(note, ids, "tool_use", "z", json.dumps(note, ensure_ascii=True), "q")
    with pytest.raises(ValueError, match="actual response"):
        s.save_note("这是凭空编造出来的完全不同的笔记内容", ids, "tool_use", "z", json.dumps("没有这段"), "q")


def test_invalidation_cascades_across_file_note_dependencies(tmp_path):
    path = tmp_path / "a.py"; path.write_text("old", encoding="utf-8")
    h = hashlib.sha256(b"old").hexdigest()
    s = EvidenceStore(None, tmp_path)
    eid = s.observe("read_file", {"path": "a.py"}, {"path": "a.py", "content": "old", "file_hash": h}, 1)[0]
    s.mark_sent("q", [eid]); s.mark_response("q")
    n = s.save_note("这是一条基于源码并且长度达到要求的笔记内容", [eid], "overview", "r", "这是一条基于源码并且长度达到要求的笔记内容", "q")
    (tmp_path / "a.py").write_text("new", encoding="utf-8")
    s.refresh()
    assert s.records[eid]["status"] == "invalid"
    assert s.records[n["id"]]["status"] == "invalid"
    assert not s.latest_notes()


def test_pdf_pages_are_sent_in_fitting_batches_and_never_truncated(tmp_path):
    s = EvidenceStore(None, tmp_path)
    pages = [{"page": i, "text": f"PAGE-{i}-" + "中" * 70} for i in range(1, 4)]
    s.observe("read_pdf", {}, {"content": {"pages": pages}}, "pdf")
    first = ContextBuilder(soft_limit=500, hard_limit=1000).build([], [], s, {}, _prepare)
    assert len(first["evidence_ids"]) == 1
    sent = first["evidence_ids"]
    assert s.records[sent[0]]["content"].endswith("中" * 70)
    s.mark_sent("req1", sent); s.mark_response("req1")
    second = ContextBuilder(soft_limit=500, hard_limit=1000).build([], [], s, {}, _prepare)
    assert second["evidence_ids"] and second["evidence_ids"][0] != sent[0]


def test_large_full_file_uses_catalog_and_required_overflow_errors(tmp_path):
    s=EvidenceStore(None,tmp_path)
    rid=s.observe("read_file", {"path":"big.py"}, {"path":"big.py","content":"x"*1000,"file_hash":"h"},1)[0]
    out=ContextBuilder(soft_limit=250,hard_limit=300).build([],[],s,{},_prepare)
    assert "catalog:"+rid in out["selected"] and rid not in out["evidence_ids"]
    with pytest.raises(ValueError,match="超过硬限制"):
        ContextBuilder(soft_limit=100,hard_limit=300).build([],[],s,{"required_evidence_ids":[rid]},_prepare)


def test_history_keeps_complete_action_result_pairs(tmp_path):
    s=EvidenceStore(None,tmp_path)
    history=[{"step_id":i,"assistant":f"ACTION-{i}","observation":f"RESULT-{i}"} for i in range(5)]
    out=ContextBuilder(soft_limit=115,hard_limit=1000).build([],history,s,{},_prepare)
    roles=[m["content"] for m in out["messages"]]
    for i in range(5):
        assert (f"ACTION-{i}" in roles) == (f"RESULT-{i}" in roles)
    assert out["chars"] == len(json.dumps(_prepare(out["messages"]),ensure_ascii=False,separators=(",",":")))


def test_course_note_events_update_chain_and_final_five_topic_pin(tmp_path):
    events=[]; s=EvidenceStore(lambda e,**k:events.append((e,k)),tmp_path)
    eid=s.observe("read_symbol",{"path":"agent.py"},{"path":"agent.py","content":"def f(): return 1","file_hash":"h"},"read")[0]
    def note(text,topic,rid,request,sources):
        s.mark_sent(request,sources);s.mark_response(request,True)
        return s.save_note(text,sources,topic,rid,f"```python\nnote = {text!r}\n```",request)
    one=note("课程项目的整体结构与主要目标说明，记录架构边界和评测场景。", "overview","r1","q1",[eid])
    two=note("课程项目的整体结构以及目标说明补充，包含实现入口和复现路径。", "overview","r2","q2",[one["id"]])
    assert one["version"]==1 and two["version"]==2
    assert events[-1][0]=="section_note" and events[-1][1]["section"]=="overview"
    assert s.latest_notes()["overview"]["id"]==two["id"]
    for topic in ("reasoning","tool_use","multi_agent","outlook"):
        note(f"课程场景下{topic}主题的简明说明文字，包含必要的来源依据和适用范围。",topic,"r-"+topic,"q-"+topic,[eid])
    assert len(s.latest_notes())==5
    assert all("content" not in r for r in s.summary()["catalog"])
    out=ContextBuilder(soft_limit=5000,hard_limit=6000).build([],[],s,{"final_notes":True},_prepare)
    assert {x["id"] for x in s.latest_notes().values()} <= set(out["evidence_ids"])


def test_pdf_top_level_pages_hash_and_progress_under_history_pressure(tmp_path):
    pdf=tmp_path/"paper.pdf";pdf.write_bytes(b"pdf bytes")
    digest=hashlib.sha256(pdf.read_bytes()).hexdigest()
    s=EvidenceStore(None,tmp_path)
    ids=s.observe("read_pdf",{"pdf":"paper.pdf"},{"pdf":"paper.pdf","pages":[{"page":1,"text":"第一整页"*30},{"page":2,"text":"第二整页"*30}]},"pdf")
    assert s.records[ids[0]]["file_hash"]==digest
    history=[{"step_id":i,"assistant":"A"*100,"observation":"O"*100} for i in range(20)]
    out=ContextBuilder(soft_limit=450,hard_limit=600).build([],history,s,{},_prepare)
    assert out["evidence_ids"]
    assert s.records[out["evidence_ids"][0]]["content"] in ["第一整页"*30,"第二整页"*30]
    s.mark_sent("bad",out["evidence_ids"]);s.mark_response("bad",False)
    assert s.records[out["evidence_ids"][0]]["status"]=="valid"
    s.invalidate("paper.pdf","changed")
    assert all(s.records[i]["status"]=="invalid" for i in ids)


def test_invalid_evidence_cannot_be_resurrected_and_missing_required_fails(tmp_path):
    s=EvidenceStore(None,tmp_path)
    rid=s.observe("read_range",{"path":"x.py"},{"path":"x.py","content":"source","file_hash":"h"},1)[0]
    s.invalidate("x.py","new")
    s.mark_sent("q",[rid]);s.mark_response("q",True)
    assert s.records[rid]["status"]=="invalid"
    with pytest.raises(ValueError,match="invalid"):
        ContextBuilder().build([],[],s,{"required_evidence_ids":[rid]},_prepare)
    with pytest.raises(ValueError,match="five latest topic notes"):
        ContextBuilder().build([],[],s,{"final_notes":True},_prepare)


def test_same_source_can_be_reused_and_escaped_note_code_is_parsed(tmp_path):
    s=EvidenceStore(None,tmp_path);rid=s.observe("read_symbol",{"path":"x.py"},{"path":"x.py","content":"def f(): pass","file_hash":"h"},1)[0]
    first=ContextBuilder(soft_limit=1000,hard_limit=1200).build([],[],s,{},_prepare)
    assert rid in first["evidence_ids"]
    s.mark_sent("q1",first["evidence_ids"]);s.mark_response("q1")
    again=ContextBuilder(soft_limit=1000,hard_limit=1200).build([],[],s,{},_prepare)
    assert rid in again["evidence_ids"] # current evidence is reusable until its version expires
    content="课程证据引用产生的一条足够长的事实笔记，并记录适用范围。"
    escaped=content.encode("unicode_escape").decode("ascii")
    response='```python\nnote = "'+escaped+'"\n```'
    # A successful source may be cited again only through a note sent in this response request.
    s.mark_sent("q2",[rid]);s.mark_response("q2")
    assert s.save_note(content,[rid],"reasoning","response",response,"q2")


def test_evidence_mode_reuses_notes_and_selected_manifest_is_exact(tmp_path):
    events=[]
    s=EvidenceStore(lambda e,**k: events.append((e,k)),tmp_path)
    rid=s.observe('read_range',{'path':'x.py'},{'path':'x.py','content':'original','file_hash':'h'},1)[0]
    s.mark_sent('q',[rid]);s.mark_response('q')
    content='A source-derived note with enough detail for a later decision.'
    note=s.save_note(content,[rid],'','response',content,'q')
    out=ContextBuilder().build([],[],s,{},_prepare)
    assert note['id'] in out['evidence_ids']
    assert {r['id'] for r in events[-1][1]['manifest']} == set(out['evidence_ids'])
    s.invalidate('x.py','changed')
    assert not ContextBuilder().build([],[],s,{},_prepare)['evidence_ids']


def test_evidence_paths_cannot_escape_workspace(tmp_path):
    s=EvidenceStore(None,tmp_path)
    with pytest.raises(ValueError,match='inside the workspace'):
        s.observe('read_pdf',{}, {'pdf':'../outside.pdf','pages':[{'page':1,'text':'x'}]},1)
    with pytest.raises(ValueError,match='inside the workspace'):
        s.observe('read_file',{}, {'path':'../outside.py','content':'x'},1)
