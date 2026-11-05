"""Append-only audit log, deliberately compatible with course evaluators."""
import json
import os
from pathlib import Path
import time
import uuid


class RunLog:
    def __init__(self, output, key_env=""):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        for name in ("run.log", "patch.diff", "run-result.json", "evidence.json"):
            if (self.output / name).exists() or (self.output / name).is_symlink():
                raise ValueError(f"Existing {name}; use a fresh output directory")
        self.run_id = uuid.uuid4().hex
        self.secret = os.environ.get(key_env, "") if key_env else ""
        self.file = (self.output / "run.log").open("x", encoding="utf-8")
        self.sequence = 0

    def __call__(self, event, **fields):
        self.sequence += 1
        text = json.dumps({"event": event, "time": time.time(), "run_id": self.run_id,
                           "seq": self.sequence, **fields}, ensure_ascii=False)
        if self.secret:
            text = text.replace(json.dumps(self.secret, ensure_ascii=False)[1:-1], "[REDACTED]")
        self.file.write(text + "\n")
        self.file.flush()

    def close(self):
        self.file.close()
