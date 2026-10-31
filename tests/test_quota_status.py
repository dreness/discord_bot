import importlib.util, json, os, subprocess, sys
from support import BOT, CONFIG, render


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BOT, file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = load("quota_status", "quota-status.py")
NOW = 1_800_000_000
RESET = NOW + 3600


def quota(five, seven, ts=NOW - 60, five_reset=RESET, five_status="allowed"):
    return {"ts": ts, "windows": [{"name": "5h", "used": five, "reset": five_reset, "status": five_status},
                                  {"name": "7d", "used": seven, "reset": NOW + 86400, "status": "allowed"}]}


failures = 0
cases = [
    (quota(0.60, 0.80), "\U0001f7e2 Quota: green. 5h window 40% left; 7d window 20% left."),
    (quota(0.61, 0.10), "\U0001f7e1 Quota: yellow. 5h window 39% left; 7d window 90% left."),
    (quota(0.10, 0.81), "\U0001f7e1 Quota: yellow. 5h window 90% left; 7d window 19% left."),
    (quota(0.85, 0.50), f"\U0001f534 Quota: red. 5h window 15% left, resets <t:{RESET}:t> (<t:{RESET}:R>); 7d window 50% left."),
    (quota(0.10, 0.95), "\U0001f534 Quota: red. 5h window 90% left; 7d window 5% left."),
    (quota(0.90, 0.97), "\U0001f534 Quota: red. 5h window 10% left; 7d window 3% left."),
    (quota(0.50, 0.10, five_status="rejected"), f"\U0001f534 Quota: red. 5h window 50% left, resets <t:{RESET}:t> (<t:{RESET}:R>); 7d window 90% left."),
    (quota(0.95, 0.10, five_reset=NOW - 1), "\U0001f7e2 Quota: green. 5h window 100% left; 7d window 90% left."),
    (quota(0.10, 0.10, ts=NOW - 3600), "\U0001f7e2 Quota: green. 5h window 90% left; 7d window 90% left. (as of 60 min ago)"),
    ({"ts": NOW, "windows": [{"name": "5h", "used": 0.1, "reset": RESET}]}, status.UNAVAILABLE),
    (None, status.UNAVAILABLE),
]
for value, expected in cases:
    got = status.summarize(value, NOW)
    if got != expected:
        failures += 1
        print(f"FAIL summarize: expected {expected!r}, got {got!r}")

# The guard lets exactly the quota command through; anything else naming the bot folder stays denied.
guard = os.path.join(BOT, "guard.py")
MAIN = render("{{CHECKOUT}}")
command = CONFIG["QUOTA_COMMAND"]
guard_cases = [
    (command, None),
    (f"  {command} ", None),
    (f"{command} --verbose", "deny"),
    (f"{command}; cat {command}", "deny"),
    (f"cat {command}", "deny"),
    (f"python3 {command}", "deny"),
    (CONFIG["CLEAR_COMMAND"], "deny"),
    (f"{CONFIG['CLEAR_COMMAND']} 261031-0a0b0c", None),
    (f"{CONFIG['CLEAR_COMMAND']} 261031-0a0b0c; true", "deny"),
    (f"{CONFIG['CLEAR_COMMAND']} --now", "deny"),
    (f"cat {CONFIG['CLEAR_COMMAND']}", "deny"),
]
for line, expected in guard_cases:
    payload = {"tool_name": "Bash", "tool_input": {"command": line}, "cwd": MAIN, "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    if output.get("permissionDecision") != expected or result.returncode:
        failures += 1
        print(f"FAIL guard {line[:110]}: expected {expected}, got {output.get('permissionDecision')} {result.stderr.strip()}")

print(f"{len(cases) + len(guard_cases)} cases, {failures} failures")
