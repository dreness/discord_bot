#!/usr/bin/env python3 -I
"""Discord requesters' preferences, kept on the Cua Volume so they outlive sessions and VM resets.
  preferences.py get <discord user id>
  preferences.py set <discord user id> [frequency=updates|quiet] [verbosity=brief|detailed] [style=default|adhd]   (at least one)
  preferences.py session-start   (SessionStart hook: the rulesets for every requester with a non-default style; never fails)
With style=adhd, get also prints the reply-style ruleset, scoped to that requester.
The bot may run these (settings.json, guard.py) but not read this file or reach the volume otherwise."""
import importlib.util
import json
import os
import re
import sys
import time

CHOICES = {"frequency": ("updates", "quiet"), "verbosity": ("brief", "detailed"), "style": ("default", "adhd")}
DEFAULTS = {"frequency": "updates", "verbosity": "brief", "style": "default"}
USER_ID = re.compile(r"[0-9]{15,21}")
USAGE = "usage: preferences.py get <user id> | set <user id> frequency=updates|quiet verbosity=brief|detailed style=default|adhd"
STYLE_FILES = {"adhd": os.path.join(os.path.dirname(os.path.realpath(__file__)), "styles", "i-have-adhd", "SKILL.md")}


def load_config():
    spec = importlib.util.spec_from_file_location("bot_config", os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.values()


def effective(entry):
    """Stored values the current CHOICES accept; anything else (a disabled feature, a hand edit) reads as the default and stays stored."""
    return {key: entry.get(key) if entry.get(key) in CHOICES[key] else DEFAULTS[key] for key in CHOICES}


def describe(preferences):
    return " ".join(f"{key}={value}" for key, value in effective(preferences).items())


def style_rules(users, style):
    """The ruleset for a non-default style, without its frontmatter and its session-wide Persistence section."""
    with open(STYLE_FILES[style]) as handle:
        text = handle.read()
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"^## Persistence\n.*?(?=^## )", "", text, flags=re.S | re.M).strip()
    return (f"Reply style {style} for requesters with user_id {', '.join(users)}: the rules below shape every reply to them and to no one else; "
            f"replies to anyone else keep your default style. The style comes from the open-source i-have-adhd plugin; choosing it says nothing "
            f"about the requester, so never refer to them as having ADHD. They hold while the choice is saved; "
            f"\"stop adhd mode\" or \"normal mode\" from one of them means `set <their user_id> style=default`.\n\n{text}")


def with_style(line, user, preferences):
    style = effective(preferences)["style"]
    return line if style not in STYLE_FILES else f"{line}\n\n{style_rules([user], style)}"


def session_start(path, volume):
    """Context for a new or compacted session; empty when nobody has a non-default style or the store is unavailable."""
    try:
        if not os.path.ismount(volume):
            return ""
        data = read(path)
        users = {}
        for user, entry in sorted(data.items()):
            style = entry.get("style") if isinstance(entry, dict) and USER_ID.fullmatch(user) else None
            if style in STYLE_FILES and style in CHOICES["style"]:
                users.setdefault(style, []).append(user)
        return "\n\n".join(style_rules(ids, style) for style, ids in sorted(users.items()))
    except (OSError, ValueError):
        return ""


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
        unchosen = "" if entry.get("style") in CHOICES["style"] else "; style not chosen"
        updated = entry.get("updated") if isinstance(entry.get("updated"), int) else 0
        return with_style(f"{describe(entry)} (saved {time.strftime('%Y-%m-%d', time.localtime(updated))}{unchosen})", user, entry), 0
    # Keys and values this version doesn't know are kept, so a feature disabled and later re-enabled finds its choices.
    entry = dict(entry or {})
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
    if sys.argv[1:] == ["session-start"]:
        text = session_start(config["PREFERENCES_FILE"], config["CUA_VOLUME"])
        if text:
            print(text)
        return
    line, status = run(sys.argv[1:], config["PREFERENCES_FILE"], config["CUA_VOLUME"], time.time())
    print(line)
    sys.exit(status)


if __name__ == "__main__":
    main()
