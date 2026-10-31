import json, os, subprocess, sys
from support import CONFIG, render
HOME = CONFIG["HOME"]
guard = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard.py")
MAIN = render("{{CHECKOUT}}")
SCRATCH = render("{{SCRATCH_ROOT}}/abc/scratchpad")
# The guard resolves a worktree's repo from its .git file.
os.makedirs(f"{SCRATCH}/wt-pr.noindex", exist_ok=True)
with open(f"{SCRATCH}/wt-pr.noindex/.git", "w") as handle:
    handle.write(f"gitdir: {MAIN}/.git\n")
cases = [
    # git -c / exec-path now deny instead of ask
    ('git -c core.sshCommand=evil fetch fork', MAIN, "deny"),
    ('git --exec-path=/tmp status', MAIN, "deny"),
    ('git -c user.email={{COMMIT_EMAIL}} commit -m x', MAIN, None),
    # discarding work only under the scratchpad
    ('git reset --hard origin/main', MAIN, "deny"),
    ('git -C Satin reset --hard HEAD', MAIN, "deny"),
    ('git clean -fdx', MAIN, "deny"),
    ('git reset --hard origin/main', f"{SCRATCH}/wt-pr.noindex", None),
    (f'cd {SCRATCH}/wt-pr.noindex && git reset --hard pr-443', MAIN, None),
    (f'git -C {SCRATCH}/wt-pr.noindex clean -fdx', MAIN, None),
    (f'cd {SCRATCH}/wt && cd {MAIN} && git clean -f', MAIN, "deny"),
    ('git reset --soft HEAD~1', MAIN, None),
    ('git -C {{CHECKOUT}}-feature reset --hard', MAIN, "deny"),
    # worktree remove
    (f'git worktree remove --force {SCRATCH}/wt-pr.noindex', MAIN, None),
    ('git worktree remove ../Fabric-feature', MAIN, "deny"),
    ('git worktree add {{SCRATCH_ROOT}}/x/wt.noindex pr-1', MAIN, None),
    # stash, config, credential
    ('git stash drop', MAIN, "deny"),
    ('git stash clear', SCRATCH, "deny"),
    ('git stash list', MAIN, None),
    ('git -C Satin config --global user.name x', MAIN, "deny"),
    ('git config user.email', MAIN, None),
    ('echo url=https://github.com | git credential fill', MAIN, "deny"),
    # rm
    (f'rm -rf {SCRATCH}/wt-pr.noindex', MAIN, None),
    ('rm -rf .build.noindex', MAIN, None),
    ('rm -rf Sources', MAIN, "deny"),
    ('rm -rf ~', MAIN, "deny"),
    ('rm -rf $HOME/x', SCRATCH, "deny"),
    (f'rm -rf {SCRATCH}/{os.path.relpath(HOME, SCRATCH)}', MAIN, "deny"),
    ('rm Sources/Fabric/Old.swift', MAIN, None),
    ('rm ~/Documents/x.txt', MAIN, "deny"),
    ('rm -f ~/.swiftpm/security/fingerprints/Satin.json', MAIN, None),
    (f'rm -r {SCRATCH}/x/*', MAIN, None),
    # gh writes pinned to the fork
    ('gh pr comment 443 -R Fabric-Project/Fabric --body x', MAIN, "deny"),
    ('gh pr comment 443 --body x', MAIN, "deny"),
    ('gh pr comment 19 -R {{FORK_OWNER}}/Fabric --body x', MAIN, None),
    ('gh pr review 19 -R {{FORK_OWNER}}/Satin --comment -b x', MAIN, None),
    ('gh pr close https://github.com/Fabric-Project/Fabric/pull/443 -R {{FORK_OWNER}}/Fabric', MAIN, "deny"),
    ('gh issue create --title t --body b', MAIN, "deny"),
    ('gh issue comment https://github.com/Fabric-Project/Satin/issues/5 -R {{FORK_OWNER}}/Satin -b x', MAIN, "deny"),
    ('gh issue create -R {{FORK_OWNER}}/Fabric --title t --body b', MAIN, None),
    ('gh issue view 5 -R Fabric-Project/Fabric', MAIN, None),
    # gh api
    ('gh api repos/Fabric-Project/Fabric/pulls/443', MAIN, None),
    ('gh api repos/Fabric-Project/Fabric/pulls/443/comments --paginate --jq ".[].body"', MAIN, None),
    ('gh api -X POST repos/{{FORK_OWNER}}/Fabric/pulls/19/reviews --input review.json', MAIN, None),
    ('gh api repos/{{FORK_OWNER}}/Satin/pulls/7/comments/123/replies -f body=fixed', MAIN, None),
    ('gh api --method=PATCH repos/{{FORK_OWNER}}/Fabric/issues/comments/5 -f body=x', MAIN, None),
    ('gh api -X DELETE repos/{{FORK_OWNER}}/Fabric/pulls/comments/5', MAIN, None),
    ('gh api -X POST repos/Fabric-Project/Fabric/pulls/443/reviews --input review.json', MAIN, "deny"),
    ('gh api repos/Fabric-Project/Fabric/issues/443/comments -f body=x', MAIN, "deny"),
    ('gh api repos/{owner}/{repo}/pulls/1/reviews -f event=COMMENT', MAIN, "deny"),
    ('gh api -X PUT repos/{{FORK_OWNER}}/Fabric/pulls/19/merge', MAIN, "deny"),
    ('gh api -X DELETE repos/{{FORK_OWNER}}/Fabric/git/refs/heads/main', MAIN, "deny"),
    ('gh api -XDELETE repos/{{FORK_OWNER}}/Fabric', MAIN, "deny"),
    ('gh api search/issues -X GET -f q=repo:Fabric-Project/Fabric', MAIN, None),
    ('gh api graphql -f query="query { viewer { login } }"', MAIN, None),
    ('gh api graphql -f query="mutation { addComment(input:{}) { clientMutationId } }"', MAIN, "deny"),
    ('gh api graphql --input q.json', MAIN, "deny"),
    # push to upstream still guarded (settings also denies push origin)
    ('git push origin main', MAIN, "deny"),
    ('git push --force-with-lease=x:abc fork x', MAIN, None),
    ('env FABRIC_TREE=pr swift test -c release -j 8 --filter ReviewX', MAIN, None),
]
failures = 0
for command, cwd, expected in cases:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "s", "cwd": cwd}
    result = subprocess.run([sys.executable, "-I", guard], input=render(json.dumps(payload), json_escaped=True), capture_output=True, text=True)
    output = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else {}
    decision = output.get("permissionDecision")
    status = "ok  " if decision == expected else "FAIL"
    failures += decision != expected
    if decision != expected or result.stderr:
        print(status, command, "->", decision, output.get("permissionDecisionReason", ""), result.stderr[-300:])
print(f"{len(cases)} cases, failures: {failures}")
