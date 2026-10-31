import json, os, subprocess, sys
from support import render
guard = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
cases = [
    ('gh pr create --base review/x-base --head feature/x --title t --body b', "deny"),
    ('gh pr create -R Fabric-Project/Fabric --base main --head feature/x', "deny"),
    ('gh pr create --repo=Fabric-Project/Satin --fill', "deny"),
    ('gh pr create -RFabric-Project/Satin --fill', "deny"),
    ('gh -R Fabric-Project/Fabric pr create --fill', "deny"),
    ('GH_REPO=Fabric-Project/Fabric gh pr create --fill', "deny"),
    ('gh pr edit 443 --add-label x', "deny"),
    ('gh pr edit https://github.com/Fabric-Project/Fabric/pull/443 -R {{FORK_OWNER}}/Fabric --title t', "deny"),
    ('gh pr ready 443', "deny"),
    ('cd /tmp && gh pr create -R fabric-project/fabric --fill', "deny"),
    ('gh pr create -R {{FORK_OWNER}}/Satin --base review/x-base --head feature/x --title "Review mirror" --body "mirror of https://github.com/Fabric-Project/Satin/pull/68, not for merge"', None),
    ('gh pr create --repo {{FORK_OWNER}}/Fabric --fill', None),
    ('gh pr create -R github.com/Dreness/Fabric --fill', None),
    ('gh pr edit 19 -R {{FORK_OWNER}}/Fabric --body x', None),
    ('gh pr edit https://github.com/{{FORK_OWNER}}/Fabric/pull/19 -R {{FORK_OWNER}}/Fabric --title t', None),
    ('gh pr view 443 -R Fabric-Project/Fabric', None),
    ('gh pr diff 68 -R Fabric-Project/Satin', None),
    ('gh pr list', None),
    ('gh pr merge 19 -R {{FORK_OWNER}}/Fabric', "deny"),
    ('git push -f fork x', "deny"),
    ('git -C Satin log --oneline -1', None),
]
failures = 0
for command, expected in cases:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "s"}
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    decision = output.get("permissionDecision")
    status = "ok  " if decision == expected and not result.stderr else "FAIL"
    failures += status == "FAIL"
    print(status, command[:80], "->", decision, output.get("permissionDecisionReason", "")[16:90], result.stderr[-200:])
print("failures:", failures)
