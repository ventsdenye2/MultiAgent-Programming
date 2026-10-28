"""Public task constraints, separate from the agent loop and business answers."""
from dataclasses import dataclass, field
from pathlib import Path
import re


TEST_COMMAND = ["python", "-m", "pytest", "-q"]
TOPICS = ("overview", "reasoning", "tool_use", "multi_agent", "outlook")


@dataclass
class TaskSpec:
    text: str
    repo: Path
    profile: str
    editable: set[str]
    max_calls: int = 60
    hard_chars: int = 32000
    soft_chars: int = 30000
    timeout: float = 1800
    required_reads: set[str] = field(default_factory=set)
    verify_commands: list = field(default_factory=lambda: [TEST_COMMAND.copy()])
    paper_pages: tuple = ()
    topics: tuple = ()
    require_write: bool = True
    strict_plan_titles: bool = True
    efficiency: bool = False

    def instructions(self):
        return {"profile": self.profile, "editable": sorted(self.editable),
                "required_full_reads_before_write": sorted(self.required_reads),
                "verify_commands": self.verify_commands, "paper_pages": list(self.paper_pages),
                "note_topics": list(self.topics), "max_model_calls": self.max_calls,
                "max_request_chars": self.hard_chars, "require_write": self.require_write}


def load_task(text, repo, config, profile="auto", allow=None):
    repo = Path(repo).resolve(strict=True)
    if profile == "auto":
        if (repo / "read_pdf.py").is_file() and (repo / "paper.json").is_file() and "report.json" in text:
            profile = "paper"
        elif (repo / "deepinfer").is_dir() and "deepinfer/" in text:
            profile = "source"
        elif allow or config.get("editable"):
            profile = "generic"
        else:
            profile = "basic"
    editable = set(allow or config.get("editable", []))
    public_paths = set()
    if not editable:
        for line in text.splitlines():
            if "只修改" in line or "只允许修改" in line:
                public_paths.update(re.findall(r"`([^`\n]+\.(?:py|json|txt|md|js|ts|tsx|jsx|yaml|yml|toml|css|html))`", line))
        if profile == "paper":
            public_paths = {"report.json"}
        elif profile == "source":
            # Paths are public task constraints; never preconfigure source symbols or answers.
            public_paths = set(re.findall(r"`(deepinfer/[\w/]+\.py)`", text))
        editable = public_paths
    if not editable and not config.get("read_only", False):
        raise ValueError("无法确定允许修改的文件；请通过 --allow 或 editable 配置明确范围")
    for name in editable:
        target = (repo / name).resolve()
        if not target.is_relative_to(repo) or target == repo or Path(name).is_absolute():
            raise ValueError("Editable path must be repository-relative")
    spec = TaskSpec(text, repo, profile, editable,
                    max_calls=int(config.get("max_steps", 60)),
                    timeout=float(config.get("run_timeout", 1800)),
                    require_write=not config.get("read_only", False))
    if profile in {"paper", "source"}:
        spec.max_calls = min(spec.max_calls, 40 if profile == "paper" else 20)
        spec.required_reads = set(editable)
    elif profile == "basic":
        spec.required_reads = set(sorted(editable)[:min(2, len(editable))])
        if (repo / "run_checks.py").is_file():
            spec.verify_commands.append(["python", "run_checks.py"])
    else:
        spec.required_reads = {p for p in editable if (repo / p).is_file()}
        spec.strict_plan_titles = False
        spec.verify_commands = config.get("verify_commands", [] if not spec.require_write else [TEST_COMMAND.copy()])
    if profile == "paper":
        spec.paper_pages, spec.topics = tuple(range(1, 53)), TOPICS
    spec.efficiency = bool(config.get("efficiency", False))
    if spec.efficiency and profile != "source":
        raise ValueError("efficiency mode requires the source profile")
    spec.hard_chars = min(32000, int(config.get("request_chars", 32000)))
    spec.soft_chars = min(spec.hard_chars, int(config.get("context_chars_v2", 30000)))
    if spec.max_calls < 1 or spec.timeout <= 0 or spec.soft_chars < 1000:
        raise ValueError("Invalid request, time, or context budget")
    return spec
