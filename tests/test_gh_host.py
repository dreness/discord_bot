import json, os, subprocess, sys
from support import render
guard = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
MAIN = render("{{CHECKOUT}}")
cases = [
    ("gh pr view https://github.com/Fabric-Project/Fabric/pull/432", None),
    ("gh api repos/Fabric-Project/Fabric/pulls/432", None),
    ("gh api --hostname github.com repos/Fabric-Project/Fabric", None),
    ("gh auth status", None),
    ("gh auth status --hostname github.com", None),
    ("gh pr comment 21 -R {{FORK_OWNER}}/Fabric --body 'see https://developer.apple.com/documentation/metal'", None),
    ("gh api -X POST repos/{{FORK_OWNER}}/Fabric/issues/21/comments -f body=https://example.com/x", None),
    ("gh pr view https://github.pie.apple.com/Fabric-Project/Fabric/pull/1", "deny"),
    ("gh pr view 1 -R github.pie.apple.com/Fabric-Project/Fabric", "deny"),
    ("gh repo view github.pie.apple.com/Fabric-Project/Fabric", "deny"),
    ("gh api --hostname github.pie.apple.com user", "deny"),
    ("gh api --hostname=github.pie.apple.com user", "deny"),
    ("gh api https://github.pie.apple.com/api/v3/user", "deny"),
    ("gh api https://evil.example/user", "deny"),
    ("gh gist view https://gist.github.pie.apple.com/abcdef0123456789abcd", "deny"),
    ("gh auth status -t", "deny"),
    ("gh auth status --show-token", "deny"),
    ("gh auth status -ht github.com", "deny"),
    ("gh auth git-credential get", "deny"),
    ("gh auth token", "deny"),
    ("gh auth status --hostname github.pie.apple.com", "deny"),
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
