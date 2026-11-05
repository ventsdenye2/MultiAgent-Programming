"""Course adapters and EA-CM; the agent kernel is unmodified upstream code."""
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "smolagents"
sys.path.insert(0, str(VENDOR / "src"))

import smolagents

if not Path(smolagents.__file__).resolve().is_relative_to(VENDOR):
    raise RuntimeError("The vendored smolagents package must be used")
if smolagents.__version__ != "1.26.0":
    raise RuntimeError("Unexpected smolagents version")

__all__ = ["VENDOR"]
