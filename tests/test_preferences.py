import json, os, subprocess, sys, tempfile, importlib.util
from support import BOT, CONFIG

spec = importlib.util.spec_from_file_location("preferences", os.path.join(BOT, "preferences.py"))
preferences = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preferences)
failures = 0


def check(label, got, expected):
    global failures
    if got != expected:
        failures += 1
        print(f"FAIL {label}: expected {expected!r}, got {got!r}")


user, other = "111111111111111111", "999999999999999999"
with tempfile.TemporaryDirectory() as scratch:
    path = os.path.join(scratch, "discord-bot", "preferences.json")
    run = lambda *arguments: preferences.run(list(arguments), path, "/", 1793400000)
    check("get unset", run("get", user), ("frequency=updates verbosity=brief (defaults; nothing saved)", 0))
    check("set one", run("set", user, "frequency=quiet"), ("saved: frequency=quiet verbosity=brief", 0))
    check("set other keeps first", run("set", user, "verbosity=detailed"), ("saved: frequency=quiet verbosity=detailed", 0))
    check("get saved", run("get", user)[0].startswith("frequency=quiet verbosity=detailed (saved "), True)
    check("other user", run("get", other), ("frequency=updates verbosity=brief (defaults; nothing saved)", 0))
    check("file", set(json.load(open(path))[user]), {"frequency", "verbosity", "updated"})
    for bad in (("set", user), ("set", user, "verbosity=loud"), ("set", user, "colour=red"), ("set", user, "frequency=quiet", "frequency=updates"),
                ("get", "12"), ("get", user, "x"), ("delete", user), ()):
        check(f"usage {bad}", run(*bad)[1], 2)
    check("unmounted get", preferences.run(["get", user], path, os.path.join(scratch, "none"), 0),
          ("frequency=updates verbosity=brief (defaults; storage unavailable (Cua Volume not mounted))", 0))
    check("unmounted set", preferences.run(["set", user, "frequency=quiet"], path, os.path.join(scratch, "none"), 0)[1], 1)

guard = os.path.join(BOT, "guard.py")
command = CONFIG["PREFERENCES_COMMAND"]
volume = CONFIG["CUA_VOLUME"]
cases = [
    ("Bash", {"command": f"{command} get {user}"}, None),
    ("Bash", {"command": f"{command} set {user} frequency=quiet verbosity=detailed"}, None),
    ("Bash", {"command": f"{command} set {user} verbosity=loud"}, "deny"),
    ("Bash", {"command": f"{command} get {user}; cat {command}"}, "deny"),
    ("Bash", {"command": f"{command} get $(whoami)"}, "deny"),
    ("Bash", {"command": f"cat {command}"}, "deny"),
    ("Bash", {"command": "ls ~/'Cua Volume'/public"}, "deny"),
    ("Read", {"file_path": os.path.join(volume, "spaces/local-fabric-bot/discord-bot/preferences.json")}, "deny"),
    ("Write", {"file_path": os.path.join(volume, "spaces/local-fabric-bot/x.txt"), "content": "x"}, "deny"),
    ("Glob", {"pattern": "*", "path": volume}, "deny"),
]
for tool, tool_input, expected in cases:
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": CONFIG["CHECKOUT"], "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    check(f"guard {tool} {tool_input}", output.get("permissionDecision"), expected)

print(f"{failures} failures")
sys.exit(1 if failures else 0)
