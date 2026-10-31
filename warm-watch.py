#!/usr/bin/env python3
"""Runs warm-main.sh at each bot launch and after a task gives the warm tree back. Long-running, run by the guest
LaunchAgent local.discord-bot-warm (KeepAlive); between refreshes it blocks on kqueue and spawns nothing.
  launch:     run.sh creates warm-main.noindex/refresh-requested
  given back: the lease is removed while READY is absent (BOT.md's return steps)
  startup:    READY is absent (boot emptied /private/tmp, or a refresh was killed or failed before a restart)
While other builds run, the refresh waits for them all to exit."""
import os
import select
import subprocess
import sys
import time

DIRECTORY = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, DIRECTORY)
import config  # noqa: E402

BUILDS = "swift-build|swift-test|xcodebuild"
SCRIPT = os.environ.get("WARM_WATCH_SCRIPT") or os.path.join(DIRECTORY, "warm-main.sh")
WARM = os.path.join(os.environ.get("WARM_MAIN_TASK_ROOT") or config.values()["TASK_ROOT"], "warm-main.noindex")
REQUEST, LEASE, READY = (os.path.join(WARM, name) for name in ("refresh-requested", "lease", "READY"))


def log(message):
    print(time.strftime("%F %T"), "warm-watch:", message, flush=True)


def watch_exit(queue, pid):
    try:
        queue.control([select.kevent(pid, select.KQ_FILTER_PROC, select.KQ_EV_ADD | select.KQ_EV_ONESHOT, select.KQ_NOTE_EXIT)], 0)
        return True
    except ProcessLookupError:
        return False


def running_builds(queue):
    """Pids of other builds, each watched for exit. Zombies and builds that exit meanwhile are not included."""
    found = subprocess.run(["pgrep", "-x", BUILDS], capture_output=True, text=True).stdout.split()
    return {int(pid) for pid in found if watch_exit(queue, int(pid))}


def main():
    os.makedirs(WARM, exist_ok=True)
    queue = select.kqueue()
    directory = os.open(WARM, getattr(os, "O_EVTONLY", 0x8000))
    queue.control([select.kevent(directory, select.KQ_FILTER_VNODE, select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                                 select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME)], 0)
    child = None
    builds = set()
    pending = not os.path.exists(READY)
    lease_held = os.path.exists(LEASE)
    while True:
        # Changes made by a running refresh are not requests; the state is read again once it exits.
        if child is None:
            if os.path.exists(REQUEST):
                os.remove(REQUEST)
                pending = True
            held = os.path.exists(LEASE)
            if lease_held and not held and not os.path.exists(READY):
                log("warm tree given back")
                pending = True
            lease_held = held
            if pending and not builds:
                builds = running_builds(queue)
                if builds:
                    log(f"other builds running; refreshing after {len(builds)} exit")
                else:
                    pending = False
                    child = subprocess.Popen(["/bin/bash", SCRIPT])
                    watch_exit(queue, child.pid)
        for event in queue.control(None, 8, None):
            if event.filter == select.KQ_FILTER_VNODE and event.fflags & (select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME):
                sys.exit(f"{WARM} was removed")
            if event.filter != select.KQ_FILTER_PROC:
                continue
            if child is not None and event.ident == child.pid:
                child.wait()
                child = None
                lease_held = os.path.exists(LEASE)
            else:
                builds.discard(event.ident)


if __name__ == "__main__":
    main()
