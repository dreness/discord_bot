#!/usr/bin/env python3 -I
"""Restarts the bot in a fresh session: kills the tmux session `bot`, waits for the Discord plugin server to exit,
then starts the LaunchAgent local.discord-bot again.

<job id> (the bot's `clear`, the job id of the clear request itself): refuses while processes tagged with another
requester's job are running (jobs.py). Otherwise detaches, waits until the session's transcript has been quiet for a few
seconds so the current turn can finish, checks again, then restarts. Log: ~/Library/Logs/discord-bot-restart.log.
--now (the operator, over ssh): restarts right away and reports on stdout/stderr."""
import glob, importlib.util, os, re, subprocess, sys, time

TMUX = "/opt/homebrew/bin/tmux"
HOME = os.path.expanduser("~")
LOG = os.path.join(HOME, "Library/Logs/discord-bot-restart.log")
LAUNCH_LOG = os.path.join(HOME, "Library/Logs/discord-bot-launch.log")
PLUGIN_SERVER = r"bun run --cwd .*/discord/[^ ]+ .*start$"
SESSION = r"claude --settings .*discord_bot/rendered/settings.json"
QUIET_SECONDS = 5
MAXIMUM_WAIT_SECONDS = 120
CLEAR_REQUEST_MAXIMUM_AGE = 600
CLEAR_WORD = re.compile(r"\bclear\b", re.IGNORECASE)


def running(pattern):
    return subprocess.run(["/usr/bin/pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()


def wait(condition, seconds):
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)
    return True


def load(name):
    spec = importlib.util.spec_from_file_location(f"bot_{name}", os.path.join(os.path.dirname(os.path.realpath(__file__)), f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clear_refusal(job_id, jobs_module, ledger, now, tagged=None):
    """Why this clear may not go ahead, or None."""
    jobs = ledger.jobs()
    request = jobs.get(job_id)
    if not request or not CLEAR_WORD.search(request.get("text") or "") or now - request.get("time", 0) > CLEAR_REQUEST_MAXIMUM_AGE:
        return f"not clearing: {job_id} isn't a clear request logged in the last {CLEAR_REQUEST_MAXIMUM_AGE // 60} minutes; pass the job id jobs.py start gave this clear message"
    blocking = jobs_module.blocking_jobs(request.get("user_id"), jobs_module.running_jobs(tagged), jobs)
    if blocking:
        return "not clearing: another requester's work is running; they can clear once it's done, or the operator can restart:\n" + "\n".join(jobs_module.describe_running(blocking, jobs))
    return None


def newest_transcript_age():
    transcripts = glob.glob(os.path.join(load("config").values()["TRANSCRIPT_DIRECTORY"], "*.jsonl"))
    return time.time() - max(map(os.path.getmtime, transcripts)) if transcripts else float("inf")


def restart():
    subprocess.run([TMUX, "kill-session", "-t", "bot"], capture_output=True)
    if not wait(lambda: not running(PLUGIN_SERVER), 15):
        sys.exit(f"Discord plugin server still running 15 s after the session ended: {' '.join(running(PLUGIN_SERVER))}")
    subprocess.run(["/bin/launchctl", "kickstart", f"gui/{os.getuid()}/local.discord-bot"], check=True)
    if not wait(lambda: running(PLUGIN_SERVER), 30):
        tail = subprocess.run(["/usr/bin/tail", "-20", LAUNCH_LOG], capture_output=True, text=True).stdout
        pane = subprocess.run([TMUX, "capture-pane", "-p", "-t", "bot"], capture_output=True, text=True).stdout
        sys.exit(f"no Discord plugin server 30 s after launch\nlaunch log:\n{tail}\npane:\n{pane[-2000:]}")
    print(f"bot restarted, session pid {' '.join(running(SESSION)) or '?'}")


def detach(job_id):
    jobs_module = load("jobs")
    ledger = jobs_module.ledger_from(load("config").values())
    requested = time.time()
    refusal = clear_refusal(job_id, jobs_module, ledger, requested)
    if refusal:
        sys.exit(refusal)
    # Own session and no inherited fds: survives the tmux session's end and doesn't hold run.sh's bot.lock (fd 9).
    if os.fork():
        print(f"restarting in a fresh session once this turn ends; log {LOG}")
        return
    os.setsid()
    if os.fork():
        os._exit(0)
    log = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.dup2(log, 1)
    os.dup2(log, 2)
    os.closerange(3, os.sysconf("SC_OPEN_MAX"))
    sys.stdout = os.fdopen(1, "w", buffering=1)
    sys.stderr = os.fdopen(2, "w", buffering=1)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "clear requested by job", job_id)
    wait(lambda: newest_transcript_age() >= QUIET_SECONDS, MAXIMUM_WAIT_SECONDS)
    refusal = clear_refusal(job_id, jobs_module, ledger, requested)
    if refusal:
        print(refusal, file=sys.stderr)
        os._exit(1)
    try:
        restart()
    except SystemExit as error:
        print(error, file=sys.stderr)
        os._exit(1)
    os._exit(0)


if __name__ == "__main__":
    if sys.argv[1:] == ["--now"]:
        restart()
    elif len(sys.argv) == 2 and re.fullmatch(r"[0-9]{6}-[0-9a-f]{6}", sys.argv[1]):
        detach(sys.argv[1])
    else:
        sys.exit("usage: session-restart.py --now | <job id of the clear request>")
