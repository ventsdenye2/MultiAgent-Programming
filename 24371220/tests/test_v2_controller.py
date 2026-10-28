"""Offline controller integration coverage; all model replies use a fake transport."""
import json
from pathlib import Path
import sys

import pytest

from codeagent.controller import CodeAgent
from codeagent.recording import RunLog
from codeagent.policies import TaskSpec


VERIFY = ["python", "verify.py"]


def make_agent(tmp_path, replies, *, action_mode="code", profile="generic", editable=None,
               required_reads=None, verify_commands=None, paper_pages=(), topics=(), require_write=True):
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    repo.mkdir(exist_ok=True)
    (repo / "target.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    (repo / "verify.py").write_text(
        "from pathlib import Path\ntext = Path('target.py').read_text()\nraise SystemExit(0 if \"VALUE = 'new'\" in text or \"VALUE = 'old'\" in text else 1)\n",
        encoding="utf-8")
    editable = set(editable or {"target.py"})
    verify_commands = verify_commands if verify_commands is not None else [VERIFY]
    spec = TaskSpec("Change the requested target and verify it.", repo, profile, editable,
                    max_calls=max(10, len(replies) + 1), hard_chars=12000, soft_chars=10000,
                    timeout=120, required_reads=set(required_reads if required_reads is not None else editable),
                    verify_commands=[list(x) for x in verify_commands], paper_pages=tuple(paper_pages),
                    topics=tuple(topics), require_write=require_write, strict_plan_titles=False)
    config = {"model": "fake", "command_timeout": 10,
              "command_rules": [["python", "verify.py"]]}
    log = RunLog(out)
    bodies = []
    def transport(body):
        bodies.append(body)
        index = len(bodies) - 1
        content = replies[index](body) if callable(replies[index]) else replies[index]
        return {"model": "fake", "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
    agent = CodeAgent(spec, config, out, log, auto=True, action_mode=action_mode, transport=transport)
    return agent, log, bodies, repo, out


def close(log):
    log.close()


def code(text):
    return "```python\n" + text + "\n```"


def test_python_full_run_roundtrips_source_and_writes_verifies_finishes(tmp_path):
    plan = [{"title": "Update target", "status": "doing"}]
    first = code(
        f"update_plan(items={plan!r})\n"
        "source = read_file(path='target.py')\n"
        "baseline = run_command(argv=['python', 'verify.py'], cwd='.')"
    )
    second = code(
        "replace_text(path='target.py', old_text=\"VALUE = 'old'\", "
        "new_text=\"VALUE = 'new'\", expected_hash=source['file_hash'])\n"
        "checked = run_command(argv=['python', 'verify.py'], cwd='.')\n"
        "update_plan(items=[{'title':'Update target','status':'done'}])\n"
        "finish(summary='updated and verified')"
    )
    agent, log, bodies, repo, out = make_agent(tmp_path, [first, second])
    try:
        result = agent.run()
        assert result["status"] == "succeeded", result
        assert (repo / "target.py").read_text(encoding="utf-8") == "VALUE = 'new'\n"
        # Exact source appears in a later request after context selection, not merely in tool output.
        later = "\n".join(m["content"] for m in bodies[1]["messages"])
        assert "VALUE = 'old'" in later
        assert result["usage"] == {"complete": True, "requests": 2, "input_tokens": 20,
                                  "output_tokens": 4, "total_tokens": 24, "attempted_requests": 2}
        evidence = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
        source_id = next(i for i, r in evidence.items() if r["kind"] == "file")
        assert evidence[source_id]["successful_requests"]
        records = [json.loads(line) for line in (out / "run.log").read_text(encoding="utf-8").splitlines()]
        req_events = [e for e in records if e["event"] == "model_request"]
        assert len(req_events) == 2
        assert {"tool_call", "tool_result", "file_read", "file_write", "command_result", "finish"} <= {e["event"] for e in records}
        read_result = next(e["result"] for e in records if e["event"] == "tool_result" and e.get("action", {}).get("tool") == "read_file")
        assert source_id in read_result["evidence_ids"]
        assert source_id in "\n".join(m["content"] for m in req_events[1]["body"]["messages"])
        assert result["state"]["verification"]["python verify.py"]["rc"] == 0
        assert result["state"]["verification"]["python verify.py"]["fingerprint"]["target.py"] == agent.workspace.current_hash("target.py")
        assert any(e["event"] == "tool_call" and e.get("name") == "finish" for e in records)
        assert (out / "run-result.json").is_file() and (out / "patch.diff").is_file()
        assert result["evaluation_status"] == "not_run"
    finally:
        close(log)


def test_json_legacy_aliases_read_plan_write_and_finish(tmp_path):
    replies = [
        '{"tool":"plan","items":[{"title":"Update target","status":"doing"}]}',
        '{"tool":"read","path":"target.py"}',
        '{"tool":"command","argv":["python","verify.py"],"cwd":"."}',
        json.dumps({"tool":"write","path":"target.py","content":"VALUE = 'new'\n"}),
        '{"tool":"command","argv":["python","verify.py"],"cwd":"."}',
        '{"tool":"plan","items":[{"title":"Update target","status":"done"}]}',
        '{"tool":"finish","summary":"JSON flow done"}',
    ]
    agent, log, bodies, repo, out = make_agent(tmp_path, replies, action_mode="json")
    try:
        result = agent.run()
        assert result["status"] == "succeeded", result
        assert (repo / "target.py").read_text(encoding="utf-8") == "VALUE = \'new\'\n"
        assert len(bodies) == 7
    finally:
        close(log)


def test_write_gates_require_baseline_and_current_source_manifest(tmp_path):
    agent, log, _, repo, _ = make_agent(tmp_path, [code("finish(summary='unused')")], profile="source")
    try:
        agent.reducer.update_plan([{"title": "Edit", "status": "doing"}])
        agent.state.full_reads.add("target.py")
        args = {"path": "target.py", "old_text": "old", "new_text": "new",
                "expected_hash": agent.workspace.current_hash("target.py")}
        with pytest.raises(ValueError, match="baseline verification"):
            agent.invoke("replace_text", args)
        agent.state.baseline["python verify.py"] = {"rc": 0}
        with pytest.raises(ValueError, match="source evidence"):
            agent.invoke("replace_text", args)
        ids = agent.evidence.observe("read_file", {"path": "target.py"},
             {"path": "target.py", "content": "VALUE = 'old'\n", "file_hash": args["expected_hash"]}, "s")
        agent.current_manifest = ids
        assert agent.invoke("replace_text", args)["changed"]
    finally:
        close(log)


def test_verification_with_old_fingerprint_cannot_finish_after_external_change(tmp_path):
    agent, log, _, repo, _ = make_agent(tmp_path, [code("finish(summary='unused')")])
    try:
        agent.reducer.update_plan([{"title": "Edit", "status": "doing"}])
        agent.state.full_reads.add("target.py")
        agent.state.baseline["python verify.py"] = {"rc": 0}
        args = {"path": "target.py", "old_text": "old", "new_text": "new",
                "expected_hash": agent.workspace.current_hash("target.py")}
        agent.invoke("replace_text", args)
        agent.invoke("run_command", {"argv": VERIFY, "cwd": "."})
        (repo / "target.py").write_text("VALUE = 'other'\n", encoding="utf-8")
        agent.reducer.update_plan([{"title": "Edit", "status": "done"}])
        with pytest.raises(ValueError, match="Current files have not passed"):
            agent._finish("stale check")
    finally:
        close(log)


def test_paper_page_and_five_note_write_gate(tmp_path):
    topics = ("overview", "reasoning", "tool_use", "multi_agent", "outlook")
    agent, log, _, _, _ = make_agent(tmp_path, [code("finish(summary='unused')")], profile="paper",
                                     paper_pages=(1, 2), topics=topics)
    try:
        agent.reducer.update_plan([{"title": "Write report", "status": "doing"}])
        agent.state.full_reads.update(agent.spec.required_reads)
        agent.state.baseline["python verify.py"] = {"rc": 0}
        source_ids = agent.evidence.observe("read_pdf", {"pdf": "paper.pdf"},
              {"pdf": "paper.pdf", "pages": [{"page": 1, "text": "page one source"}, {"page": 2, "text": "page two source"}]}, "paper")
        agent.evidence.mark_sent("note-request", source_ids[:1])
        agent.evidence.mark_response("note-request", True)
        for topic in topics:
            content = f"课程论文主题 {topic} 的证据笔记，记录页面来源和论述范围。"
            note = agent.evidence.save_note(content, [source_ids[0]], topic, "resp", content, "note-request")
            agent.current_manifest.append(note["id"])
        agent.current_manifest = [r["id"] for r in agent.evidence.latest_notes().values()]
        with pytest.raises(ValueError, match="PDF pages"):
            agent._write_guard({"path": "target.py"})
        agent.evidence.mark_sent("paper-request", source_ids)
        agent.evidence.mark_response("paper-request", True)
        agent.current_manifest = source_ids
        with pytest.raises(ValueError, match="All five latest notes"):
            agent._write_guard({"path": "target.py"})
        agent.current_manifest = [r["id"] for r in agent.evidence.latest_notes().values()] + source_ids
        agent._write_guard({"path": "target.py"})
    finally:
        close(log)


def test_missing_usage_stops_before_action_without_retry(tmp_path):
    agent, log, bodies, repo, out = make_agent(tmp_path, [code("update_plan(items=[{'title':'x','status':'doing'}])")])
    def no_usage(body):
        bodies.append(body)
        return {"model": "fake", "choices": [{"message": {"content": code("update_plan(items=[{'title':'x','status':'doing'}])")}}]}
    agent.model.transport = no_usage
    try:
        result = agent.run()
        assert result["status"] == "incomplete" and "USAGE_INCOMPLETE" in result["reason"]
        assert len(bodies) == 1 and agent.state.plan == []
        assert result["usage"]["attempted_requests"] == 1
    finally:
        close(log)


def test_tool_error_is_logged_and_patch_artifact_survives_run(tmp_path):
    agent, log, _, repo, out = make_agent(tmp_path, [code("read_file(path='missing.py')")])
    try:
        result = agent.run()
        assert result["status"] == "incomplete"
        assert (out / "patch.diff").is_file()
        events = [json.loads(line)["event"] for line in (out / "run.log").read_text(encoding="utf-8").splitlines()]
        assert "tool_error" in events and "run_finished" in events
        assert (out / "run-result.json").is_file() and (out / "evidence.json").is_file()
    finally:
        close(log)


def test_direct_read_source_helper_creates_relative_hashed_range_evidence(tmp_path):
    agent, log, _, repo, _ = make_agent(tmp_path, [code("finish(summary='unused')")], require_write=False)
    try:
        helper = repo / "read_source.py"
        helper.write_text(
            "import json\nfrom pathlib import Path\n"
            "print(json.dumps({'path': str(Path(__file__).parent / 'target.py'), 'ranges': "
            "[{'start_line': 1, 'end_line': 1, 'content': \"VALUE = 'old'\\n\"}]}))\n",
            encoding="utf-8")
        result = agent.invoke("run_command", {"argv": [sys.executable, "read_source.py", "--file", "target.py", "--search", "VALUE", "--lines", "1"], "cwd": "."})
        assert result["rc"] == 0 and result["evidence_ids"]
        evidence = [agent.evidence.records[i] for i in result["evidence_ids"]]
        assert len(evidence) == 1
        assert evidence[0]["kind"] == "range" and evidence[0]["path"] == "target.py"
        assert evidence[0]["content"] == "VALUE = 'old'\n"
        assert evidence[0]["file_hash"] == agent.workspace.current_hash("target.py")
        assert evidence[0]["start_line"] == evidence[0]["end_line"] == 1
    finally:
        close(log)


def test_timed_out_verification_cannot_count_as_baseline_or_finish(tmp_path):
    agent, log, _, repo, _ = make_agent(tmp_path, [code("finish(summary='unused')")],
                                        verify_commands=[["python", "slow.py"]], require_write=False)
    try:
        (repo / "slow.py").write_text("import time\ntime.sleep(1)\n", encoding="utf-8")
        agent.config["command_rules"].append(["python", "slow.py"])
        agent.workspace.command_rules.append(["python", "slow.py"])
        agent.config["command_timeout"] = 0.05
        agent.workspace.command_timeout = 0.05
        result = agent.invoke("run_command", {"argv": ["python", "slow.py"], "cwd": "."})
        key = "python slow.py"
        assert result["timed_out"] is True and result["rc"] != 0
        assert key not in agent.state.baseline and key not in agent.state.verification
        agent.reducer.update_plan([{"title": "Verify", "status": "done"}])
        with pytest.raises(ValueError, match="Current files have not passed"):
            agent._finish("must not accept timeout")
    finally:
        close(log)
