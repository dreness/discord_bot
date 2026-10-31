import json, os, subprocess, sys
from support import BOT, CONFIG
guard = os.path.join(BOT, "guard.py")
MAIN = CONFIG["CHECKOUT"]
# The bot's own process, and this test, which is an ancestor of the guard like the session is.
target = subprocess.Popen(["/bin/sleep", "60"])
own, ancestor = target.pid, os.getpid()
cases = [
    (f"kill {own}", None),
    (f"kill -9 {own}", None),
    (f"kill -s TERM {own}", None),
    (f"/bin/kill {own}", None),
    (f"env kill -- {own}", None),
    ("kill -l", None),
    (f"kill {ancestor}", "deny"),
    (f"kill -9 {own} {ancestor}", "deny"),
    ("kill 1", "deny"),
    ("kill 0", "deny"),
    ("kill -9 -1", "deny"),
    ("kill -- -123", "deny"),
    ("kill %1", "deny"),
    ("kill", "deny"),
    ("pgrep -f guard.py | xargs kill", "deny"),
    ("pkill -f guard.py", "deny"),
    ("pkill python3", "deny"),
    ("pkill claude", "deny"),
    ("pkill -x tmux", "deny"),
    ("pkill spacesd", "deny"),
    ("pkill -f 'Fabric Editor|guard'", "deny"),
    ("pkill -f '.*'", "deny"),
    ("pkill -f '['", "deny"),
    ("pkill -u someone -f 'Fabric Editor'", "deny"),
    ("pkill -f 'Fabric Editor' guard", "deny"),
    ("pkill", "deny"),
    ("killall python3", "deny"),
    ("killall Finder", "deny"),
    ("killall -m '.*'", "deny"),
    ("killall -u someone xcodebuild", "deny"),
    ("pkill -x 'Fabric Editor'", None),
    ("pkill -f 'Fabric Editor'", None),
    ("pkill -9 -f 'Fabric Editor.app/Contents/MacOS/Fabric Editor'", None),
    ("killall 'Fabric Editor'", None),
    ("killall -9 xcodebuild", None),
    ("pkill -x swift-build", None),
    ("pgrep -f 'Fabric Editor'", None),
    ("git log --grep kill", None),
]
failures = 0
try:
    for command, expected in cases:
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": MAIN, "session_id": "abc"}
        result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
        output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
        if output.get("permissionDecision") != expected or result.returncode:
            failures += 1
            print(f"FAIL {command}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()[:300]}")
finally:
    target.kill()

with open(os.path.join(BOT, "settings.json")) as handle:
    permissions = json.load(handle)["permissions"]
for rule in ("Bash(kill *)", "Bash(killall *)", "Bash(pkill *)", "TaskStop"):
    if rule not in permissions["allow"] or rule in permissions["deny"]:
        failures += 1
        print(f"FAIL {rule} should be allowed (the guard checks it)")
print(f"{len(cases) + 4} cases, {failures} failures")
