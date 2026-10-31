import json, os, shutil, subprocess, sys, tempfile
from support import CONFIG, render
BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = 0
cases = 0


def check(name, condition, detail=""):
    global failures, cases
    cases += 1
    if not condition:
        failures += 1
        print(f"FAIL {name} {detail}")


def decision(directory):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": CONFIG["CHECKOUT"], "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", os.path.join(directory, "guard.py")], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    return output.get("permissionDecision"), output.get("permissionDecisionReason", ""), result.returncode


# The guard fails closed: no .envrc, or one lacking a required value, denies everything.
copy = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
for name in ("guard.py", "config.py"):
    shutil.copy(os.path.join(BOT, name), copy)
verdict, reason, code = decision(copy)
check("missing .envrc denies", verdict == "deny" and ".envrc" in reason and code == 0, reason)
with open(os.path.join(copy, ".envrc"), "w") as handle:
    handle.write('export FABRIC_BOT_CHECKOUT="$HOME/x"\nexport FABRIC_BOT_FORK_OWNER=someone\n')
verdict, reason, code = decision(copy)
check("incomplete .envrc denies", verdict == "deny" and "FABRIC_BOT_COMMIT_EMAIL" in reason and code == 0, reason)
shutil.rmtree(copy)
check("configured guard allows git status", decision(BOT)[0] is None)

# Templates render completely; settings stays valid JSON.
for name in ("settings.json", "BOT.md"):
    with open(os.path.join(BOT, name)) as handle:
        text = render(handle.read(), json_escaped=name.endswith(".json"))
    check(f"{name} fully rendered", "{{" not in text)
    if name.endswith(".json"):
        json.loads(text)
try:
    render("{{NOT_A_VALUE}}")
    check("unknown placeholder raises", False)
except KeyError:
    check("unknown placeholder raises", True)

# render puts the spacesd token only into rendered/mcp.json, mode 0600.
copy = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
for name in ("config.py", "settings.json", "BOT.md", ".envrc", "guard-client.c"):
    shutil.copy(os.path.join(BOT, name), copy)
token = "token-for-test-0123456789"
with open(os.path.join(copy, "token"), "w") as handle:
    handle.write(token + "\n")
with open(os.path.join(copy, ".envrc"), "a") as handle:
    handle.write(f'\nexport FABRIC_BOT_DRIVER_TOKEN_FILE="{copy}/token"\nexport FABRIC_BOT_DRIVER_MCP_URL="http://127.0.0.1:3999/mcp"\n')
result = subprocess.run([sys.executable, "-I", os.path.join(copy, "config.py"), "render"], capture_output=True, text=True)
check("render with a token", result.returncode == 0, result.stderr)
mcp = os.path.join(copy, "rendered", "mcp.json")
if os.path.exists(mcp):
    check("mcp.json is 0600", os.stat(mcp).st_mode & 0o777 == 0o600, oct(os.stat(mcp).st_mode))
    with open(mcp) as handle:
        server = json.load(handle)["mcpServers"]["vm-driver"]
    check("mcp.json carries the token", server["headers"]["Authorization"] == f"Bearer {token}" and server["url"] == "http://127.0.0.1:3999/mcp", server)
else:
    check("mcp.json written", False)
for name in ("settings.json", "BOT.md"):
    with open(os.path.join(copy, "rendered", name)) as handle:
        check(f"rendered {name} lacks the token", token not in handle.read())
os.remove(os.path.join(copy, "token"))
result = subprocess.run([sys.executable, "-I", os.path.join(copy, "config.py"), "render"], capture_output=True, text=True)
check("render without a token drops mcp.json", result.returncode == 0 and not os.path.exists(mcp) and "no vm-driver MCP config" in result.stderr, result.stderr)
shutil.rmtree(copy)

# A bad job cap fails closed like a missing value.
copy = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
for name in ("guard.py", "config.py", ".envrc"):
    shutil.copy(os.path.join(BOT, name), copy)
with open(os.path.join(copy, ".envrc"), "a") as handle:
    handle.write("\nexport FABRIC_BOT_BUILD_JOBS=many\n")
verdict, reason, code = decision(copy)
check("non-numeric BUILD_JOBS denies", verdict == "deny" and "BUILD_JOBS" in reason and code == 0, reason)
shutil.rmtree(copy)
print(f"{cases} cases, {failures} failures")
