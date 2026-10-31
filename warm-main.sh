#!/bin/bash
# Keeps a Fabric worktree on origin/main built (SwiftPM release with tests, the Editor) for tasks to borrow.
# Run by warm-watch.py (LaunchAgent local.discord-bot-warm), outside the bot session and its guard, when no other build runs.
# READY holds the built commit; it is absent while a refresh runs or after one failed.
# Builds run with cwd under the task root, so the guard counts their jobs against the bot's cap.
set -u
BOT_DIRECTORY=$(cd "$(dirname "$0")" && pwd) || exit 1
config() { python3 -I "$BOT_DIRECTORY/config.py" get "$1"; }
CHECKOUT=${WARM_MAIN_CHECKOUT:-$(config CHECKOUT)} || exit 1
TASK_ROOT=${WARM_MAIN_TASK_ROOT:-$(config TASK_ROOT)} || exit 1
JOBS=${WARM_MAIN_JOBS:-4}
WARM=$TASK_ROOT/warm-main.noindex
TREE=$WARM/Fabric
LEASE=$WARM/lease
READY=$WARM/READY
LEASE_STALE_MINUTES=720

log() { echo "$(date '+%F %T') $*"; }

mkdir -p "$WARM" || exit 1
if ! mkdir "$LEASE" 2>/dev/null; then
  owner=$(cat "$LEASE/refresher.pid" 2>/dev/null)
  if [[ -n "$owner" ]] && ! kill -0 "$owner" 2>/dev/null; then
    log "removing lease of dead refresher $owner"
  elif [[ -z "$owner" && -n $(find "$LEASE" -maxdepth 0 -mmin +$LEASE_STALE_MINUTES) ]]; then
    log "removing lease idle over $LEASE_STALE_MINUTES min: $(cat "$LEASE/task.txt" 2>/dev/null)"
  else
    exit 0
  fi
  rm -rf "$LEASE" && mkdir "$LEASE" || exit 1
fi
echo $$ > "$LEASE/refresher.pid"
echo "warm-main.sh refresh" > "$LEASE/task.txt"
trap 'rm -rf "$LEASE"' EXIT

git -C "$CHECKOUT" fetch -q origin main || { log "fetch failed"; exit 1; }
target=$(git -C "$CHECKOUT" rev-parse origin/main) || exit 1
if [[ -d "$TREE" && "$(cat "$READY" 2>/dev/null)" == "$target" && "$(git -C "$TREE" rev-parse HEAD 2>/dev/null)" == "$target" ]]; then
  exit 0
fi

log "refreshing to $target"
rm -f "$READY"
if [[ ! -d "$TREE" ]]; then
  # /private/tmp is emptied at boot, which leaves the worktree registered but missing.
  git -C "$CHECKOUT" worktree prune
  git -C "$CHECKOUT" worktree add -q --detach "$TREE" "$target" || { log "worktree add failed"; exit 1; }
else
  git -C "$TREE" checkout -q --detach -f "$target" || { log "checkout failed"; exit 1; }
  git -C "$TREE" clean -fdq -e .build.noindex || exit 1
fi
cd "$TREE" || exit 1
git submodule -q update --init || { log "submodule update failed"; exit 1; }
ditto "$CHECKOUT/Frameworks" Frameworks || exit 1

nice -n 10 swift build -c release -j "$JOBS" -Xswiftc -enable-testing --build-tests --scratch-path .build.noindex \
  > "$WARM/swift-build.log" 2>&1 || { log "swift build failed, see $WARM/swift-build.log"; exit 1; }
ln -sfn "$TREE/HapInAVFoundation/external/Sparkle.framework" .build.noindex/out/Products/Release/Sparkle.framework
nice -n 10 xcodebuild -project Fabric.xcodeproj -scheme "Fabric Editor" -configuration Release -destination 'platform=macOS,arch=arm64' \
  -skipMacroValidation -derivedDataPath "$WARM/editor-dd.noindex" -jobs "$JOBS" \
  CODE_SIGN_IDENTITY="-" CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM="" PROVISIONING_PROFILE_SPECIFIER="" build \
  > "$WARM/editor-build.log" 2>&1 || { log "Editor build failed, see $WARM/editor-build.log"; exit 1; }

echo "$target" > "$READY"
log "ready at $target"
