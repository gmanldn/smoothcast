#!/usr/bin/env bash
# Fresh macOS: use preinstalled compatible Python, or acquire it with verified Homebrew.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BREW_COMMIT="eaa2af62ca1d5349c9743f82b1b0c4e5d365fb2d"
BREW_SHA256="8fd2f1a5287a7c2e3d7362924c677edcc04c5a0e16448c77132d056bc88cf1ed"

valid_python() {
    command -v "$1" >/dev/null 2>&1 &&
        "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
        >/dev/null 2>&1
}
find_python() {
    if [[ -n "${PYTHON:-}" ]]; then
        valid_python "$PYTHON" || return 1
        printf '%s\n' "$PYTHON"
        return
    fi
    local candidate
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3 \
                     python3.15 python3.14 python3.13 python3.12 python3.11 \
                     python3.10 /usr/bin/python3; do
        if valid_python "$candidate"; then
            printf '%s\n' "$candidate"
            return
        fi
    done
    return 1
}
find_brew() {
    local candidate
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew brew; do
        if command -v "$candidate" >/dev/null 2>&1; then
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
            echo "Python 3.10+ is not installed (--check is read-only)." >&2
            exit 1
        fi
    done
    if [[ -n "${PYTHON:-}" ]]; then
        echo "PYTHON does not point to a working Python 3.10+ interpreter." >&2
        exit 1
    fi

    brew="$(find_brew || true)"
    if [[ -z "$brew" ]]; then
        command -v curl >/dev/null || { echo "macOS curl is missing." >&2; exit 1; }
        command -v shasum >/dev/null || { echo "macOS shasum is missing." >&2; exit 1; }
        temp="$(mktemp -d "${TMPDIR:-/tmp}/smoothcast-brew.XXXXXXXX")"
        trap 'rm -rf "$temp"' EXIT
        echo "Downloading the reviewed, pinned Homebrew installer."
        url="https://raw.githubusercontent.com/Homebrew/install/${BREW_COMMIT}/install.sh"
        curl --fail --location --retry 3 --connect-timeout 20 --max-time 120 \
             --output "$temp/install.sh" "$url"
        [[ -s "$temp/install.sh" ]] || { echo "Empty Homebrew installer." >&2; exit 1; }
        [[ "$(wc -c <"$temp/install.sh" | tr -d ' ')" -le 262144 ]] || {
            echo "Homebrew installer exceeded the safe size limit." >&2
            exit 1
        }
        actual="$(shasum -a 256 "$temp/install.sh" | awk '{print $1}')"
        [[ "$actual" == "$BREW_SHA256" ]] || {
            echo "Homebrew installer checksum mismatch. Nothing was executed." >&2
            exit 1
        }
        NONINTERACTIVE=1 /bin/bash "$temp/install.sh"
        brew="$(find_brew || true)"
        if [[ -z "$brew" ]]; then
            echo "Homebrew is still unavailable. Complete any requested macOS Command Line Tools installation and rerun." >&2
            exit 1
        fi
    fi
    echo "Installing Python with Homebrew."
    "$brew" install python
    python="$(find_python || true)"
    if [[ -z "$python" ]]; then
        echo "Homebrew completed but Python 3.10+ is missing." >&2
        exit 1
    fi
fi

exec "$python" "$HERE/bootstrap.py" --target macos "$@"
