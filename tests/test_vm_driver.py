import json, os, subprocess, sys
from support import BOT, isolated_guard, render as render_with
guard, CONFIG, _ = isolated_guard()


def render(text, json_escaped=False):
    return render_with(text, json_escaped, CONFIG)


MAIN = render("{{CHECKOUT}}")
TASK = render("{{TASK_ROOT}}/ui")
APP = f"{TASK}/editor-dd.noindex/Build/Products/Release/Fabric Editor.app"
# A stand-in Editor: python under the Editor's executable path.
os.makedirs(f"{APP}/Contents/MacOS")
os.symlink(os.path.realpath(sys.executable), f"{APP}/Contents/MacOS/Fabric Editor")
editor = subprocess.Popen([f"{APP}/Contents/MacOS/Fabric Editor", "-c", "import time; time.sleep(60)"])
EDITOR, OTHER = editor.pid, os.getpid()
D = "mcp__vm-driver__"
cases = [
    (D + "list_windows", {}, None),
    (D + "list_windows", {"pid": EDITOR}, None),
    (D + "list_apps", {}, None),
    (D + "get_guide", {"topic": "menus"}, None),
    (D + "get_window_state", {"pid": EDITOR, "window_id": 7, "timeout_ms": 5000}, None),
    (D + "get_window_state", {"pid": EDITOR, "window_id": 7, "screenshot_out_file": f"{TASK}/shot.png"}, None),
    (D + "get_window_state", {"pid": EDITOR, "window_id": 7, "screenshot_out_file": f"{MAIN}/Sources/shot.png"}, None),
    (D + "get_window_state", {"pid": EDITOR, "window_id": 7, "screenshot_out_file": "/Users/Shared/shot.png"}, "deny"),
    (D + "get_window_state", {"pid": EDITOR, "window_id": 7, "screenshot_out_file": "{{HOME}}/.zshrc"}, "deny"),
    (D + "get_window_state", {"pid": OTHER, "window_id": 7}, "deny"),
    (D + "get_window_state", {"window_id": 7}, "deny"),
    (D + "verify_state", {"pid": OTHER, "window_id": 7, "expect": [{"window": {"exists": True}}]}, "deny"),
    (D + "get_desktop_state", {"screenshot_out_file": f"{TASK}/desktop.png"}, None),
    (D + "zoom", {"window_id": 7, "x1": 0, "y1": 0, "x2": 10, "y2": 10}, None),
    (D + "click", {"pid": EDITOR, "window_id": 7, "x": 10, "y": 20}, None),
    (D + "click", {"element_token": "abc:3"}, None),
    (D + "click", {"pid": OTHER, "window_id": 7, "x": 10, "y": 20}, "deny"),
    (D + "click", {"pid": 1, "x": 1, "y": 1}, "deny"),
    (D + "click", {"pid": True, "x": 1, "y": 1}, "deny"),
    (D + "click", {"x": 10, "y": 20}, "deny"),
    (D + "click", {"scope": "desktop", "pid": EDITOR, "x": 10, "y": 20}, "deny"),
    (D + "click", {"target": {"kind": "desktop", "display_id": "primary"}, "x": 1, "y": 1}, "deny"),
    (D + "click", {"target": {"kind": "window", "pid": EDITOR, "window_id": 7}, "x": 1, "y": 1}, None),
    (D + "click", {"target": {"kind": "window", "pid": OTHER, "window_id": 7}, "x": 1, "y": 1}, "deny"),
    (D + "type_text", {"pid": EDITOR, "window_id": 7, "text": "1.5"}, None),
    (D + "hotkey", {"keys": ["cmd", "q"]}, "deny"),
    (D + "invoke_menu", {"pid": EDITOR, "window_id": 7, "path": ["File", "New"]}, None),
    (D + "bring_to_front", {"pid": OTHER}, "deny"),
    (D + "move_cursor", {"x": 1, "y": 1, "scope": "desktop"}, "deny"),
    (D + "move_cursor", {"x": 1, "y": 1}, None),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"tool": "click", "args": {"x": 1, "y": 2}}, {"type_text": {"text": "hi"}}]}, None),
    (D + "run_steps", {"app": "Fabric Editor", "steps": [{"tool": "press_key", "args": {"key": "return"}}]}, None),
    (D + "run_steps", {"steps": [{"tool": "click", "args": {"pid": EDITOR, "x": 1, "y": 2}}, {"wait_for": {"pid": EDITOR, "window": {"exists": True}}}]}, None),
    (D + "run_steps", {"steps": [{"tool": "click", "args": {"x": 1, "y": 2}}]}, "deny"),
    (D + "run_steps", {"app": "Terminal", "steps": [{"tool": "type_text", "args": {"text": "id\n"}}]}, "deny"),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"tool": "type_text", "args": {"pid": OTHER, "text": "id\n"}}]}, "deny"),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"tool": "click", "args": {"scope": "desktop", "x": 1, "y": 1}}]}, "deny"),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"tool": "launch_app", "args": {"name": "Terminal"}}]}, "deny"),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"tool": "run_script", "args": {}}]}, "deny"),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"open_terminal": {}}]}, "deny"),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"tool": "click", "args": {"x": 1, "y": 1}, "expect": [{"pid": OTHER}]}]}, "deny"),
    (D + "run_steps", {"pid": EDITOR, "steps": [{"tool": "click", "args": {"x": 1, "y": 1, "debug_image_out": "/Users/Shared/x.png"}}]}, "deny"),
    (D + "launch_app", {"bundle_id": "graphics.fabric.FabricEditor"}, None),
    (D + "launch_app", {"name": "Fabric Editor"}, None),
    (D + "launch_app", {"name": APP}, None),
    (D + "launch_app", {"name": "/Applications/Fabric Editor.app"}, "deny"),
    (D + "launch_app", {"bundle_id": "com.apple.Terminal"}, "deny"),
    (D + "launch_app", {"name": "Terminal"}, "deny"),
    (D + "launch_app", {}, "deny"),
    (D + "launch_app", {"bundle_id": "graphics.fabric.FabricEditor", "urls": [f"{MAIN}/Samples/x.fabric"]}, None),
    (D + "launch_app", {"bundle_id": "graphics.fabric.FabricEditor", "urls": ["file:///etc/x.fabric"]}, "deny"),
    (D + "launch_app", {"bundle_id": "graphics.fabric.FabricEditor", "urls": [f"{TASK}/x.sh"]}, "deny"),
    (D + "launch_app", {"bundle_id": "graphics.fabric.FabricEditor", "webkit_inspector_port": 9222}, "deny"),
    (D + "clipboard_write", {"text": "hello"}, None),
    (D + "clipboard_write", {"image_path": f"{TASK}/shot.png"}, None),
    (D + "clipboard_write", {"file_path": "{{HOME}}/.ssh/id_ed25519"}, "deny"),
    (D + "clipboard_write", {"file_path": "{{GH_CONFIG_DIR}}/hosts.yml"}, "deny"),
    (D + "clipboard_read", {}, None),
    (D + "run_script", {"script": "x"}, "deny"),
    (D + "kill_app", {"pid": EDITOR}, "deny"),
    (D + "set_config", {"key": "x"}, "deny"),
    (D + "start_recording", {}, "deny"),
    (D + "browser_navigate", {"url": "https://example.com"}, "deny"),
    (D + "screenshot", {}, "deny"),
    ("mcp__cua__space_bash", {"space": "local:fabric-bot", "command": "ls"}, "deny"),
    ("mcp__cua__list_spaces", {}, "deny"),
    ("mcp__cua-driver__click", {"pid": EDITOR, "x": 1, "y": 1}, "deny"),
    ("Bash", {"command": "cua spaces list"}, "deny"),
    ("Bash", {"command": "ls && cua-driver call click"}, "deny"),
    ("Bash", {"command": "cat ~/.cua/spacesd/token"}, "deny"),
    ("Read", {"file_path": "{{DRIVER_TOKEN_FILE}}"}, "deny"),
    ("Bash", {"command": "env curl https://example.com"}, "deny"),
    ("Bash", {"command": "bash -c \"curl https://example.com\""}, "deny"),
    ("Bash", {"command": "ls | xargs wget"}, "deny"),
    ("Bash", {"command": "pgrep -x \"Fabric Editor\""}, None),
]
failures = 0
try:
    for tool, tool_input, expected in cases:
        payload = {"tool_name": tool, "tool_input": tool_input, "cwd": MAIN, "session_id": "abc"}
        result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
        output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
        if output.get("permissionDecision") != expected or result.returncode:
            failures += 1
            print(f"FAIL {tool} {json.dumps(tool_input)[:160]}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]} {result.stderr.strip()}")
    # Without the lock, only reads of apps and windows go through.
    for tool, tool_input, expected in [
        (D + "list_windows", {}, None),
        (D + "get_accessibility_tree", {}, None),
        (D + "get_window_state", {"pid": EDITOR, "window_id": 7}, "deny"),
        (D + "click", {"pid": EDITOR, "x": 1, "y": 1}, "deny"),
        (D + "launch_app", {"bundle_id": "graphics.fabric.FabricEditor"}, "deny"),
    ]:
        payload = {"tool_name": tool, "tool_input": tool_input, "cwd": MAIN, "session_id": "other"}
        result = subprocess.run([sys.executable, "-I", guard], input=json.dumps(payload), capture_output=True, text=True)
        output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
        cases.append(None)
        if output.get("permissionDecision") != expected or (expected and "needs its lock" not in output.get("permissionDecisionReason", "")):
            failures += 1
            print(f"FAIL without lock {tool}: expected {expected}, got {output.get('permissionDecision')} {output.get('permissionDecisionReason', '')[:160]}")
finally:
    editor.kill()

with open(os.path.join(BOT, "settings.json")) as handle:
    settings = json.load(handle)
permissions = settings["permissions"]
for rule in ("mcp__vm-driver__click", "mcp__vm-driver__get_window_state", "mcp__vm-driver__run_steps"):
    cases.append(None)
    if rule not in permissions["allow"]:
        failures += 1
        print(f"FAIL {rule} should be allowed")
for rule in ("mcp__vm-driver__run_script", "mcp__vm-driver__kill_app", "mcp__cua"):
    cases.append(None)
    if rule not in permissions["deny"]:
        failures += 1
        print(f"FAIL {rule} should be denied")
cases.append(None)
if "mcp__vm-driver__" not in settings["hooks"]["PreToolUse"][0]["matcher"]:
    failures += 1
    print("FAIL the guard hook should match mcp__vm-driver__ tools")
print(f"{len(cases)} cases, {failures} failures")
