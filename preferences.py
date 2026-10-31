#!/usr/bin/env python3 -I
"""Discord requesters' status-update preferences, kept on the Cua Volume so they outlive sessions and VM resets.
  preferences.py get <discord user id>
  preferences.py set <discord user id> frequency=updates|quiet [verbosity=brief|detailed]   (either or both)
The bot may run these (settings.json, guard.py) but not read this file or reach the volume otherwise."""
import importlib.util
import json
import os
import re
import sys
import time

CHOICES = {"frequency": ("updates", "quiet"), "verbosity": ("brief", "detailed")}
DEFAULTS = {"frequency": "updates", "verbosity": "brief"}
USER_ID = re.compile(r"[0-9]{15,21}")
USAGE = "usage: preferences.py get <user id> | set <user id> frequency=updates|quiet verbosity=brief|detailed"


def load_config():
    spec = importlib.util.spec_from_file_location("bot_config", os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.values()


def describe(preferences):
    return " ".join(f"{key}={preferences.get(key, DEFAULTS[key])}" for key in CHOICES)


def read(path):
    try:
        with open(path) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def parse_settings(arguments):
    settings = {}
    for argument in arguments:
        key, _, value = argument.partition("=")
        if key not in CHOICES or value not in CHOICES[key] or key in settings:
            return None
        settings[key] = value
    return settings or None


def run(arguments, path, volume, now):
    """Returns (line, exit status)."""
    if len(arguments) < 2 or arguments[0] not in ("get", "set") or not USER_ID.fullmatch(arguments[1]):
        return USAGE, 2
    command, user = arguments[0], arguments[1]
    settings = parse_settings(arguments[2:]) if command == "set" else {}
    if settings is None or (command == "get" and len(arguments) != 2):
        return USAGE, 2
    if not os.path.ismount(volume):
        detail = "storage unavailable (Cua Volume not mounted)"
        return (f"{describe({})} (defaults; {detail})" if command == "get" else f"not saved: {detail}"), (0 if command == "get" else 1)
    try:
        data = read(path)
    except (OSError, ValueError) as error:
        return f"{describe({})} (defaults; preferences file unreadable: {error})", 1
    entry = data.get(user) if isinstance(data.get(user), dict) else None
    if command == "get":
        if not entry:
            return f"{describe({})} (defaults; nothing saved)", 0
        return f"{describe(entry)} (saved {time.strftime('%Y-%m-%d', time.localtime(entry.get('updated', 0)))})", 0
    entry = {key: value for key, value in (entry or {}).items() if key in CHOICES}
    entry.update(settings, updated=int(now))
    data[user] = entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    return f"saved: {describe(entry)}", 0


def main():
    config = load_config()
    line, status = run(sys.argv[1:], config["PREFERENCES_FILE"], config["CUA_VOLUME"], time.time())
    print(line)
    sys.exit(status)


if __name__ == "__main__":
    main()
