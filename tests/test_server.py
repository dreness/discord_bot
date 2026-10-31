import json, os, socket, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from support import BOT, CONFIG, isolated_guard, render
CLIENT = os.path.join(tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"]), "guard-client")
subprocess.run(["/usr/bin/clang", "-O2", "-o", CLIENT, os.path.join(BOT, "guard-client.c")], check=True)
guard, config, registry = isolated_guard()
SOCKET = os.path.join(config["TEMP_ROOT"], "guard.sock")
MAIN = CONFIG["CHECKOUT"]
failures = 0
payloads = [
    ("Read", {"file_path": f"{MAIN}/Package.swift"}),
    ("Read", {"file_path": f"{CONFIG['DISCORD_STATE_DIR']}/.env"}),
    ("Bash", {"command": "ls Sources"}),
    ("Bash", {"command": "git push origin main"}),
    ("Bash", {"command": "curl https://example.com"}),
    ("Bash", {"command": "swift build"}),
    ("Bash", {"command": "swift build -j 4 --scratch-path .build.noindex"}),
    ("Bash", {"command": "claude -p hi"}),
    ("Write", {"file_path": f"{config['SCRATCH_ROOT']}/notes.md", "content": "x" * 300000}),
    ("mcp__plugin_discord_discord__reply", {"chat_id": "1", "text": "Build passed."}),
    ("mcp__vm-driver__list_windows", {}),
    ("mcp__vm-driver__click", {"x": 1, "y": 1}),
]


def request(tool, tool_input, program):
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": MAIN, "session_id": "abc"})
    result = subprocess.run(program, input=payload, capture_output=True, text=True, cwd=MAIN)
    return result.returncode, result.stdout


def fail(message):
    global failures
    failures += 1
    print(f"FAIL {message}")


def start_server():
    server = subprocess.Popen([sys.executable, "-I", guard, "--serve", SOCKET])
    for _ in range(100):
        if os.path.exists(SOCKET):
            return server
        time.sleep(0.05)
    fail("server never bound its socket")
    return server


client = [CLIENT, SOCKET, guard]
direct = [sys.executable, "-I", guard]
for tool, tool_input in payloads:
    expected = request(tool, tool_input, direct)
    if request(tool, tool_input, client) != expected:
        fail(f"fallback differs for {tool} {str(tool_input)[:80]}")

server = start_server()
for tool, tool_input in payloads:
    expected = request(tool, tool_input, direct)
    if request(tool, tool_input, client) != expected:
        fail(f"server differs for {tool} {str(tool_input)[:80]}: {request(tool, tool_input, client)} vs {expected}")
with ThreadPoolExecutor(16) as pool:
    expected = [request(tool, tool_input, direct) for tool, tool_input in payloads]
    for round in range(3):
        if list(pool.map(lambda case: request(*case, client), payloads)) != expected:
            fail("concurrent requests differ")

# Edits to the guard take effect on the next call, and checks see the client's environment and working directory.
probe_code = 'import io\noriginal_main = main\n\n\ndef main():\n    data = sys.stdin.read()\n    if "reload-marker" in data:\n        deny(f"reloaded {os.environ.get(\'GUARD_PROBE\')} {os.getcwd()}")\n    sys.stdin = io.StringIO(data)\n    original_main()\n\n\n'
with open(guard) as handle:
    source = handle.read()
entry = 'if __name__ == "__main__":'
assert entry in source
with open(guard, "w") as handle:
    handle.write(source.replace(entry, probe_code + entry))
marker = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo reload-marker"}, "cwd": MAIN, "session_id": "abc"})
probe = os.path.join(config["SCRATCH_ROOT"], "probe.noindex")
os.makedirs(probe)


def marker_reply():
    return subprocess.run(client, input=marker, capture_output=True, text=True, cwd=probe, env=os.environ | {"GUARD_PROBE": "seen"}).stdout


for _ in range(2):
    if f"reloaded seen {os.path.realpath(probe)}" not in marker_reply():
        fail(f"edited guard not used, or environment/directory not passed: {marker_reply()[:300]}")
time.sleep(0.5)
if server.poll() is not None:
    fail("server exited instead of restarting")

server.kill()
server.wait()
after_kill = marker_reply(), request("Bash", {"command": "curl x"}, client)
if "reloaded seen" not in after_kill[0] or "deny" not in after_kill[1][1]:
    fail(f"fallback after the server was killed: {after_kill}")

# The server exits once the process that started it does, and removes its socket.
launcher = subprocess.Popen(["/bin/bash", "-c", f'"{sys.executable}" -I "{guard}" --serve "{SOCKET}" & exec /bin/sleep 1'])
launcher.wait()
for _ in range(60):
    if not os.path.exists(SOCKET):
        break
    time.sleep(0.1)
else:
    fail("server outlived its session")
# A server that takes connections but never reads or replies, like a stopped one, falls back after the timeout.
silent_path = os.path.join(config["TEMP_ROOT"], "silent.sock")
silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
silent.bind(silent_path)
silent.listen(64)
for tool, tool_input in (("Bash", {"command": "curl x"}), ("Write", {"file_path": f"{config['SCRATCH_ROOT']}/notes.md", "content": "x" * 300000})):
    started = time.monotonic()
    result = request(tool, tool_input, [CLIENT, silent_path, guard, "2"])
    elapsed = time.monotonic() - started
    if result != request(tool, tool_input, direct) or not 2 <= elapsed < 3.5:
        fail(f"silent server, {tool}: {result[0]} {result[1][:200]} after {elapsed:.1f} s")
silent.close()
os.unlink(silent_path)
# The call only proceeds on an answer from the guard: a fallback that can't start, crashes, exits nonzero or hangs denies.
broken = os.path.join(config["SCRATCH_ROOT"], "broken.noindex")
os.makedirs(broken)
for name, code in (("exits.py", "import sys\nsys.exit(1)\n"), ("crashes.py", "import os, signal\nos.kill(os.getpid(), signal.SIGSEGV)\n"), ("hangs.py", "import sys, time\nsys.stdin.read()\ntime.sleep(60)\n")):
    with open(os.path.join(broken, name), "w") as handle:
        handle.write(code)
for name in ("exits.py", "crashes.py", "hangs.py", "missing.py"):
    started = time.monotonic()
    code, output = request("Bash", {"command": "ls"}, [CLIENT, os.path.join(broken, "none.sock"), os.path.join(broken, name), "2"])
    if code or '"deny"' not in output or time.monotonic() - started > 3.5:
        fail(f"broken fallback {name}: {code} {output[:200]} after {time.monotonic() - started:.1f} s")
# Claude Code blocks the call when the hook command can't run, crashes or times out. The timeout leaves room for both
# of the client's attempts, so its deny explains why.
with open(os.path.join(BOT, "settings.json")) as handle:
    hook = json.load(handle)["hooks"]["PreToolUse"][0]["hooks"][0]
command = render(hook["command"])
client_path = render("{{BOT_DIRECTORY}}/rendered/guard-client")
if hook.get("onFailure") != "block" or hook["timeout"] <= 2 * 30 or client_path not in command:
    fail(f"hook entry: {hook}")
curl = json.dumps({"tool_name": "Bash", "tool_input": {"command": "curl https://example.com"}, "cwd": MAIN, "session_id": "abc"})
result = subprocess.run(["/bin/sh", "-c", command.replace(client_path, CLIENT)], input=curl, capture_output=True, text=True, cwd=MAIN)
if result.returncode or '"deny"' not in result.stdout:
    fail(f"hook command with a working client: {result.returncode} {result.stdout[:200]} {result.stderr[-200:]}")
# A crashing check denies instead of exiting 1, which would let the call through.
for program in (client, direct):
    result = subprocess.run(program, input="not json", capture_output=True, text=True)
    if result.returncode or '"deny"' not in result.stdout:
        fail(f"malformed payload through {program[0]}: {result.returncode} {result.stdout[:200]} {result.stderr[-300:]}")
print(f"{len(payloads) * 2 + 17} cases, {failures} failures")
