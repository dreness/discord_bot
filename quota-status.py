#!/usr/bin/env python3 -I
"""Prints the account's quota status as one line for the bot: green, yellow or red, from the 5h and 7d windows.
The bot may run this (settings.json, guard.py) but not read it."""
import importlib.util
import json
import os
import sys
import time
import urllib.request

# Remaining share at or above which a window is fine, and at or below which it is red.
THRESHOLDS = {"5h": (0.40, 0.15), "7d": (0.20, 0.05)}
STALE_SECONDS = 15 * 60
CIRCLES = {"green": "\U0001f7e2", "yellow": "\U0001f7e1", "red": "\U0001f534"}
UNAVAILABLE = "\u26aa Quota: unknown (status unavailable right now)."


def load_config():
    spec = importlib.util.spec_from_file_location("bot_config", os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.values()


def fetch(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        return json.load(response)


def discord_time(epoch):
    return f"<t:{int(epoch)}:t> (<t:{int(epoch)}:R>)"


def summarize(quota, now):
    windows = {w.get("name"): w for w in (quota or {}).get("windows") or []}
    levels, remaining, resets = {}, {}, {}
    for name, (fine, red) in THRESHOLDS.items():
        window = windows.get(name)
        if not window or not isinstance(window.get("used"), (int, float)):
            return UNAVAILABLE
        reset = window.get("reset")
        # A window whose reset has passed since the sample starts over.
        rolled = isinstance(reset, (int, float)) and reset <= now
        # Rounded so that thresholds hold exactly for the two-decimal values the headers carry.
        left = 1.0 if rolled else max(0.0, round(1.0 - window["used"], 4))
        remaining[name], resets[name] = left, None if rolled else reset
        if left <= red or (window.get("status") == "rejected" and not rolled):
            levels[name] = "red"
        elif left >= fine:
            levels[name] = "green"
        else:
            levels[name] = "yellow"
    status = "red" if "red" in levels.values() else "green" if set(levels.values()) == {"green"} else "yellow"
    five_hour = f"5h window {round(remaining['5h'] * 100)}% left"
    if levels["5h"] == "red" and levels["7d"] != "red" and resets["5h"]:
        five_hour += f", resets {discord_time(resets['5h'])}"
    line = f"{CIRCLES[status]} Quota: {status}. {five_hour}; 7d window {round(remaining['7d'] * 100)}% left."
    age = now - quota["ts"] if isinstance(quota.get("ts"), (int, float)) else None
    if age is not None and age > STALE_SECONDS:
        line += f" (as of {int(age // 60)} min ago)"
    return line


def main():
    try:
        quota = fetch(load_config()["QUOTA_URL"])
    except Exception:
        print(UNAVAILABLE)
        return
    print(summarize(quota, time.time()))


if __name__ == "__main__":
    main()
