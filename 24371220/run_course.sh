#!/usr/bin/env bash
set -euo pipefail
submission="$(cd "$(dirname "$0")" && pwd)"
exec "$submission/.venv/bin/python" "$submission/evaluate_course.py" "$@"
