import json, os, shutil, subprocess, sys, time
from support import TAG, isolated_guard, register_session, render as render_with
guard, CONFIG, registry = isolated_guard(lock_holder=None)
LOCK = CONFIG["EDITOR_LOCK"]
HOLDER = os.path.join(LOCK, "holder.json")
TASKS = CONFIG["TASK_ROOT"]
MAIN = render_with("{{CHECKOUT}}", config=CONFIG)
JOBS = int(CONFIG["BUILD_JOBS"])
for session in ("main", "other"):
    register_session(registry, session)
failures = 0


def run(tool, tool_input, session="main", agent=None):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": MAIN, "session_id": session}
    if agent:
        payload |= {"agent_id": agent, "agent_type": "general-purpose"}
    result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    return output.get("permissionDecision"), output.get("permissionDecisionReason", "") + result.stderr


def check(label, outcome, expected, phrase=""):
    global failures
    decision, reason = outcome
    if decision != expected or phrase not in reason:
        failures += 1
        print(f"FAIL {label}: expected {expected} '{phrase}', got {decision} {reason[:200]}")


def bash(command, **caller):
    return run("Bash", {"command": command}, **caller)


def vm(**caller):
    return run("mcp__vm-driver__zoom", {"window_id": 7, "x1": 0, "y1": 0, "x2": 10, "y2": 10}, **caller)


def age_lock(seconds):
    then = time.time() - seconds
    os.utime(HOLDER, (then, then))


check("driver without lock", vm(), "deny", "needs its lock")
check("list_windows without lock", run("mcp__vm-driver__list_windows", {}), None)
check("plain mkdir", bash(f"mkdir {LOCK}"), "deny", "mkdir -p")
check("take lock", bash(f"mkdir -p {LOCK}"), None)
with open(HOLDER) as handle:
    taken = json.load(handle)
if taken.get("session") != "main" or taken.get("agent") != "":
    failures += 1
    print(f"FAIL holder.json: {taken}")
check("holder retakes", bash(f"mkdir -p {LOCK}"), None)
check("holder uses driver", vm(), None)
check("other session uses driver", vm(session="other"), "deny", "needs its lock")
check("subagent of holder session uses driver", vm(agent="a1"), "deny", "this agent")
check("other session takes lock", bash(f"mkdir -p {LOCK}", session="other"), "deny", "in use")
check("mkdir inside lock", bash(f"mkdir -p {LOCK}/x"), "deny", "only task.txt")
check("other session removes lock", bash(f"rm -r {LOCK}", session="other"), "deny", "belongs to another task")
check("other session removes task root", bash(f"rm -rf {TASKS}", session="other"), "deny")
check("other session moves lock aside", bash(f"mv {LOCK} {TASKS}/old.lock", session="other"), "deny", "belongs to another task")
check("write holder.json", run("Write", {"file_path": HOLDER, "content": "{}"}), "deny")
check("edit holder.json via shell", bash(f"echo '{{}}' > {HOLDER}"), "deny")

age_lock(10 * 60)
bash("true")
if time.time() - os.path.getmtime(HOLDER) > 60:
    failures += 1
    print("FAIL heartbeat: a holder tool call did not refresh holder.json")
age_lock(10 * 60)
bash("true", session="other")
if time.time() - os.path.getmtime(HOLDER) < 9 * 60:
    failures += 1
    print("FAIL heartbeat: another session's tool call refreshed holder.json")

age_lock(16 * 60)
check("take idle lock", bash(f"mkdir -p {LOCK}", session="other"), "deny", "stale: its holder has made no tool calls for 16 minutes")
check("break idle lock", bash(f"rm -r {LOCK}", session="other"), None)
check("holder releases", bash(f"rm -r {LOCK}"), None)

shutil.rmtree(LOCK)
gone = subprocess.Popen(["/usr/bin/true"])
gone.wait()
register_session(registry, "gone", gone.pid)
check("gone session takes lock", bash(f"mkdir -p {LOCK}", session="gone"), None)
check("take lock of ended session", bash(f"mkdir -p {LOCK}"), "deny", "session gone is no longer running")
check("break lock of ended session", bash(f"rm -r {LOCK}"), None)
shutil.rmtree(LOCK)

os.makedirs(LOCK)
check("take lock without holder.json", bash(f"mkdir -p {LOCK}"), "deny", "no readable holder.json")
check("break lock without holder.json", bash(f"rm -r {LOCK}"), None)
shutil.rmtree(LOCK)

# Running builds share the job limit when their directory or arguments are in the task root.
fake = os.path.join(CONFIG["SCRATCH_ROOT"], "bin.noindex")
os.makedirs(fake)
os.symlink(os.path.realpath(sys.executable), os.path.join(fake, "swift-build"))
outside = os.path.join(CONFIG["SCRATCH_ROOT"], "elsewhere.noindex")
inside = os.path.join(TASKS, "pr1", "tree.noindex")
for folder in (outside, inside):
    os.makedirs(folder)
sleeper = [os.path.join(fake, "swift-build"), "-c", "import time; time.sleep(60)"]
elsewhere = subprocess.Popen(sleeper + ["-j", str(JOBS)], cwd=outside)
try:
    time.sleep(0.5)
    check("build beside an unrelated build", bash(f"cd {inside} && {TAG}swift build -j {JOBS}"), None)
    running = subprocess.Popen(sleeper + ["-j", str(JOBS - 2)], cwd=inside)
    try:
        time.sleep(0.5)
        check("build over the shared limit", bash(f"cd {inside} && {TAG}swift build -j 4"), "deny", "run this one with 2 jobs")
        check("build within the shared limit", bash(f"cd {inside} && {TAG}swift build -j 2"), None)
        check("xcodebuild over the shared limit", bash(f"cd {inside} && {TAG}xcodebuild -scheme X -derivedDataPath dd.noindex -jobs 3 build"), "deny", f"{JOBS - 2} are taken")
    finally:
        running.kill()
        running.wait()
    unflagged = subprocess.Popen(sleeper, cwd=inside)
    try:
        time.sleep(0.5)
        check("build beside a build without a job flag", bash(f"cd {inside} && {TAG}swift build -j 1"), "deny", "wait for those to finish")
    finally:
        unflagged.kill()
        unflagged.wait()
finally:
    elsewhere.kill()
    elsewhere.wait()
print(f"failures: {failures}")
