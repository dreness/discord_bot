import atexit, glob, http.server, json, os, shutil, socket, subprocess, sys, tempfile, threading, time
from support import BOT, CONFIG
guard = os.path.join(BOT, "guard.py")
MAIN = CONFIG["CHECKOUT"]
cases = [
    ("claude -p hi", "deny"),
    ("env claude --resume", "deny"),
    ("/opt/homebrew/bin/claude", "deny"),
    ("nohup claude &", "deny"),
    ("bash -c 'claude --channels plugin:discord@claude-plugins-official'", "deny"),
    ("python3 -c \"import subprocess; subprocess.run(['x', '--channels', 'y'])\"", "deny"),
    (f"{BOT}/run.sh", "deny"),
    ("git log --grep claude", None),
    ("grep -rn 'claude' Sources | head", None),
]
failures = 0
for command, expected in cases:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": MAIN, "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    if output.get("permissionDecision") != expected or result.returncode:
        failures += 1
        print(f"FAIL {command}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()[:300]}")

# run.sh against a copy whose launcher is a stub, so no session starts.
root = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
atexit.register(shutil.rmtree, root, True)
copy, state = os.path.join(root, "bot"), os.path.join(root, "state")
os.makedirs(copy)
os.makedirs(state)
for name in ("run.sh", "config.py", "settings.json", "BOT.md", ".envrc", "guard-client.c"):
    shutil.copy(os.path.join(BOT, name), copy)
TOKEN = "test-token"
token_file = os.path.join(root, "token")
with open(token_file, "w") as handle:
    handle.write(TOKEN + "\n")


# A stand-in for spacesd's MCP endpoint: initialize with the right token gets a session id.
class Driver(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        valid = self.headers.get("Authorization") == f"Bearer {TOKEN}" and request.get("method") == "initialize"
        self.send_response(200 if valid else 401)
        if valid:
            self.send_header("mcp-session-id", "test")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *arguments):
        pass


driver = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Driver)
threading.Thread(target=driver.serve_forever, daemon=True).start()
with open(os.path.join(copy, ".envrc"), "a") as handle:
    handle.write(f'\nexport FABRIC_BOT_DISCORD_STATE_DIR="{state}"\nexport FABRIC_BOT_DRIVER_TOKEN_FILE="{token_file}"\n'
                 f'export FABRIC_BOT_DRIVER_MCP_URL="http://127.0.0.1:{driver.server_address[1]}/mcp"\n'
                 'export FABRIC_BOT_LLM_PROXY=""\n'
                 f'export FABRIC_BOT_TEMP_ROOT="{root}/temp"\n')
with open(os.path.join(copy, "bot-env.sh"), "w") as handle:
    handle.write('#!/bin/bash\n[[ $2 == --version ]] && { echo "${CLAUDE_STUB_VERSION:-2.1.295} (Claude Code)"; exit; }\necho "launched proxy=${HTTPS_PROXY-} ca=${NODE_EXTRA_CA_CERTS-} ssl=${SSL_CERT_FILE-} no_proxy=${NO_PROXY-}"\nexec /bin/sleep 30\n')
os.chmod(os.path.join(copy, "bot-env.sh"), 0o755)
plugin = os.path.join(root, "plugins", "discord", "0.0.4")
os.makedirs(plugin)
fake_bun = os.path.join(root, "bun")
os.symlink(os.path.realpath(sys.executable), fake_bun)
# The fake runs as "bun run --cwd ...": python takes "run" as its script.
with open(os.path.join(root, "run"), "w") as handle:
    handle.write("import time\ntime.sleep(60)\n")


def launch(environment=None):
    return subprocess.Popen([os.path.join(copy, "run.sh")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)


def check(label, process, expected_output, expect_running):
    global failures
    time.sleep(2)
    running = process.poll() is None
    if running:
        process.kill()
    out, err = process.communicate()
    if running != expect_running or expected_output not in out + err:
        failures += 1
        print(f"FAIL {label}: running={running}, output {(out + err).strip()[:300]}")


# Plugin servers of other sessions block startup; the real ones on this machine would too, so the pattern is narrowed to the fake.
with open(os.path.join(copy, "run.sh")) as handle:
    script = handle.read()
real_pattern = "/bun run --cwd .*\\/discord\\/[^ ]+ .*start$/"
assert real_pattern in script
with open(os.path.join(copy, "run.sh"), "w") as handle:
    handle.write(script.replace(real_pattern, real_pattern.replace("--cwd ", f"--cwd " + root.replace("/", "\\/") + "\\/plugins")))
server = subprocess.Popen([fake_bun, "run", "--cwd", plugin, "--shell=bun", "--silent", "start"], cwd=root)
try:
    time.sleep(0.5)
    check("launch beside a plugin server", launch(), "Discord plugin servers are already connected", False)
finally:
    server.kill()
    server.wait()

# Older Claude Code lacks the hook's onFailure, so a failed hook would let calls through.
check("launch with Claude Code 2.1.294", launch(os.environ | {"CLAUDE_STUB_VERSION": "2.1.294"}), "older than 2.1.295", False)

# The Editor tools need spacesd; a missing token or a server that refuses it stops the launch.
os.rename(token_file, token_file + ".moved")
check("launch without the spacesd token", launch(), "no vm-driver MCP config", False)
with open(token_file, "w") as handle:
    handle.write("wrong\n")
check("launch with a wrong spacesd token", launch(), "did not answer initialize", False)
os.replace(token_file + ".moved", token_file)

first = launch()
time.sleep(2)
check("second launch", launch(), "another bot launch holds", False)
first.kill()
first.wait()
check("launch after the first was killed", launch(), "launched", True)
# The request lands under this test's temp root (FABRIC_BOT_TEMP_ROOT above), so a running watcher never sees it.
requests = glob.glob(os.path.join(root, "temp", "*", "discord-bot", "warm-main.noindex", "refresh-requested"))
if len(requests) != 1:
    failures += 1
    print(f"FAIL launch requests a warm tree refresh: {requests}")


# A stand-in for the observer proxy: it answers the proxied health probe.
class Proxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "http://llm-proxy.invalid/" else 404)
        self.end_headers()

    def log_message(self, *arguments):
        pass


proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
threading.Thread(target=proxy.serve_forever, daemon=True).start()
proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
# A freed port refuses at once; macOS drops connections to one that is bound but not listening.
closed = socket.socket()
closed.bind(("127.0.0.1", 0))
closed_url = f"http://127.0.0.1:{closed.getsockname()[1]}"
closed.close()
ca = os.path.join(root, "ca.pem")
with open(ca, "w") as handle:
    handle.write("test\n")
with open(os.path.join(copy, ".envrc")) as handle:
    base_envrc = handle.read()
proxy_cases = [
    ("healthy proxy", proxy_url, ca, f"launched proxy={proxy_url} ca={ca} ssl={ca} no_proxy=localhost,127.0.0.1"),
    ("unhealthy proxy", closed_url, ca, "launched proxy= ca= ssl= no_proxy="),
    ("proxy CA missing", proxy_url, ca + ".missing", "launched proxy= ca= ssl= no_proxy="),
    ("no proxy configured", "", ca, "launched proxy= ca= ssl= no_proxy="),
]
for label, url, ca_path, expected in proxy_cases:
    with open(os.path.join(copy, ".envrc"), "w") as handle:
        handle.write(base_envrc + f'export FABRIC_BOT_LLM_PROXY="{url}"\nexport FABRIC_BOT_LLM_PROXY_CA="{ca_path}"\n')
    # A proxy from the caller's environment never reaches the session.
    check(label, launch(os.environ | {"HTTPS_PROXY": "http://127.0.0.1:9", "NODE_EXTRA_CA_CERTS": "/x"}), expected, True)
print(f"{len(cases) + 7 + len(proxy_cases)} cases, {failures} failures")
