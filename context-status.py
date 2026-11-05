#!/usr/bin/env python3 -I
"""The bot session's context window use, from Claude Code's own status line data; no API calls.
  context-status.py              one line for the bot: tokens in context, window size, percent used
  context-status.py statusline   statusLine command: saves its stdin JSON per session under CONTEXT_DIRECTORY, prints a short line for the pane
The bot may run the first form (settings.json, guard.py) but not read this file."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

SESSION_ID = re.compile(r"[0-9a-f-]{36}")
KEEP_SECONDS = 7 * 86400
UNAVAILABLE = "Context: unknown (no status line data for this session yet)."


def load_config():
    spec = importlib.util.spec_from_file_location("bot_config", os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.values()


def tokens(count):
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    return f"{round(count / 1000)}k"


def summarize(data):
    window = data.get("context_window") if isinstance(data, dict) else None
    if not isinstance(window, dict) or not isinstance(window.get("context_window_size"), int):
        return UNAVAILABLE
    size = window["context_window_size"]
    usage = window.get("current_usage")
    if not isinstance(usage, dict):
        return f"Context: nothing used yet ({tokens(size)} window)."
    used = sum(usage.get(key) or 0 for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    percent = window.get("used_percentage")
    percent = round(percent) if isinstance(percent, (int, float)) else round(used * 100 / size)
    return f"Context: {tokens(used)} of {tokens(size)} tokens ({percent}%)."


def ancestors(pid):
    seen = []
    while pid > 1 and pid not in seen:
        seen.append(pid)
        result = subprocess.run(["/bin/ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True)
        try:
            pid = int(result.stdout.strip())
        except ValueError:
            break
    return seen


def own_session(registry, pids):
    """The session id of the nearest ancestor registered in Claude Code's session registry."""
    for pid in pids:
        try:
            with open(os.path.join(registry, f"{pid}.json")) as handle:
                session = json.load(handle).get("sessionId")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(session, str) and SESSION_ID.fullmatch(session):
            return session
    return None


def report(directory, session):
    if not session:
        return UNAVAILABLE
    try:
        with open(os.path.join(directory, f"{session}.json")) as handle:
            return summarize(json.load(handle))
    except (OSError, ValueError):
        return UNAVAILABLE


def save(directory, data, now):
    """Saves the status line input for its session and prunes old sessions' files; returns the pane line."""
    session = data.get("session_id") if isinstance(data, dict) else None
    if isinstance(session, str) and SESSION_ID.fullmatch(session):
        os.makedirs(directory, exist_ok=True)
        temporary = os.path.join(directory, f".{session}.{os.getpid()}.tmp")
        with open(temporary, "w") as handle:
            json.dump({"context_window": data.get("context_window"), "model": data.get("model")}, handle)
        os.replace(temporary, os.path.join(directory, f"{session}.json"))
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if now - os.path.getmtime(path) > KEEP_SECONDS:
                os.remove(path)
    return summarize(data)


def main():
    config = load_config()
    if sys.argv[1:] == ["statusline"]:
        try:
            print(save(config["CONTEXT_DIRECTORY"], json.load(sys.stdin), time.time()))
        except Exception:
            print(UNAVAILABLE)
        return
    if sys.argv[1:]:
        sys.exit(__doc__)
    print(report(config["CONTEXT_DIRECTORY"], own_session(config["SESSION_REGISTRY"], ancestors(os.getppid()))))


if __name__ == "__main__":
    main()
