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
    check("get unset", run("get", user), ("frequency=updates verbosity=brief style=default (defaults; nothing saved)", 0))
    check("set one", run("set", user, "frequency=quiet"), ("saved: frequency=quiet verbosity=brief style=default", 0))
    check("set other keeps first", run("set", user, "verbosity=detailed"), ("saved: frequency=quiet verbosity=detailed style=default", 0))
    check("get saved", run("get", user)[0].startswith("frequency=quiet verbosity=detailed style=default (saved "), True)
    check("style not chosen", run("get", user)[0].endswith("; style not chosen)"), True)
    check("default style has no rules", "\n" in run("get", user)[0], False)
    check("other user", run("get", other), ("frequency=updates verbosity=brief style=default (defaults; nothing saved)", 0))
    check("set style", run("set", user, "style=adhd"), ("saved: frequency=quiet verbosity=detailed style=adhd", 0))
    line, status = run("get", user)
    check("adhd first line", line.split("\n")[0].startswith("frequency=quiet verbosity=detailed style=adhd (saved "), True)
    check("adhd scoped to requester", f"Reply style adhd for requesters with user_id {user}:" in line and "to no one else" in line, True)
    check("adhd rules", "### 1. Lead with the next action" in line and "## Pre-send check" in line, True)
    check("adhd no frontmatter", "disable-model-invocation" in line, False)
    check("adhd no persistence section", "## Persistence" in line or "rest of the session" in line, False)
    check("other user unaffected", run("get", other)[0].count("\n"), 0)
    run("set", other, "style=adhd")
    start = preferences.session_start(path, "/")
    check("session-start lists both", f"for requesters with user_id {user}, {other}:" in start, True)
    check("session-start ruleset once", start.count("## Pre-send check"), 1)
    check("session-start unmounted", preferences.session_start(path, os.path.join(scratch, "none")), "")
    check("style off", run("set", user, "style=default"), ("saved: frequency=quiet verbosity=detailed style=default", 0))
    check("style chosen default", run("get", user)[0].endswith("; style not chosen)"), False)
    run("set", other, "style=default")
    check("session-start nobody", preferences.session_start(path, "/"), "")
    broken = os.path.join(scratch, "broken.json")
    with open(broken, "w") as handle:
        handle.write("{not json")
    check("session-start unreadable", preferences.session_start(broken, "/"), "")
    legacy = os.path.join(scratch, "legacy.json")
    with open(legacy, "w") as handle:
        json.dump({user: {"style": "retired", "verbosity": "loud", "colour": "red", "frequency": "quiet", "updated": "x"}}, handle)
    old = lambda *arguments: preferences.run(list(arguments), legacy, "/", 1793400000)
    line, status = old("get", user)
    check("unknown values read as defaults", (line.startswith("frequency=quiet verbosity=brief style=default (saved "), status), (True, 0))
    check("unknown style counts as not chosen", line.endswith("; style not chosen)"), True)
    check("unknown style gives no rules", preferences.session_start(legacy, "/"), "")
    check("set keeps unknown", old("set", user, "frequency=updates"), ("saved: frequency=updates verbosity=brief style=default", 0))
    stored = json.load(open(legacy))[user]
    check("unknown stays stored", (stored["style"], stored["verbosity"], stored["colour"], stored["frequency"]), ("retired", "loud", "red", "updates"))
    check("session-start missing", preferences.session_start(os.path.join(scratch, "nothing.json"), "/"), "")
    check("file", set(json.load(open(path))[user]), {"frequency", "verbosity", "style", "updated"})
    for bad in (("set", user), ("set", user, "verbosity=loud"), ("set", user, "colour=red"), ("set", user, "frequency=quiet", "frequency=updates"), ("set", user, "style=loud"),
                ("get", "12"), ("get", user, "x"), ("delete", user), ()):
        check(f"usage {bad}", run(*bad)[1], 2)
    check("unmounted get", preferences.run(["get", user], path, os.path.join(scratch, "none"), 0),
          ("frequency=updates verbosity=brief style=default (defaults; storage unavailable (Cua Volume not mounted))", 0))
    check("unmounted set", preferences.run(["set", user, "frequency=quiet"], path, os.path.join(scratch, "none"), 0)[1], 1)

guard = os.path.join(BOT, "guard.py")
command = CONFIG["PREFERENCES_COMMAND"]
volume = CONFIG["CUA_VOLUME"]
cases = [
    ("Bash", {"command": f"{command} get {user}"}, None),
    ("Bash", {"command": f"{command} set {user} frequency=quiet verbosity=detailed"}, None),
    ("Bash", {"command": f"{command} set {user} style=adhd"}, None),
    ("Bash", {"command": f"{command} set {user} frequency=quiet verbosity=detailed style=default"}, None),
    ("Bash", {"command": f"{command} set {user} style=loud"}, "deny"),
    ("Bash", {"command": f"{command} session-start"}, "deny"),
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
