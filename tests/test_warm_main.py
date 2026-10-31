import json, os, shutil, subprocess, sys, tempfile
from support import BOT, CONFIG
SCRIPT = os.path.join(BOT, "warm-main.sh")
root = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
origin, checkout, task_root, fakes = (os.path.join(root, name) for name in ("origin", "checkout", "tasks", "bin"))
log = os.path.join(root, "calls.log")
os.mkdir(fakes)


def git(directory, *arguments):
    return subprocess.run(["git", "-C", directory, "-c", "user.email=t@t", "-c", "user.name=t", *arguments], check=True, capture_output=True, text=True).stdout.strip()


def fake(name, body):
    path = os.path.join(fakes, name)
    with open(path, "w") as handle:
        handle.write("#!/bin/bash\n" + body + "\n")
    os.chmod(path, 0o755)


fake("swift", f'echo "swift $*" >> {log}; mkdir -p .build.noindex/out/Products/Release; exit ${{FAKE_SWIFT_EXIT:-0}}')
fake("xcodebuild", f'echo "xcodebuild $*" >> {log}')
fake("pgrep", "exit 1")

os.makedirs(origin)
git(origin, "init", "-q", "-b", "main")
with open(os.path.join(origin, "a.txt"), "w") as handle:
    handle.write("1\n")
git(origin, "add", "a.txt")
git(origin, "commit", "-qm", "one")
subprocess.run(["git", "clone", "-q", origin, checkout], check=True)
os.makedirs(os.path.join(checkout, "Frameworks"))
warm = os.path.join(task_root, "warm-main.noindex")
tree, lease, ready = (os.path.join(warm, name) for name in ("Fabric", "lease", "READY"))


def run(**extra):
    if os.path.exists(log):
        os.remove(log)
    environment = dict(os.environ, PATH=fakes + ":" + os.environ["PATH"], WARM_MAIN_CHECKOUT=checkout, WARM_MAIN_TASK_ROOT=task_root, **extra)
    result = subprocess.run(["/bin/bash", SCRIPT], env=environment, capture_output=True, text=True)
    calls = open(log).read() if os.path.exists(log) else ""
    return result, calls


def read(path):
    return open(path).read().strip() if os.path.exists(path) else None


failures = 0
cases = 0


def check(name, condition, detail=""):
    global failures, cases
    cases += 1
    if not condition:
        failures += 1
        print(f"FAIL {name} {detail}")


result, calls = run()
head = git(origin, "rev-parse", "HEAD")
check("first run builds", read(ready) == head and "-Xswiftc -enable-testing --build-tests --scratch-path .build.noindex" in calls and "xcodebuild" in calls, result.stdout + result.stderr)
check("first run frees lease", not os.path.exists(lease))
check("sparkle link", os.path.islink(os.path.join(tree, ".build.noindex/out/Products/Release/Sparkle.framework")))

result, calls = run()
check("no change, no build", calls == "" and read(ready) == head, calls)

with open(os.path.join(origin, "a.txt"), "w") as handle:
    handle.write("2\n")
git(origin, "commit", "-qam", "two")
with open(os.path.join(tree, "stray.txt"), "w") as handle:
    handle.write("x")
result, calls = run()
head = git(origin, "rev-parse", "HEAD")
check("new main rebuilds", read(ready) == head and git(tree, "rev-parse", "HEAD") == head and "swift build" in calls, result.stdout + result.stderr)
check("clean keeps build", not os.path.exists(os.path.join(tree, "stray.txt")) and os.path.isdir(os.path.join(tree, ".build.noindex")))

os.remove(ready)
os.mkdir(lease)
with open(os.path.join(lease, "task.txt"), "w") as handle:
    handle.write("review Fabric#1 for someone")
result, calls = run()
check("borrowed lease is left alone", calls == "" and os.path.exists(os.path.join(lease, "task.txt")) and read(ready) is None, calls)
subprocess.run(["touch", "-t", "202001010000", lease], check=True)
result, calls = run()
check("lease over 12 h is taken back", read(ready) == head and not os.path.exists(lease), result.stdout)

os.remove(ready)
os.mkdir(lease)
with open(os.path.join(lease, "refresher.pid"), "w") as handle:
    handle.write("999999")
result, calls = run()
check("dead refresher's lease is taken back", read(ready) == head, result.stdout)

os.remove(ready)
result, calls = run(FAKE_SWIFT_EXIT="1")
check("failed build leaves no READY", read(ready) is None and not os.path.exists(lease) and "swift build failed" in result.stdout, result.stdout)

shutil.rmtree(warm)
result, calls = run()
check("missing worktree is re-added", read(ready) == head and git(tree, "rev-parse", "HEAD") == head, result.stdout + result.stderr)

shutil.rmtree(root, True)

bot_warm = os.path.join(CONFIG["TASK_ROOT"], "warm-main.noindex")
for command, expected in [
    (f"rm -r {bot_warm}/lease", None),
    (f"rm {bot_warm}/READY", None),
    (f"rm -r {bot_warm}", "deny"),
    (f"rm -rf {bot_warm}/Fabric/.build.noindex", "deny"),
    (f"rm -r {bot_warm}/editor-dd.noindex", "deny"),
    (f"rm -rf {CONFIG['TASK_ROOT']}/*", "deny"),
    (f"find {bot_warm} -name '*.o' -delete", "deny"),
    (f"rm -r {CONFIG['TASK_ROOT']}/pr433", None),
    (f"git worktree remove --force {bot_warm}/Fabric", "deny"),
]:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": CONFIG["CHECKOUT"], "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", os.path.join(BOT, "guard.py")], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    check(command, output.get("permissionDecision") == expected, f"expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]}")
print(f"{cases} cases, {failures} failures")
