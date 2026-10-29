#!/usr/bin/env bash
set -euo pipefail
submission="$(cd "$(dirname "$0")" && pwd)"
exec "$submission/.venv/bin/python" "$submission/evaluate_long_context_v2.py" "$@"
