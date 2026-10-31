import json, os, subprocess, sys
from support import JOB, isolated_guard, render as render_with
guard, CONFIG, _ = isolated_guard()


def render(text, json_escaped=False):
    return render_with(text, json_escaped, CONFIG)


MAIN = render("{{CHECKOUT}}")
SAMPLES = render("{{SAMPLES_CHECKOUT}}")
SCRATCH = render("{{SCRATCH_ROOT}}")
APP = f"{SCRATCH}/9f5c9cae-60c5-440e-a0bd-1680c1651955/scratchpad/editor-dd.noindex/Build/Products/Release/Fabric Editor.app"
cases = [
    ("git status", MAIN, None),
    ("git -C Satin log -1", MAIN, None),
    ("git status", f"{MAIN}/Satin", None),
    ("git status", SAMPLES, None),
    ("git status", "{{HOME}}/work/ai/cua", "deny"),
    ("cd {{HOME}}/work/ai/cua && git log", MAIN, "deny"),
    ("git -C {{HOME}}/work/ai/cua log", MAIN, "deny"),
    ("git --git-dir={{HOME}}/work/ai/cua/.git log", MAIN, "deny"),
    ("git --work-tree /tmp status", MAIN, "deny"),
    (f"git --work-tree {SCRATCH} status", MAIN, None),
    ("env GIT_DIR={{HOME}}/work/ai/cua/.git git log", MAIN, "deny"),
    ("git fetch origin pull/433/head:pr-433", MAIN, None),
    ("git fetch fork", MAIN, None),
    ("git fetch https://github.com/Fabric-Project/Fabric pull/1/head", MAIN, None),
    ("git fetch git@github.com:{{FORK_OWNER}}/Satin.git main", MAIN, None),
    ("git fetch https://github.com/evil/repo main", MAIN, "deny"),
    ("git fetch https://gitlab.com/Fabric-Project/Fabric main", MAIN, "deny"),
    ("git fetch {{HOME}}/work/ai/cua main", MAIN, "deny"),
    ("git fetch ../other main", MAIN, "deny"),
    ("git ls-remote ssh://git@github.com/someone/else", MAIN, "deny"),
    ("git remote add x https://github.com/evil/repo", MAIN, "deny"),
    ("git remote add samples git@github.com:Fabric-Project/Fabric-Samples.git", MAIN, None),
    ("git remote set-url fork --push=https://github.com/evil/x", MAIN, "deny"),
    ("git remote -v", MAIN, None),
    ("git clone https://github.com/Fabric-Project/Fabric x", SCRATCH, "deny"),
    ("git config remote.fork.url https://github.com/evil/x", MAIN, "deny"),
    ("git config core.sshCommand evil", MAIN, "deny"),
    ("git config --get remote.origin.url", MAIN, None),
    ("git config user.email {{COMMIT_EMAIL}}", MAIN, None),
    ("git submodule update --init", MAIN, None),
    ("gh pr view 433 -R Fabric-Project/Fabric", MAIN, None),
    ("gh pr view https://github.com/Fabric-Project/Satin/pull/67", MAIN, None),
    ("gh pr view 1 -R someone/else", MAIN, "deny"),
    ("gh pr view https://github.com/someone/else/pull/1", MAIN, "deny"),
    ("gh repo view someone/else", MAIN, "deny"),
    ("gh api repos/Fabric-Project/Fabric/pulls/433", MAIN, None),
    ("gh api repos/someone/else/contents/x", MAIN, "deny"),
    ("gh repo sync {{FORK_OWNER}}/Fabric --branch main", MAIN, None),
    (f"open --env FABRIC_JOB={JOB} \"{APP}\"", MAIN, None),
    (f"open --env FABRIC_JOB={JOB} -n \"{APP}\"", MAIN, None),
    (f"open --env FABRIC_JOB={JOB} https://example.com", MAIN, "deny"),
    (f"open --env FABRIC_JOB={JOB} -a Terminal", MAIN, "deny"),
    (f"open --env FABRIC_JOB={JOB} -b com.apple.Terminal", MAIN, "deny"),
    (f"open --env FABRIC_JOB={JOB} /System/Applications/Calculator.app", MAIN, "deny"),
    (f"open --env FABRIC_JOB={JOB} Samples", MAIN, "deny"),
    (f"open --env FABRIC_JOB={JOB} \"{APP}\" --args -x", MAIN, None),
    (f"open --env FABRIC_JOB={JOB} -e Package.swift", MAIN, "deny"),
    (f"open --env FABRIC_JOB={JOB} x-man-page://ls", MAIN, "deny"),
]
failures = 0
def run(payload, expected, label):
    global failures
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    decision = output.get("permissionDecision")
    if decision != expected or result.returncode:
        failures += 1
        print(f"FAIL {label}: expected {expected}, got {decision} {output.get('permissionDecisionReason', '')} {result.stderr.strip()}")
for command, cwd, expected in cases:
    run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd, "session_id": "abc"}, expected, command)
print(f"{len(cases)} cases, {failures} failures")
