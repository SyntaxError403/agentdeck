#!/bin/sh
# Shows raw button numbers so you can fix config.json -> buttons.
DIR="$(cd "$(dirname "$0")" && pwd)/agentdeck"
cd "$DIR" || exit 1
export SDL_NOMOUSE=1
python3 main.py --input-test > "$DIR/input-test.txt" 2>&1
