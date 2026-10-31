import atexit, json, os, shutil, subprocess, sys, tempfile
from support import BOT, CONFIG
guard = os.path.join(BOT, "guard.py")
STATE = CONFIG["DISCORD_STATE_DIR"]
HOME = CONFIG["HOME"]
MAIN = CONFIG["CHECKOUT"]
scratch = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
atexit.register(shutil.rmtree, scratch, True)
os.symlink(os.path.dirname(STATE), os.path.join(scratch, "link"))
with open(os.path.join(scratch, "peek.py"), "w") as handle:
    handle.write("import os\nprint(open(os.path.join(os.path.expanduser('~/.claude'), 'channels', 'discord', '.env')).read())\n")
with open(os.path.join(scratch, "plain.py"), "w") as handle:
    handle.write("print('hello')\n")
cases = [
    ("Read", {"file_path": f"{STATE}/.env"}, "deny"),
    ("Read", {"file_path": f"{STATE}/inbox/1-2.png"}, "deny"),
    ("Read", {"file_path": f"{scratch}/link/discord/access.json"}, "deny"),
    ("Glob", {"pattern": "**/*", "path": STATE}, "deny"),
    ("Glob", {"pattern": "*", "path": os.path.dirname(STATE)}, "deny"),
    ("Glob", {"pattern": "~/.claude/channels/**"}, "deny"),
    ("Grep", {"pattern": "TOKEN", "path": os.path.join(HOME, ".claude")}, "deny"),
    ("Write", {"file_path": f"{STATE}/access.json", "content": "{}"}, "deny"),
    ("Edit", {"file_path": f"{STATE}/access.json", "old_string": "a", "new_string": "b"}, "deny"),
    ("Bash", {"command": "cat ~/.claude/channels/discord/.env"}, "deny"),
    ("Bash", {"command": "stat $HOME/.claude/channels/discord"}, "deny"),
    ("Bash", {"command": f"ls -la {STATE}"}, "deny"),
    ("Bash", {"command": "ls ~/.claude/chan*/disc*"}, "deny"),
    ("Bash", {"command": "cat ~/.cl*/ch*/d*/access.json"}, "deny"),
    ("Bash", {"command": "cd ~/.claude && cat channels/discord/.env"}, "deny"),
    ("Bash", {"command": "cd ~/.claude"}, "deny"),
    ("Bash", {"command": f"cp {scratch}/link/discord/.env {scratch}/x"}, "deny"),
    ("Bash", {"command": f"cat {scratch}/link/*/.env"}, "deny"),
    ("Bash", {"command": f"ditto ~ {scratch}/home.noindex"}, "deny"),
    ("Bash", {"command": f"cp -R ~ {scratch}/home.noindex"}, "deny"),
    ("Bash", {"command": "grep -r TOKEN ~"}, "deny"),
    ("Bash", {"command": "find ~ -name .env"}, "deny"),
    ("Bash", {"command": "tar czf x.tgz ~/.claude"}, "deny"),
    ("Bash", {"command": f"D=~/.claude; ls $D"}, "deny"),
    ("Bash", {"command": f"echo x > {STATE}/access.json"}, "deny"),
    ("Bash", {"command": "python3 -c \"import os; print(os.listdir(os.path.join(os.path.expanduser('~/.claude'), 'channels')))\""}, "deny"),
    ("Bash", {"command": f"python3 {scratch}/peek.py"}, "deny"),
    ("Bash", {"command": "env DISCORD_STATE_DIR=/tmp/x ls"}, "deny"),
    ("Monitor", {"command": "tail -f ~/.claude/channels/discord/access.json", "description": "x", "timeout_ms": 1000}, "deny"),
    ("Monitor", {"ws": {"url": "wss://example.com"}, "description": "x", "timeout_ms": 1000}, "deny"),
    ("Monitor", {"command": "curl https://example.com", "description": "x", "timeout_ms": 1000}, "deny"),
    ("mcp__plugin_discord_discord__reply", {"chat_id": "1", "text": "here", "files": [f"{STATE}/access.json"]}, "deny"),
    ("mcp__plugin_discord_discord__reply", {"chat_id": "1", "text": "here", "files": [f"{scratch}/link/discord/.env"]}, "deny"),
    ("mcp__vm-driver__clipboard_write", {"file_path": f"{STATE}/.env"}, "deny"),
    ("mcp__vm-driver__get_window_state", {"pid": 1, "window_id": 1, "screenshot_out_file": f"{STATE}/x.png"}, "deny"),
    # Ordinary work is untouched.
    ("Bash", {"command": f"python3 {scratch}/plain.py"}, None),
    ("Bash", {"command": "ls ~"}, None),
    ("Bash", {"command": "grep -rn 'channels' Sources | head"}, None),
    ("Bash", {"command": "find . -name '*.swift' -newer Package.swift"}, None),
    ("Bash", {"command": f"ls {scratch}/*.py"}, None),
    ("Monitor", {"command": "tail -f build.log | grep --line-buffered error", "description": "x", "timeout_ms": 1000}, None),
    ("Read", {"file_path": f"{MAIN}/Package.swift"}, None),
    ("Grep", {"pattern": "channels", "path": MAIN}, None),
]
failures = 0
for tool, tool_input, expected in cases:
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": MAIN, "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    if output.get("permissionDecision") != expected or result.returncode:
        failures += 1
        print(f"FAIL {tool} {str(tool_input)[:110]}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()[:300]}")
print(f"{len(cases)} cases, {failures} failures")
