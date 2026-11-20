#!/usr/bin/env bash
# Malaria dashboard monitor (ONT fragment monitoring). Author: Khadim Gueye
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

# macOS and Linux: an application with the logo, in the applications menu and on the Desktop.
install_app_launcher() {
  local name="Malaria dashboard monitor" icon="$ROOT/img/icon_256.png" desk="$HOME/Desktop"
  if [ "$(uname)" = "Darwin" ]; then
    local app="$HOME/Applications/$name.app"
    [ -f "$app/Contents/MacOS/launcher" ] && grep -qF "$ROOT" "$app/Contents/MacOS/launcher" && return 0
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cat > "$app/Contents/MacOS/launcher" <<EOF2
#!/bin/bash
# Author: Khadim Gueye
open -a Terminal "$ROOT/Start_Dashboard_macOS.command"
EOF2
    chmod +x "$app/Contents/MacOS/launcher" "$ROOT/Start_Dashboard_macOS.command"
    cat > "$app/Contents/Info.plist" <<EOF2
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$name</string>
  <key>CFBundleDisplayName</key><string>$name</string>
  <key>CFBundleIdentifier</key><string>org.igh.malaria-dashboard-monitor</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$(cat "$ROOT/VERSION")</string>
</dict></plist>
EOF2
    local set; set="$(mktemp -d)/icon.iconset"; mkdir -p "$set"
    for s in 16 32 64 128 256 512; do
      sips -z $s $s "$icon" --out "$set/icon_${s}x${s}.png" >/dev/null 2>&1
      sips -z $((s * 2)) $((s * 2)) "$icon" --out "$set/icon_${s}x${s}@2x.png" >/dev/null 2>&1
    done
    iconutil -c icns "$set" -o "$app/Contents/Resources/icon.icns" >/dev/null 2>&1
    [ -d "$desk" ] && ln -sfn "$app" "$desk/$name.app"
    say "      Application added: ~/Applications/$name and on the Desktop"
  elif [ "$(uname)" = "Linux" ] && ! grep -qi microsoft /proc/version 2>/dev/null; then
    local dir="$HOME/.local/share/applications" file="malaria-dashboard-monitor.desktop"
    [ -f "$dir/$file" ] && grep -qF "$ROOT" "$dir/$file" && return 0
    mkdir -p "$dir"
    cat > "$dir/$file" <<EOF2
[Desktop Entry]
Type=Application
Name=$name
Comment=ONT fragment monitoring dashboard, Malaria team IGH (author: Khadim Gueye)
Exec=bash "$ROOT/app/bootstrap.sh"
Path=$ROOT
Icon=$icon
Terminal=true
Categories=Science;Biology;
EOF2
    chmod +x "$dir/$file"
    if [ -d "$desk" ]; then
      cp "$dir/$file" "$desk/$file" && chmod +x "$desk/$file"
      command -v gio >/dev/null 2>&1 && gio set "$desk/$file" metadata::trusted true 2>/dev/null
    fi
    say "      Application added to the applications menu and on the Desktop"
  fi
  return 0
}
install_app_launcher || true

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
# 3: the dashboard was already running and its window has been opened again.
if [ "$code" -eq 3 ]; then
  say "The dashboard was already running. Its window is open."
  exit 0
fi
say "The dashboard is closed."
exit "$code"
