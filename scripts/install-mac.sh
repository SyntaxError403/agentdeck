#!/usr/bin/env bash
# Installs the AgentDeck agent as a login item (launchd) on macOS.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found. Install Xcode command line tools: xcode-select --install"; exit 1; }
command -v tmux >/dev/null || { echo "tmux not found. Install it with: brew install tmux"; exit 1; }

PLIST="$HOME/Library/LaunchAgents/com.agentdeck.agent.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.agentdeck"
sed -e "s|__PYTHON__|$PY|g" \
    -e "s|__AGENT__|$REPO/agent/agentdeck_agent.py|g" \
    -e "s|__HOME__|$HOME|g" \
    "$REPO/agent/com.agentdeck.agent.plist.template" > "$PLIST"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
chmod +x "$REPO/scripts/agentdeck-new"

echo "Agent installed and running. Logs: ~/.agentdeck/agent.log"
echo
"$PY" "$REPO/agent/agentdeck_agent.py" --show-config
