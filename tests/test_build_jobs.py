import json, os, subprocess, sys
from support import TAG, isolated_guard, render as render_with
guard, CONFIG, _ = isolated_guard()


def render(text, json_escaped=False):
    return render_with(text, json_escaped, CONFIG)


MAIN = render("{{CHECKOUT}}")
JOBS = int(CONFIG["BUILD_JOBS"])
cases = [
    (f"{TAG}swift build --scratch-path .build.noindex", "deny"),
    (f"{TAG}swift build -j {JOBS} --scratch-path .build.noindex", None),
    (f"{TAG}swift build -j{JOBS} --scratch-path .build.noindex", None),
    (f"{TAG}swift build --jobs=1 --scratch-path .build.noindex", None),
    (f"{TAG}swift build --jobs {JOBS + 1} --scratch-path .build.noindex", "deny"),
    (f"{TAG}swift build -j 0", "deny"),
    (f"{TAG}swift test -c release -Xswiftc -enable-testing --scratch-path .build.noindex --filter GraphTests", "deny"),
    (f"{TAG}swift test -c release -j {JOBS} -Xswiftc -enable-testing --scratch-path .build.noindex --filter GraphTests", None),
    (f"cd Satin && {TAG}swift test -j {JOBS + 1}", "deny"),
    (f"env FABRIC_TREE=pr swift test -j {JOBS} --filter X", None),
    (f"{TAG}swift run -j {JOBS} tool", None),
    ("swift package resolve", None),
    ("swift --version", None),
    (f"{TAG}swift build --help", None),
    (f'{TAG}xcodebuild -project Fabric.xcodeproj -scheme "Fabric Editor" -derivedDataPath x.noindex build', "deny"),
    (f'{TAG}xcodebuild -project Fabric.xcodeproj -scheme "Fabric Editor" -derivedDataPath x.noindex -jobs {JOBS} build', None),
    (f'{TAG}xcodebuild -scheme Fabric -jobs {JOBS + 2} test', "deny"),
    (f"{TAG}xcodebuild -list -project Fabric.xcodeproj", None),
    (f"{TAG}xcodebuild -showBuildSettings -scheme Fabric", None),
    (f"{TAG}xcodebuild -version", None),
    (f"swift build -j {JOBS} --scratch-path .build.noindex", "deny"),
    (f"env FABRIC_TREE=pr swift test -j {JOBS} --filter X", "deny"),
    (f"env FABRIC_JOB=261031-ffffff swift build -j {JOBS}", "deny"),
    (f"env FABRIC_JOB=nope swift build -j {JOBS}", "deny"),
    (f'xcodebuild -scheme Fabric -jobs {JOBS} build', "deny"),
    ("swift package describe", None),
]
failures = 0
for command, expected in cases:
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": MAIN, "session_id": "abc"}), json_escaped=True), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    if output.get("permissionDecision") != expected or result.returncode:
        failures += 1
        print(f"FAIL {command}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()}")
print(f"{len(cases)} cases, {failures} failures")
