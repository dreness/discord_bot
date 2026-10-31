#!/bin/bash
# Runs a command with only the variables below; nothing else from the caller's environment reaches the bot.
# Bot-specific values (GH_CONFIG_DIR, git HTTPS rewrite) come from settings.json env, not from here; the proxy variables from run.sh.
INHERITED=(HOME USER LOGNAME SHELL TMPDIR LANG LC_ALL LC_CTYPE TERM COLORTERM TERM_PROGRAM TERM_PROGRAM_VERSION __CF_USER_TEXT_ENCODING
  HTTPS_PROXY HTTP_PROXY https_proxy http_proxy NO_PROXY no_proxy NODE_EXTRA_CA_CERTS SSL_CERT_FILE)
CLAUDE_DIRECTORY=$(dirname "$(command -v claude)") || exit 1
assignments=("PATH=$CLAUDE_DIRECTORY:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
for name in "${INHERITED[@]}"; do
  [[ -n "${!name+set}" ]] && assignments+=("$name=${!name}")
done
exec /usr/bin/env -i "${assignments[@]}" "$@"
