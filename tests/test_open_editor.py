import json, subprocess, sys
from support import JOB, isolated_guard, render as render_with
guard, CONFIG, _ = isolated_guard()


def render(text, json_escaped=False):
    return render_with(text, json_escaped, CONFIG)


MAIN = render("{{CHECKOUT}}")
JOBS = CONFIG["BUILD_JOBS"]
APP = render("{{SCRATCH_ROOT}}/x/editor-dd.noindex/Build/Products/Release/Fabric Editor.app")
# Session abc holds the Editor lock; other doesn't.
cases = [
    (f'open --env FABRIC_JOB={JOB} "{APP}"', "abc", None),
    (f'open --env FABRIC_JOB={JOB} -n -W "{APP}" --args -NSDocumentRevisionsDebugMode YES', "abc", None),
    (f'open --env FABRIC_JOB={JOB} -a "{APP}" Samples/cube.fabric', "abc", None),
    (f'open --env FABRIC_JOB={JOB} -a "{APP}"', "abc", None),
    (f"open --env FABRIC_JOB={JOB} Samples/cube.fabric", "abc", None),
    (f"open --env FABRIC_JOB={JOB} {render('{{CHECKOUT}}')}-pr414/Samples/x.fabric", "abc", None),
    (f'"{APP}/Contents/MacOS/Fabric Editor" &', "abc", None),
    (f'open --env FABRIC_JOB={JOB} "{APP}"', "other", "deny"),
    (f"open --env FABRIC_JOB={JOB} Samples/cube.fabric", "other", "deny"),
    (f'"{APP}/Contents/MacOS/Fabric Editor"', "other", "deny"),
    (f"open --env FABRIC_JOB={JOB} https://example.com", "abc", "deny"),
    (f"open --env FABRIC_JOB={JOB} -a Terminal", "abc", "deny"),
    ("/usr/bin/open -a Terminal", "abc", "deny"),
    (f"open --env FABRIC_JOB={JOB} -b com.apple.Terminal", "abc", "deny"),
    (f"open --env FABRIC_JOB={JOB} /System/Applications/Utilities/Terminal.app", "abc", "deny"),
    (f'open --env FABRIC_JOB={JOB} "/Applications/Fabric Editor.app"', "abc", "deny"),
    (f"open --env FABRIC_JOB={JOB} x.command", "abc", "deny"),
    (f"open --env FABRIC_JOB={JOB} Samples", "abc", "deny"),
    (f"open --env FABRIC_JOB={JOB} /etc/x.fabric", "abc", "deny"),
    (f"open --env FABRIC_JOB={JOB} -R Samples/cube.fabric", "abc", "deny"),
    ("open", "abc", "deny"),
    (f'xcodebuild -project Fabric.xcodeproj -scheme "Fabric Editor" -derivedDataPath x.noindex -jobs {JOBS} test', "other", None),
    (f'xcodebuild -project Fabric.xcodeproj -scheme "Fabric Editor" -configuration Release -derivedDataPath x.noindex -jobs {JOBS} build', "other", None),
    (f'codesign -dv "{APP}/Contents/MacOS/Fabric Editor"', "other", None),
    (f'otool -L "{APP}/Contents/MacOS/Fabric Editor"', "other", None),
    ("pgrep -x 'Fabric Editor'", "other", None),
]
failures = 0
for command, session, expected in cases:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": MAIN, "session_id": session}
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    if output.get("permissionDecision") != expected or result.returncode:
        failures += 1
        print(f"FAIL {command[:100]} ({session}): expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()}")
print(f"{len(cases)} cases, {failures} failures")
