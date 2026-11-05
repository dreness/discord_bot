import importlib.util, json, os, subprocess, sys, tempfile
from support import BOT, CONFIG

spec = importlib.util.spec_from_file_location("context_status", os.path.join(BOT, "context-status.py"))
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)
failures = 0


def check(label, got, expected):
    global failures
    if got != expected:
        failures += 1
        print(f"FAIL {label}: expected {expected!r}, got {got!r}")


SESSION = "a28780d2-7a46-4487-b132-e9136cb7d587"


def status(size, usage, percent=None):
    return {"session_id": SESSION, "context_window": {"context_window_size": size, "current_usage": usage, "used_percentage": percent}}


usage = {"input_tokens": 2, "cache_creation_input_tokens": 724, "cache_read_input_tokens": 61107, "output_tokens": 331}
check("used", context.summarize(status(200000, usage, 31)), "Context: 62k of 200k tokens (31%).")
check("percent computed", context.summarize(status(200000, usage)), "Context: 62k of 200k tokens (31%).")
check("1M", context.summarize(status(1000000, {"cache_read_input_tokens": 1500000})), "Context: 1.5M of 1M tokens (150%).")
check("fresh", context.summarize(status(200000, None)), "Context: nothing used yet (200k window).")
for bad in ({}, {"context_window": None}, {"context_window": {"context_window_size": "x"}}, None, []):
    check(f"unavailable {bad!r}", context.summarize(bad), context.UNAVAILABLE)

with tempfile.TemporaryDirectory() as scratch:
    registry, directory = os.path.join(scratch, "sessions"), os.path.join(scratch, "context")
    os.mkdir(registry)
    with open(os.path.join(registry, "500.json"), "w") as handle:
        json.dump({"pid": 500, "sessionId": SESSION}, handle)
    with open(os.path.join(registry, "400.json"), "w") as handle:
        handle.write("{broken")
    check("own session nearest registered ancestor", context.own_session(registry, [300, 400, 500, 1]), SESSION)
    check("own session none", context.own_session(registry, [300, 400]), None)
    check("report before save", context.report(directory, SESSION), context.UNAVAILABLE)
    check("save line", context.save(directory, status(200000, usage, 31), 1793400000), "Context: 62k of 200k tokens (31%).")
    check("report after save", context.report(directory, SESSION), "Context: 62k of 200k tokens (31%).")
    check("report no session", context.report(directory, None), context.UNAVAILABLE)
    check("save rejects odd session id", context.save(directory, dict(status(200000, None), session_id="../x"), 0), "Context: nothing used yet (200k window).")
    check("only the valid file", sorted(os.listdir(directory)), [f"{SESSION}.json"])
    old = os.path.join(directory, "11111111-1111-1111-1111-111111111111.json")
    open(old, "w").close()
    os.utime(old, (0, 0))
    context.save(directory, status(200000, usage, 31), 1793400000)
    check("prunes old sessions", os.path.exists(old), False)

check("ancestors include parent", os.getppid() in context.ancestors(os.getpid()), True)

guard = os.path.join(BOT, "guard.py")
command = CONFIG["CONTEXT_COMMAND"]
cases = [
    ("Bash", {"command": command}, None),
    ("Bash", {"command": f"{command} statusline"}, "deny"),
    ("Bash", {"command": f"cat {command}"}, "deny"),
    ("Read", {"file_path": os.path.join(CONFIG["CONTEXT_DIRECTORY"], f"{SESSION}.json")}, "deny"),
]
for tool, tool_input, expected in cases:
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": CONFIG["CHECKOUT"], "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    check(f"guard {tool} {tool_input}", output.get("permissionDecision"), expected)

print(f"{failures} failures")
sys.exit(1 if failures else 0)
