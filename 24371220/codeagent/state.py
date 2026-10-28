"""Single reducer owns current state; logs/evidence retain history separately."""
from dataclasses import dataclass, field


@dataclass
class AgentState:
    status: str = "running"
    phase: str = "plan"
    plan: list = field(default_factory=list)
    full_reads: set = field(default_factory=set)
    writes: int = 0
    revision: int = 0
    baseline: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    focus_paths: list = field(default_factory=list)
    pending_finish: str | None = None

    def view(self):
        return {"status": self.status, "phase": self.phase, "plan": self.plan,
                "read_files": sorted(self.full_reads), "writes": self.writes,
                "workspace_revision": self.revision, "baseline": self.baseline,
                "verification": self.verification, "focus_paths": self.focus_paths}


class StateReducer:
    def __init__(self, spec, log):
        self.spec, self.log, self.state = spec, log, AgentState()

    def update_plan(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ValueError("Plan must contain 1..10 items")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
                raise ValueError("Plan title required")
            if item.get("status") not in {"todo", "doing", "done"}:
                raise ValueError("Invalid plan status")
        if self.spec.strict_plan_titles and self.state.plan:
            if [i["title"] for i in items] != [i["title"] for i in self.state.plan]:
                raise ValueError("Plan titles and order must remain stable")
        self.state.plan = [dict(i) for i in items]
        if self.state.phase == "plan":
            self.state.phase = "explore"
        self.log("plan", items=self.state.plan)
        return {"items": self.state.plan}

    def observe(self, name, args, result, fingerprint):
        state = self.state
        if name == "read_file":
            state.full_reads.add(result["path"])
        if name in {"read_file", "read_range", "read_symbol", "replace_text", "write_file"}:
            state.focus_paths = [result.get("path", args.get("path"))]
        if name in {"write_file", "replace_text"} and result.get("changed"):
            state.writes += 1
            state.revision += 1
            state.verification.clear()
            state.phase = "verify"
        if name == "run_command" and args.get("cwd", ".") == ".":
            argv = args.get("argv")
            if argv in self.spec.verify_commands:
                key = " ".join(argv)
                if result.get("timed_out") or result.get("interrupted"):
                    state.verification.pop(key, None)
                    return
                record = {"rc": result["rc"], "fingerprint": fingerprint,
                          "revision": state.revision}
                if not state.writes:
                    state.baseline[key] = record
                state.verification[key] = record
                state.phase = "repair" if state.writes and result["rc"] else ("verify" if state.writes else "explore")

    def stop(self, status):
        self.state.status = status
