"""Public task requirements, independent of the upstream decision loop."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

TOPICS = ("overview", "reasoning", "tool_use", "multi_agent", "outlook")
PYTEST = ["python", "-m", "pytest", "-q"]


@dataclass
class TaskContract:
    text: str
    repo: Path
    profile: str
    editable: set[str]
    required_reads: set[str] = field(default_factory=set)
    verify_commands: list = field(default_factory=lambda: [PYTEST.copy()])
    max_calls: int = 60
    hard_chars: int = 32000
    soft_chars: int = 30000
    content_chars: int | None = None
    timeout: float = 1800
    paper_pages: tuple = ()
    topics: tuple = ()
    require_write: bool = True
    strict_plan: bool = True

    def view(self):
        return {"profile": self.profile, "editable": sorted(self.editable),
                "required_full_reads": sorted(self.required_reads),
                "verify_commands": self.verify_commands, "required_pages": self.paper_pages,
                "note_topics": self.topics, "max_model_calls": self.max_calls}


def load_task(text, repo, config, profile="auto", allow=None):
    repo = Path(repo).resolve(strict=True)
    if profile == "auto":
        if (repo / "read_pdf.py").is_file() and (repo / "paper.json").is_file() and "report.json" in text:
            profile = "paper"
        elif (repo / "deepinfer").is_dir() and "deepinfer/" in text:
            profile = "source"
        elif allow or config.get("editable") or config.get("read_only"):
            profile = "generic"
        else:
            profile = "basic"
    if profile not in {"basic", "generic", "source", "paper"}:
        raise ValueError("Unknown task profile")
    editable = set(allow or config.get("editable", []))
    if not editable:
        for line in text.splitlines():
            if "只修改" in line or "只允许修改" in line:
                editable.update(re.findall(r"`([^`\n]+\.(?:py|json|txt|md|js|ts|tsx|jsx|yaml|yml|toml|css|html))`", line))
        if profile == "paper":
            editable = {"report.json"}
        elif profile == "source":
            editable = set(re.findall(r"`(deepinfer/[\w/]+\.py)`", text))
    if not editable and not config.get("read_only", False):
        raise ValueError("无法确定允许修改的文件；请使用 --allow 或 editable 配置")
    for rel in editable:
        target = (repo / rel).resolve()
        if Path(rel).is_absolute() or not target.is_relative_to(repo) or target == repo:
            raise ValueError("Editable paths must remain inside the repository")
    spec = TaskContract(text, repo, profile, editable,
                        max_calls=int(config.get("max_steps", 60)),
                        timeout=float(config.get("run_timeout", 1800)),
                        require_write=not config.get("read_only", False))
    if profile in {"source", "paper"}:
        spec.max_calls = min(spec.max_calls, 40 if profile == "paper" else 20)
        spec.required_reads = set(editable)
    elif profile == "basic":
        spec.required_reads = set(sorted(editable)[:min(2, len(editable))])
        spec.content_chars = min(16000, int(config.get("context_chars", 15000)))
        if (repo / "run_checks.py").is_file():
            spec.verify_commands.append(["python", "run_checks.py"])
    else:
        spec.required_reads = {p for p in editable if (repo / p).is_file()}
        spec.verify_commands = config.get("verify_commands", [PYTEST.copy()] if spec.require_write else [])
        spec.strict_plan = False
    if profile == "paper":
        metadata = json.loads((repo / "paper.json").read_text(encoding="utf-8"))
        bounds = metadata.get("required_pages", [1, 52])
        if not (isinstance(bounds, list) and len(bounds) == 2 and all(type(n) is int for n in bounds)
                and 1 <= bounds[0] <= bounds[1]):
            raise ValueError("paper.json required_pages must contain valid inclusive page bounds")
        spec.paper_pages = tuple(range(bounds[0], bounds[1] + 1))
        spec.topics = TOPICS
    spec.hard_chars = min(32000, int(config.get("request_chars", 32000)))
    spec.soft_chars = min(spec.hard_chars, int(config.get("context_chars_smol", 30000)))
    if spec.max_calls < 1 or spec.timeout <= 0 or spec.soft_chars < 1000:
        raise ValueError("Invalid task budget")
    return spec
