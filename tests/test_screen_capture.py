import json, os, shutil, subprocess, sys, tempfile
from support import isolated_guard, render as render_with
guard, CONFIG, _ = isolated_guard()


def render(text, json_escaped=False):
    return render_with(text, json_escaped, CONFIG)


MAIN = render("{{CHECKOUT}}")
JOBS = CONFIG["BUILD_JOBS"]
NODE = f"{MAIN}/Fabric/Nodes/Image/ScreenCaptureProviderNode.swift"
TASK = render("{{TASK_ROOT}}/ui")
fixtures = tempfile.mkdtemp(dir=render("{{SCRATCH_ROOT}}"))
def fixture(name, text):
    path = os.path.join(fixtures, name)
    with open(path, "w") as handle:
        handle.write(text)
    return path
grab_script = fixture("grab.py", "import Quartz\nQuartz.CGWindowListCreateImage(Quartz.CGRectInfinite, 1, 0, 0)\n")
capture_composition = fixture("capture.fabric", '{"nodes":[{"class":"ScreenCaptureProviderNode"}]}')
# The VM's desktop is the bot's: capture code runs freely, and the CLI writes only into scratch.
bash_cases = [
    (f"screencapture -x {TASK}/shot.png", None),
    (f"screencapture -x -l 123 -t png {TASK}/window.png", None),
    (f"screencapture -x -R 0,0,100,100 {TASK}/a.png {TASK}/b.png", None),
    (f"cd {TASK} && screencapture -x shot.png", None),
    ("screencapture -x shot.png", "deny"),
    (f"screencapture -x {MAIN}/Sources/shot.png", "deny"),
    ("screencapture -x /Users/Shared/shot.png", "deny"),
    (f"screencapture -x {TASK}/../../../../../Users/Shared/shot.png", "deny"),
    ("screencapture -x", "deny"),
    ("screencapture -c", "deny"),
    (f"screencapture -i {TASK}/shot.png", "deny"),
    (f"screencapture -v {TASK}/movie.mov", "deny"),
    (f"screencapture -P {TASK}/shot.png", "deny"),
    (f"screencapture -B com.apple.Preview {TASK}/shot.png", "deny"),
    (f"/usr/sbin/screencapture -x {TASK}/shot.png", None),
    ("python3 -c 'from PIL import ImageGrab; ImageGrab.grab()'", None),
    ("swift -e 'import ScreenCaptureKit'", None),
    (f"python3 {grab_script}", None),
    (f"swift test -j {JOBS} --filter ScreenCaptureProviderNodeTests", None),
    ("grep -rn ScreenCaptureKit Fabric/Nodes", None),
    (f"cat {NODE}", None),
]
file_cases = [
    ("Write", {"file_path": fixture("new.swift", ""), "content": "import ScreenCaptureKit\n"}, None),
    ("Edit", {"file_path": NODE, "old_string": "x", "new_string": "let filter = SCContentFilter()"}, None),
    ("Write", {"file_path": os.path.join(fixtures, "grab.sh"), "content": "screencapture -x a.png\n"}, None),
]
failures = 0
def run(payload, expected, label):
    global failures
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    if output.get("permissionDecision") != expected or result.returncode:
        failures += 1
        print(f"FAIL {label[:100]}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()}")
os.makedirs(TASK, exist_ok=True)
for command, expected in bash_cases:
    run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": MAIN, "session_id": "abc"}, expected, command)
for tool, tool_input, expected in file_cases:
    run({"tool_name": tool, "tool_input": tool_input, "cwd": MAIN, "session_id": "abc"}, expected, f"{tool} {tool_input}")
shutil.rmtree(fixtures)
print(f"{len(bash_cases) + len(file_cases)} cases, {failures} failures")
