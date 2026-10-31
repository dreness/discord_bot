import json, os, subprocess, sys
from support import render
guard = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
MAIN = render("{{CHECKOUT}}")
cases = [
    ("gh pr view 433 -R Fabric-Project/Fabric", None),
    ("git push fork review/x", None),
    ("env", None),
    ("GH_CONFIG_DIR={{HOME}}/x gh pr view 1 -R Fabric-Project/Fabric", "deny"),
    ("env GH_TOKEN=x gh api user", "deny"),
    ("unset GH_CONFIG_DIR; gh pr list -R Fabric-Project/Fabric", "deny"),
    ("export GITHUB_TOKEN=x && gh pr list -R Fabric-Project/Fabric", "deny"),
    ("env -i PATH=/usr/bin gh pr list -R Fabric-Project/Fabric", "deny"),
    ("env -u GH_CONFIG_DIR gh pr list", "deny"),
    ("env -u XDG_X gh pr list", "deny"),
    ("XDG_CONFIG_HOME=/tmp gh pr list", "deny"),
    ("GIT_CONFIG_COUNT=0 git push fork x", "deny"),
    ("unset GIT_CONFIG_COUNT && git push fork x", "deny"),
    ("printenv GH_CONFIG_DIR", "deny"),
    ("cat ~/.config/gh-fabric-bot/hosts.yml", "deny"),
]
failures = 0
for command, expected in cases:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": MAIN, "session_id": "abc"}
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    if output.get("permissionDecision") != expected or result.returncode:
        failures += 1
        print(f"FAIL {command[:110]}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()}")
print(f"{len(cases)} cases, {failures} failures")
