import json, os, subprocess, sys
from support import render
guard = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
MAIN = render("{{CHECKOUT}}")
SCRATCH = render("{{TASK_ROOT}}/keychain-test")
os.makedirs(SCRATCH, exist_ok=True)
with open(os.path.join(SCRATCH, "steal.py"), "w") as handle:
    handle.write('import subprocess\nsubprocess.run(["security", "find-generic-password", "-s", "gh:github.com", "-w"])\n')
with open(os.path.join(SCRATCH, "plain.py"), "w") as handle:
    handle.write('print("hello")\n')
cases = [
    ("security list-keychains", "deny"),
    ("/usr/bin/security find-generic-password -s gh:github.com -w", "deny"),
    ("echo hi; security dump-keychain", "deny"),
    ("xcrun security list-keychains", "deny"),
    ("python3 -c \"print(open('{{HOME}}/Library/Keychains/login.keychain-db','rb').read(4))\"", "deny"),
    ("ls ~/Library/Keychains", "deny"),
    # Code isn't scanned for keychain access: the VM holds no operator credentials.
    ('bash -c "security list-keychains"', None),
    ("""python3 -c "import subprocess; subprocess.run(['security','list-keychains'])" """, None),
    ("""swift -e 'import Security; SecItemCopyMatching(nil, nil)'""", None),
    ("cat ~/.claude/.credentials.json", "deny"),
    ("cat ~/.claude/.cred*", "deny"),
    ("cd ~/.claude && cat .credentials.json", "deny"),
    ("python3 -c \"print(open('{{HOME}}/.claude/.credentials.json').read())\"", "deny"),
    (f"python3 {SCRATCH}/steal.py", None),
    (f"cd {SCRATCH} && python3 steal.py", None),
    (f"python3 {SCRATCH}/plain.py", None),
    ('bash -c "swift package describe"', None),
    ("python3 -c \"print('finished the security review')\"", None),
    ("grep -rn security Sources", None),
    ("rm ~/.swiftpm/security/fingerprints/x", None),
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
