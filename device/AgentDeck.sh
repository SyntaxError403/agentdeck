#!/bin/sh
# AgentDeck launcher. Place this file and the agentdeck/ folder in your
# firmware's Ports folder (for example roms/ports on Knulli or ROCKNIX).
DIR="$(cd "$(dirname "$0")" && pwd)/agentdeck"
LOG="$DIR/log.txt"
cd "$DIR" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on this firmware" > "$LOG"
  exit 1
fi
if ! python3 -c "import pygame" >/dev/null 2>&1; then
  echo "pygame not found. See README: Device setup" > "$LOG"
  exit 1
fi

export SDL_NOMOUSE=1
python3 main.py "$@" > "$LOG" 2>&1
