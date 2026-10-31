#!/bin/bash
# Discord bot session for Fabric. dontAsk: anything not allowed by settings.json is denied, so no prompt ever reaches Discord.
BOT_DIRECTORY=$(cd "$(dirname "$0")" && pwd -P) || exit 1
python3 -I "$BOT_DIRECTORY/config.py" render || exit 1
STATE_DIRECTORY=$(python3 -I "$BOT_DIRECTORY/config.py" get DISCORD_STATE_DIR) || exit 1

# The hook's onFailure (settings.json) needs 2.1.295; older versions would let a failed hook's calls through.
version=$("$BOT_DIRECTORY/bot-env.sh" claude --version </dev/null | awk '{ print $1 }')
if ! python3 -I -c 'import sys; sys.exit(tuple(map(int, sys.argv[1].split("."))) < (2, 1, 295))' "$version" 2>/dev/null; then
  echo "run.sh: Claude Code ${version:-(not found)} is older than 2.1.295, which the guard hook's onFailure needs" >&2
  exit 1
fi

# One gateway client per bot token: every Discord plugin server logs in and receives every message.
plugin_servers=$(ps -axo pid=,ppid=,command= | awk '/bun run --cwd .*\/discord\/[^ ]+ .*start$/ { print $1, $2 }')
if [[ -n "$plugin_servers" ]]; then
  echo "run.sh: Discord plugin servers are already connected; quit their sessions first:" >&2
  while read -r server session; do
    echo "  server $server, session $session: $(ps -o command= -p "$session" | cut -c1-120)" >&2
  done <<< "$plugin_servers"
  exit 1
fi

# Held by the session (inherited fd 9) until it and every child holding the fd exit; the kernel drops it on a crash.
exec 9>"$STATE_DIRECTORY/bot.lock" || exit 1
if ! lockf -s -t 0 9; then
  echo "run.sh: another bot launch holds $STATE_DIRECTORY/bot.lock" >&2
  exit 1
fi

# The Editor UI tools come from the guest's spacesd (cua-driver); render writes its URL and token into rendered/mcp.json.
if ! python3 -I - "$BOT_DIRECTORY/rendered/mcp.json" <<'EOF'
import json, sys, urllib.request
try:
    with open(sys.argv[1]) as file:
        server = json.load(file)["mcpServers"]["vm-driver"]
except (OSError, ValueError, KeyError) as error:
    sys.exit(f"run.sh: no vm-driver MCP config ({error}); is the spacesd token readable?")
body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "discord-bot-run", "version": "1"}}}
request = urllib.request.Request(server["url"], json.dumps(body).encode(), method="POST", headers={
    **server["headers"], "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        if not response.headers.get("mcp-session-id"):
            sys.exit(f"run.sh: {server['url']} answered initialize without an mcp-session-id")
except Exception as error:
    sys.exit(f"run.sh: the spacesd MCP server at {server['url']} did not answer initialize: {error}")
EOF
then
  exit 1
fi

# Inference observability: the session and its tools go through the proxy if it is healthy at launch, else direct.
# The observer answers http://llm-proxy.invalid/ itself once its startup has finished.
unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy NO_PROXY no_proxy NODE_EXTRA_CA_CERTS SSL_CERT_FILE
proxy=$(python3 -I "$BOT_DIRECTORY/config.py" get LLM_PROXY) || exit 1
if [[ -n "$proxy" ]]; then
  proxy_ca=$(python3 -I "$BOT_DIRECTORY/config.py" get LLM_PROXY_CA) || exit 1
  if ! curl --proxy "$proxy" --noproxy '' --connect-timeout 2 --max-time 5 --silent --fail --output /dev/null http://llm-proxy.invalid/; then
    echo "run.sh: proxy $proxy is not healthy; running direct" >&2
  elif [[ ! -r "$proxy_ca" ]]; then
    echo "run.sh: proxy CA $proxy_ca is missing; running direct" >&2
  else
    # Node (claude, the Discord plugin) reads the CA from NODE_EXTRA_CA_CERTS; OpenSSL tools from SSL_CERT_FILE; Apple's stack from the System keychain.
    export HTTPS_PROXY=$proxy HTTP_PROXY=$proxy https_proxy=$proxy http_proxy=$proxy \
      NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 NODE_EXTRA_CA_CERTS=$proxy_ca SSL_CERT_FILE=$proxy_ca
    echo "run.sh: using proxy $proxy" >&2
  fi
fi

# warm-watch.py (guest LaunchAgent local.discord-bot-warm) refreshes the warm main tree on this request.
warm=$(python3 -I "$BOT_DIRECTORY/config.py" get TASK_ROOT)/warm-main.noindex || exit 1
mkdir -p "$warm" && touch "$warm/refresh-requested"

cd "$(python3 -I "$BOT_DIRECTORY/config.py" get CHECKOUT)" || exit 1
# The hook (rendered/guard-client) asks this server, which keeps guard.py loaded, and runs guard.py itself when the server is down.
# The server's parent is this process, which becomes the session; it exits when the session does.
"$BOT_DIRECTORY/bot-env.sh" python3 -I "$BOT_DIRECTORY/guard.py" --serve "$(python3 -I "$BOT_DIRECTORY/config.py" get GUARD_SOCKET)" \
  </dev/null >>"$BOT_DIRECTORY/rendered/guard-server.log" 2>&1 9>&- &
exec "$BOT_DIRECTORY/bot-env.sh" claude --settings "$BOT_DIRECTORY/rendered/settings.json" --permission-mode dontAsk \
  --append-system-prompt-file "$BOT_DIRECTORY/rendered/BOT.md" \
  --mcp-config "$BOT_DIRECTORY/rendered/mcp.json" \
  --name discord-bot \
  --channels plugin:discord@claude-plugins-official "$@"
