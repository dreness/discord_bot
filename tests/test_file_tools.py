import json, os, subprocess, sys
from support import render

guard = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
session = "2468dc1f-d939-432e-a241-254c011b8683"
project = render("~/.claude/projects/{{PROJECT_SLUG}}")
home_project = os.path.expanduser(project)
cases = [
    ("Bash", {"command": f"cd {project}/ && ls *.jsonl | wc -l"}, "deny"),
    # Memory is read with file tools only, so no shell write can reach it.
    ("Bash", {"command": f"cat {project}/memory/MEMORY.md"}, "deny"),
    ("Bash", {"command": f"head {project}/{session}/tool-results/x.txt"}, None),
    ("Bash", {"command": f"head {project}/other-session/tool-results/x.txt"}, "deny"),
    ("Bash", {"command": "ls ~/.claude/projects"}, "deny"),
    ("Bash", {"command": f"cat {project}/memory/../{session}.jsonl"}, "deny"),
    ("Read", {"file_path": f"{home_project}/memory/project_running_tests.md"}, None),
    # Earlier transcripts: file tools may read them, Bash and writes may not.
    ("Read", {"file_path": f"{home_project}/{session}.jsonl"}, None),
    ("Read", {"file_path": f"{home_project}/memory/../{session}.jsonl"}, None),
    ("Read", {"file_path": f"{home_project}/{session}/subagents/agent-1.jsonl"}, None),
    ("Grep", {"pattern": "quiet", "path": home_project, "glob": "*.jsonl"}, None),
    ("Write", {"file_path": f"{home_project}/{session}.jsonl", "content": "x"}, "deny"),
    ("Edit", {"file_path": f"{home_project}/{session}.jsonl", "old_string": "a", "new_string": "b"}, "deny"),
    ("Read", {"file_path": f"{home_project}/../-Users-lume/{session}.jsonl"}, "deny"),
    ("Read", {"file_path": os.path.expanduser("~/.claude/projects/-Users-lume/x.jsonl")}, "deny"),
    ("Grep", {"pattern": "x", "path": os.path.expanduser("~/.claude/projects")}, "deny"),
    ("Read", {"file_path": f"{home_project}/{session}/tool-results/b1.txt"}, None),
    ("Read", {"file_path": "{{CHECKOUT}}/README.md"}, None),
    ("Grep", {"pattern": "x", "path": os.path.expanduser("~/.claude")}, "deny"),
    ("Grep", {"pattern": "x", "path": f"{home_project}/memory"}, None),
    ("Glob", {"pattern": "*.jsonl", "path": home_project}, None),
    ("Grep", {"pattern": "x"}, None),
    ("Bash", {"command": "git push -f fork x"}, "deny"),
    ("Bash", {"command": "git -C Satin log --oneline -1"}, None),
]
failures = 0
for tool, tool_input, expected in cases:
    payload = {"tool_name": tool, "tool_input": tool_input, "session_id": session}
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
    decision = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] if result.stdout.strip() else None
    status = "ok  " if decision == expected and not result.stderr else "FAIL"
    failures += status == "FAIL"
    print(status, tool, json.dumps(tool_input)[:90], "->", decision, result.stderr[-150:])
print("failures:", failures)
