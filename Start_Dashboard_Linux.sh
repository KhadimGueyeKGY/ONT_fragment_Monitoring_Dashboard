#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -t 1 ]; then
  for term in x-terminal-emulator gnome-terminal konsole xfce4-terminal xterm; do
    if command -v "$term" >/dev/null 2>&1; then
      case "$term" in
        gnome-terminal) exec gnome-terminal -- bash ./app/bootstrap.sh ;;
        *) exec "$term" -e bash ./app/bootstrap.sh ;;
      esac
    fi
  done
fi
bash ./app/bootstrap.sh
