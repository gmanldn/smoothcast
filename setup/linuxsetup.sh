#!/usr/bin/env bash
# SmoothCast Linux installer: Python 3.10+ is the only initial prerequisite.
set -euo pipefail
HERE="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
PYTHON="\${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "SmoothCast setup needs Python 3.10+ installed first." >&2
    exit 1
fi
exec "$PYTHON" "$HERE/bootstrap.py" --target linux "$@"
