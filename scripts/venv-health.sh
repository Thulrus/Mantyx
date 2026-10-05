#!/usr/bin/env bash
# Shared virtualenv health check, sourced by setup-dev.sh and check-env.sh.
#
# A venv can exist on disk and still be unusable. The common ways it breaks:
#   - bin/python is a symlink to a system Python that was removed or upgraded
#     (e.g. python3.12 -> 3.14), so the installed packages live under a
#     lib/pythonX.Y the interpreter no longer looks in;
#   - the venv directory was moved or the project renamed, so console scripts
#     (bin/pip, bin/pytest, ...) have shebangs pointing at the old location.
# Neither is repairable in place in a useful way; the fix is to recreate it.

# venv_problems VENV_DIR
# Prints one human-readable problem per line. No output means the venv is healthy.
venv_problems() {
    local venv="$1"
    local python="$venv/bin/python"

    if [ ! -d "$venv" ]; then
        echo "virtual environment does not exist"
        return
    fi

    if [ ! -e "$python" ]; then
        if [ -L "$python" ]; then
            echo "bin/python points at a Python that no longer exists ($(readlink -f "$python" 2>/dev/null || readlink "$python"))"
        else
            echo "bin/python is missing"
        fi
        return
    fi

    local version
    if ! version=$("$python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null); then
        echo "bin/python fails to run"
        return
    fi

    if [ ! -d "$venv/lib/python$version/site-packages" ]; then
        local built_for
        built_for=$(find "$venv/lib" -maxdepth 1 -name 'python3.*' -printf '%f ' 2>/dev/null | sed 's/ $//')
        echo "bin/python is now Python $version but the venv was built for ${built_for:-another version}"
        return
    fi

    # Console scripts hardcode the venv's absolute path in their shebang.
    local script interpreter
    for script in "$venv/bin/pip" "$venv/bin/pytest" "$venv/bin/pre-commit"; do
        [ -f "$script" ] || continue
        interpreter=$(head -n 1 "$script" | sed -n 's/^#!\([^ ]*\).*/\1/p')
        if [ -n "$interpreter" ] && [ ! -x "$interpreter" ]; then
            echo "venv was moved: $(basename "$script") still points at $interpreter"
            return
        fi
    done

    if ! "$python" -m pip --version >/dev/null 2>&1; then
        echo "pip is not usable inside the venv"
    fi
}

# precommit_hook_problems VENV_DIR
# Checks that the git pre-commit hook exists and runs through this venv.
precommit_hook_problems() {
    local venv="$1"
    local hook
    hook="$(git rev-parse --git-path hooks/pre-commit 2>/dev/null)"

    if [ -z "$hook" ] || [ ! -f "$hook" ] || ! grep -q "pre-commit" "$hook" 2>/dev/null; then
        echo "git pre-commit hook is not installed"
        return
    fi

    local install_python
    install_python=$(sed -n 's/^INSTALL_PYTHON=//p' "$hook")
    if [ -n "$install_python" ] && [ ! -x "$install_python" ]; then
        echo "git pre-commit hook points at a missing interpreter ($install_python)"
    elif [ -n "$install_python" ] && [ "$(readlink -f "$(dirname "$install_python")/..")" != "$(readlink -f "$venv")" ]; then
        echo "git pre-commit hook uses a different venv ($install_python)"
    fi
}
