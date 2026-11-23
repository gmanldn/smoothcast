#!/usr/bin/env bash
# Fresh Linux host: only Bash and the distribution package manager are assumed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

valid_python() {
    command -v "$1" >/dev/null 2>&1 &&
        "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    if [[ -n "${PYTHON:-}" ]]; then
        valid_python "$PYTHON" || {
            echo "PYTHON=$PYTHON is not a working Python 3.10+ interpreter." >&2
            return 1
        }
        printf '%s\n' "$PYTHON"
        return
    fi
    local candidate
    for candidate in python3 python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 \
                     /usr/bin/python3; do
        if valid_python "$candidate"; then
            printf '%s\n' "$candidate"
            return
        fi
    done
    return 1
}

python="$(find_python || true)"
if [[ -z "$python" ]]; then
    for arg in "$@"; do
        if [[ "$arg" == "--check" ]]; then
            echo "Python 3.10+ is not installed (--check does not modify the machine)." >&2
            exit 1
        fi
    done
    if [[ -n "${PYTHON:-}" ]]; then
        echo "The explicit PYTHON interpreter is unusable; fix PYTHON or unset it." >&2
        exit 1
    fi
    if [[ "$(id -u)" -eq 0 ]]; then
        elevate=()
    elif command -v sudo >/dev/null 2>&1; then
        elevate=(sudo)
    else
        echo "Installing Python requires sudo or running this script as root." >&2
        exit 1
    fi
    if command -v apt-get >/dev/null 2>&1; then
        echo "Installing Python through apt (administrator permission may be requested)."
        "${elevate[@]}" apt-get update
        "${elevate[@]}" apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        echo "Installing Python through dnf."
        "${elevate[@]}" dnf install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        echo "Installing Python through pacman."
        "${elevate[@]}" pacman -Syu --needed --noconfirm python python-pip
    else
        echo "Unsupported Linux package manager. Supported: apt-get, dnf, pacman." >&2
        exit 1
    fi
    hash -r
    python="$(find_python || true)"
    if [[ -z "$python" ]]; then
        echo "Python 3.10+ is still missing. This distro may ship an unsupported Python." >&2
        exit 1
    fi
fi

exec "$python" "$HERE/bootstrap.py" --target linux "$@"
