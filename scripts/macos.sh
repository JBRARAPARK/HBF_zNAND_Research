#!/bin/bash
# Compatible with macOS /bin/bash 3.2. All model commands use the project venv.
set -euo pipefail

znand_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
znand_venv="${ZNAND_VENV:-$znand_root/.venv}"
case "$znand_venv" in /*) ;; *) znand_venv="$znand_root/$znand_venv" ;; esac
znand_python="$znand_venv/bin/python3"
znand_results_root="${ZNAND_RESULTS_DIR:-$znand_root/results/local}"
case "$znand_results_root" in /*) ;; *) znand_results_root="$znand_root/$znand_results_root" ;; esac
znand_action="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
cd "$znand_root"

usage() {
    cat <<'EOF'
Usage: bash scripts/macos.sh COMMAND [OPTIONS]
  setup [--plots]   Create .venv using Python 3.10+; optionally install matplotlib
  check            Run the 35 model tests
  smoke            Run tests plus two explicit-spawn 32/64-plane checks
  diagnostics      Reproduce the six A2 diagnostic cases (accepts CLI options)
  replay [PATTERN] Replay a saved best config; default A2, 8192 requests/port
  report           Regenerate plots and Markdown from the saved evaluation CSVs
  sweep            Run the base/sensitivity sweep, including the saved MQSim layout
  extended         Run upper-QD comparisons (accepts --workers and --per-port)
  layout           Open the 8/16-plane address diagram on macOS

New output: results/local/<date>-<command>-<pid>/
Overrides: ZNAND_PYTHON (setup), ZNAND_VENV, ZNAND_RESULTS_DIR
Example: bash scripts/macos.sh diagnostics --cases 64plane_8MiB 64plane_32MiB
EOF
}

fail() { printf '%s\n' "$*" >&2; exit 1; }

supported_python() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

require_python() {
    [[ -x "$znand_python" ]] || fail 'Run first: bash scripts/macos.sh setup'
    supported_python "$znand_python" || fail 'The venv needs Python 3.10+. Choose a different ZNAND_VENV and run setup.'
}

new_output() {
    znand_out="$znand_results_root/$(date '+%Y%m%d-%H%M%S')-$znand_action-$$"
    mkdir -p "$znand_results_root"
    mkdir "$znand_out"
    "$znand_python" - "$znand_root" "$znand_out" "$znand_action" <<'PY'
import datetime, hashlib, json, platform, subprocess, sys
from pathlib import Path
root, out = (Path(value) for value in sys.argv[1:3])
def git_value(*args):
    try:
        result = subprocess.run(['git', *args], cwd=root, text=True, capture_output=True)
        return result.stdout.strip() if result.returncode == 0 else None
    except FileNotFoundError:
        return None
status = git_value('status', '--porcelain', '--untracked-files=no')
record = dict(command=sys.argv[3], timestamp=datetime.datetime.now().astimezone().isoformat(),
              python=platform.python_version(), platform=platform.system(), machine=platform.machine(),
              git_commit=git_value('rev-parse', 'HEAD'), tracked_changes=bool(status) if status is not None else None,
              model_sha256=hashlib.sha256((root/'znand/model.py').read_bytes()).hexdigest())
(out/'execution.json').write_text(json.dumps(record, indent=2))
PY
    printf 'Output: %s\n' "$znand_out"
}

# Keep managed outputs consistent with the path printed above.
reject_output_override() {
    for znand_arg in "$@"; do
        case "$znand_arg" in --out|--out=*) fail 'Use ZNAND_RESULTS_DIR to choose the output base directory.' ;; esac
    done
}

case "$znand_action" in
    help|-h|--help) usage; exit 0 ;;
    setup)
        znand_plots=0
        for znand_arg in "$@"; do
            case "$znand_arg" in --plots) znand_plots=1 ;; *) fail "Unknown setup option: $znand_arg" ;; esac
        done
        if [[ ! -x "$znand_python" ]]; then
            [[ ! -e "$znand_venv" ]] || fail 'The venv path already exists without bin/python3. Choose a different ZNAND_VENV.'
            znand_selected=''
            if [[ -n "${ZNAND_PYTHON:-}" ]]; then
                command -v "$ZNAND_PYTHON" >/dev/null 2>&1 || fail "Python not found: $ZNAND_PYTHON"
                supported_python "$ZNAND_PYTHON" || fail 'ZNAND_PYTHON must be Python 3.10+.'
                znand_selected="$ZNAND_PYTHON"
            else
                for znand_candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
                    if command -v "$znand_candidate" >/dev/null 2>&1 && supported_python "$znand_candidate"; then
                        znand_selected="$znand_candidate"
                        break
                    fi
                done
                [[ -n "$znand_selected" ]] || fail 'Install Python 3.10+ from python.org, then set ZNAND_PYTHON if needed. See docs/11_macos_run_ko.md.'
            fi
            "$znand_selected" -m venv "$znand_venv"
        fi
        require_python
        if [[ "$znand_plots" -eq 1 ]]; then
            "$znand_python" -m pip install -r "$znand_root/requirements-znand-plot.txt"
        fi
        "$znand_python" -c 'import platform; print("Ready: Python " + platform.python_version() + " / " + platform.system() + " / " + platform.machine())'
        printf '%s\n' 'Next: bash scripts/macos.sh smoke' 'Then: bash scripts/macos.sh diagnostics'
        ;;
    layout)
        [[ $# -eq 0 ]] || fail 'layout takes no options.'
        if [[ "$(uname -s)" == Darwin ]]; then
            open "$znand_root/docs/plane_layout/index.html"
        else
            printf 'Diagram: %s\n' "$znand_root/docs/plane_layout/index.html"
        fi
        ;;
    check)
        [[ $# -eq 0 ]] || fail 'check takes no options.'
        require_python
        "$znand_python" -m unittest test_znand test_znand_expansion -q
        ;;
    smoke)
        [[ $# -eq 0 ]] || fail 'smoke takes no options.'
        require_python
        "$znand_python" -m unittest test_znand test_znand_expansion -q
        new_output
        "$znand_python" -m znand.portability --out "$znand_out"
        ;;
    diagnostics)
        require_python
        reject_output_override "$@"
        new_output
        "$znand_python" -m znand.diagnostics --out "$znand_out" "$@"
        ;;
    replay)
        require_python
        [[ $# -le 1 ]] || fail 'replay accepts one pattern: A1, A2, B1, B2 or B3.'
        znand_pattern="${1:-A2}"
        case "$znand_pattern" in A1|A2|B1|B2|B3) ;; *) fail "Unknown pattern: $znand_pattern" ;; esac
        new_output
        "$znand_python" -m znand.run --config "$znand_root/znand/observed_best/$znand_pattern.json" --pattern "$znand_pattern" --per-port 8192 --out "$znand_out"
        ;;
    report)
        [[ $# -eq 0 ]] || fail 'report takes no options.'
        require_python
        "$znand_python" -c 'import matplotlib' >/dev/null 2>&1 || fail 'Install plot dependencies first: bash scripts/macos.sh setup --plots'
        new_output
        export MPLCONFIGDIR="${MPLCONFIGDIR:-$znand_results_root/.matplotlib-cache}"
        "$znand_python" -m znand.report --input "$znand_root/results/znand/full/sweep.csv" --extended "$znand_root/results/znand/extended/saturation.csv" --out "$znand_out"
        ;;
    sweep)
        require_python
        reject_output_override "$@"
        new_output
        "$znand_python" -m znand.sweep --workers 2 --snapshot "$znand_root/znand/mqsim/snapshot.json" --out "$znand_out" "$@"
        ;;
    extended)
        require_python
        reject_output_override "$@"
        new_output
        "$znand_python" -m znand.extend --workers 2 --out "$znand_out" "$@"
        ;;
    *) usage >&2; fail "Unknown command: $znand_action" ;;
esac
