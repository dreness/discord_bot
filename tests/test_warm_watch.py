import atexit, os, shutil, signal, subprocess, sys, tempfile, time
from support import BOT, CONFIG
root = tempfile.mkdtemp(dir=CONFIG["SCRATCH_ROOT"])
atexit.register(shutil.rmtree, root, True)
warm = os.path.join(root, "warm-main.noindex")
request, lease, ready = (os.path.join(warm, name) for name in ("refresh-requested", "lease", "READY"))
runs, fakes = (os.path.join(root, name) for name in ("runs.log", "bin"))
os.makedirs(warm)
os.mkdir(fakes)
# The refresher stand-in holds the lease like warm-main.sh.
script = os.path.join(root, "warm-main.sh")
with open(script, "w") as handle:
    handle.write(f'echo run >> {runs}; mkdir {lease} && rmdir {lease}; touch {ready}\n')
# The watcher's pgrep reports the pids in build.pid, if any.
build_pid = os.path.join(root, "build.pid")
with open(os.path.join(fakes, "pgrep"), "w") as handle:
    handle.write(f"#!/bin/bash\ncat {build_pid} 2>/dev/null\n")
os.chmod(os.path.join(fakes, "pgrep"), 0o755)


def start():
    watcher = subprocess.Popen([sys.executable, "-I", os.path.join(BOT, "warm-watch.py")], env=dict(
        os.environ, PATH=fakes + ":" + os.environ["PATH"], WARM_WATCH_SCRIPT=script, WARM_MAIN_TASK_ROOT=root))
    atexit.register(watcher.kill)
    return watcher


def stop(watcher):
    watcher.send_signal(signal.SIGTERM)
    watcher.wait()


open(ready, "w").close()
open(request, "w").close()
watcher = start()

failures = 0
cases = 0


def count():
    time.sleep(0.5)
    return len(open(runs).read().split()) if os.path.exists(runs) else 0


def check(name, expected):
    global failures, cases
    cases += 1
    got = count()
    if got != expected:
        failures += 1
        print(f"FAIL {name}: {got} runs, expected {expected}")


check("request present at start", 1)
check("refresher's own lease is not a return", 1)
open(request, "w").close()
check("launch request", 2)
os.mkdir(lease)
check("borrowing does not refresh", 2)
os.rmdir(lease)
check("return with READY present does not refresh", 2)
os.mkdir(lease)
os.remove(ready)
os.rmdir(lease)
check("return refreshes", 3)
build = subprocess.Popen(["/bin/sleep", "2"])
with open(build_pid, "w") as handle:
    handle.write(f"{build.pid}\n")
open(request, "w").close()
check("waits for the builds", 3)
build.wait()
check("runs after the builds exit", 4)
check("no repeat", 4)
# The build pgrep reports has exited but is not reaped: nothing to wait on, so the refresh runs.
open(request, "w").close()
check("exited build is not waited on", 5)
os.remove(build_pid)

stop(watcher)
os.remove(ready)
watcher = start()
check("start without READY refreshes", 6)
stop(watcher)
watcher = start()
check("start with READY does not refresh", 6)
stop(watcher)
print(f"{cases} cases, {failures} failures")
