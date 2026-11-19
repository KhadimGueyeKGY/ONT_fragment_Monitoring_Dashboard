#!/usr/bin/env bash
# Prepares conda and the environment, then starts the dashboard. Used by the Start_Dashboard launchers.
set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$APP_DIR")"
ENV_NAME="ont_fragment_dashboard"
ENV_FILE="$ROOT/environment.yml"
INSTALL_DIR="$HOME/miniforge3"

say()  { printf '\n  %s\n' "$*" >&2; }
fail() { printf '\n  ERROR: %s\n\n' "$*" >&2; exit 1; }

cat <<'EOF'

  ONT Fragment Monitoring Dashboard
  ---------------------------------
  This window runs the dashboard. Keep it open while you use it.
EOF

find_conda() {
  local c
  for c in "${CONDA_EXE:-}" "$(command -v conda 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  for d in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/mambaforge" "$HOME/anaconda3" "$HOME/micromamba" \
           "/opt/miniforge3" "/opt/miniconda3" "/opt/conda" "/opt/anaconda3" \
           "/opt/homebrew/Caskroom/miniforge/base" "/usr/local/Caskroom/miniforge/base" \
           "/opt/homebrew/anaconda3" "/usr/local/anaconda3"; do
    [ -x "$d/bin/conda" ] && { echo "$d/bin/conda"; return 0; }
  done
  return 1
}

download() {
  if command -v curl >/dev/null 2>&1; then curl -fL --progress-bar -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -q --show-progress -O "$2" "$1"
  else fail "Neither curl nor wget is installed. Install one of them and start again."
  fi
}

install_conda() {
  local os arch url inst
  os="$(uname)"; arch="$(uname -m)"
  case "$os" in Linux|Darwin) ;; *) fail "Unsupported system: $os" ;; esac
  url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-${os}-${arch}.sh"
  inst="$(mktemp -d)/miniforge.sh"
  say "conda was not found. Downloading Miniforge (conda for ${os} ${arch})..."
  download "$url" "$inst" || fail "Download failed. Check the internet connection."
  say "Installing conda in $INSTALL_DIR ..."
  bash "$inst" -b -p "$INSTALL_DIR" >/dev/null || fail "conda installation failed."
  rm -f "$inst"
  echo "$INSTALL_DIR/bin/conda"
}

env_hash() { cksum < "$ENV_FILE" | awk '{print $1}'; }

env_ok() {
  [ -x "$1/bin/python" ] && [ -x "$1/bin/minimap2" ] && [ -x "$1/bin/samtools" ] &&
  "$1/bin/python" -c "import pysam, numpy, plotly" >/dev/null 2>&1
}

say "[1/4] Checking conda"
CONDA="$(find_conda)" || CONDA="$(install_conda | tail -n 1)"
[ -x "$CONDA" ] || fail "conda could not be found or installed."
BASE="$(cd "$(dirname "$CONDA")/.." && pwd)"
SOLVER="$CONDA"
[ -x "$BASE/bin/mamba" ] && SOLVER="$BASE/bin/mamba"
say "      conda: $BASE"

say "[2/4] Checking the environment '$ENV_NAME'"
ENV_PREFIX="$BASE/envs/$ENV_NAME"
MARK="$ENV_PREFIX/.dashboard_env_hash"
SETUP_LOG="$HOME/.ont_fragment_dashboard/setup.log"
mkdir -p "$(dirname "$SETUP_LOG")"
run_logged() {
  "$@" >>"$SETUP_LOG" 2>&1 &
  local pid=$! n=0
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r        working %ss ' "$n" >&2
    sleep 1; n=$((n + 1))
  done
  printf '\r                         \r' >&2
  wait "$pid"
}
solve() {
  local action="$1"
  : > "$SETUP_LOG"
  run_logged "$SOLVER" env "$action" -y -n "$ENV_NAME" -f "$ENV_FILE" && return 0
  [ "$action" = "create" ] && run_logged "$CONDA" env remove -y -n "$ENV_NAME"
  run_logged "$SOLVER" env "$action" -n "$ENV_NAME" -f "$ENV_FILE" && return 0
  if [ "$(uname)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
    say "      Retrying with Intel packages (Rosetta)."
    [ "$action" = "create" ] && run_logged "$CONDA" env remove -y -n "$ENV_NAME"
    CONDA_SUBDIR=osx-64 run_logged "$SOLVER" env "$action" -n "$ENV_NAME" -f "$ENV_FILE" && return 0
  fi
  tail -n 25 "$SETUP_LOG" >&2
  say "      Full details: $SETUP_LOG"
  return 1
}
if [ ! -d "$ENV_PREFIX" ]; then
  say "      Creating it. This is done once and takes a few minutes."
  solve create || fail "The environment could not be created. See the messages above."
  env_hash > "$MARK"
elif ! env_ok "$ENV_PREFIX" || [ "$(cat "$MARK" 2>/dev/null)" != "$(env_hash)" ]; then
  say "      Updating it to match environment.yml."
  solve update || fail "The environment could not be updated. See the messages above."
  env_hash > "$MARK"
fi
env_ok "$ENV_PREFIX" || fail "The environment is incomplete (python, pysam, minimap2 or samtools missing)."
say "      ready"

say "[3/4] Reference and index are checked by the dashboard itself"
say "[4/4] Starting the dashboard in your browser"
export PATH="$ENV_PREFIX/bin:$PATH"
while true; do
  "$ENV_PREFIX/bin/python" "$APP_DIR/server.py" "$@"
  code=$?
  [ "$code" -eq 75 ] || break
  say "Restarting after the update..."
  if ! env_ok "$ENV_PREFIX" || [ "$(cat "$MARK" 2>/dev/null)" != "$(env_hash)" ]; then
    solve update && env_hash > "$MARK"
  fi
done
say "The dashboard is closed. You can close this window."
exit "$code"
