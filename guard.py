#!/usr/bin/env python3 -I
"""PreToolUse guard for the Discord bot session, which runs in dontAsk mode.
Denies Bash commands that permission rules can't express reliably (git -C,
flag reordering, quoting, target paths and repos), and file-tool reads of
session transcripts other than this session's own. Never asks: there is no
one to ask."""
import importlib.util
import json
import os
import re
import shlex
import sys
import time

# glob, subprocess, ctypes and the server's modules are imported where used: together they cost ~8 ms per hook run.


def load_config():
    # A guard that crashes lets the tool call through, so a broken config denies everything instead.
    try:
        spec = importlib.util.spec_from_file_location("bot_config", os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.values()
    except Exception as error:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"discord-bot guard: config failed to load ({error}); everything is denied until the operator fixes .envrc",
        }}))
        sys.exit(0)


CONFIG = load_config()

PROTECTED_BRANCHES = {"main", "master"}
PERSONAL_FORK_REMOTE = "fork"
PROTECTED_PATH_FRAGMENTS = (
    ".claude/channels",
    ".claude/.credentials",
    ".claude/settings",
    ".claude/discord-bot",
    CONFIG["BOT_DIRECTORY_FRAGMENT"],
    ".claude/hooks",
    ".claude/plugins",
    ".ssh",
    ".config/gh",
    CONFIG["GH_CONFIG_DIR"],
    "Library/Keychains",
    ".git/hooks",
    ".cua/",
    "Cua Volume",
    "--dangerously-skip-permissions",
)
PROJECTS_DIRECTORY = os.path.realpath(os.path.expanduser("~/.claude/projects"))
FABRIC_PROJECT_NAME = CONFIG["PROJECT_SLUG"]
FABRIC_PROJECT_DIRECTORY = os.path.join(PROJECTS_DIRECTORY, FABRIC_PROJECT_NAME)
DISCORD_STATE_DIRECTORY = CONFIG["DISCORD_STATE_DIR"]


def state_ancestors():
    # Folders above the state directory, up to but not including home: naming one reaches the state too.
    ancestors, path = [], os.path.dirname(DISCORD_STATE_DIRECTORY)
    while path.startswith(CONFIG["HOME"] + os.sep):
        ancestors.append(path)
        path = os.path.dirname(path)
    return ancestors


DISCORD_STATE_ANCESTORS = state_ancestors()
# Credentials and the bot's own configuration, matched after symlinks resolve.
PROTECTED_REAL_PATHS = tuple(os.path.realpath(os.path.expanduser(path)) for path in (
    "~/.ssh", "~/.config/gh", CONFIG["GH_CONFIG_DIR"], "~/.claude/.credentials.json", "~/Library/Keychains", "~/.aws", "~/.netrc", CONFIG["BOT_DIRECTORY"],
    "~/.cua", CONFIG["DRIVER_TOKEN_FILE"], CONFIG["CUA_VOLUME"],
))
PROTECTED_REAL_PATH_DENIAL = "that path holds credentials (SSH keys, gh tokens, the Claude login, keychains, the spacesd token), the bot's own configuration or the Cua Volume (outlives VM resets; preferences and the job ledger go through their commands), under whatever name or symlink it is reached. Supported: nothing there; ask the operator"
# Read by the operator's own, less restricted sessions: instructions, memory, Claude and MCP config, git internals (hooks, fsmonitor).
INSTRUCTION_FILE_NAMES = {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"}
PERSISTENT_WRITE_DENIAL = "the operator's own Claude sessions and git read this (CLAUDE.md, AGENTS.md, .claude/, .mcp.json, the memory folder, .git internals), so content written here would outlive this session and act outside its limits. Supported: the same edit in a worktree under {root}, committed to a fork branch for the operator to review; ask the operator to change memory or the main checkout's instructions"
# Path spellings in commands and code, including os.path.join("~/.claude", "channels") style splits.
DISCORD_STATE_PATTERN = re.compile(r"\.claude\W{0,12}channels|channels\W{0,12}discord|DISCORD_STATE_DIR|" + re.escape(DISCORD_STATE_DIRECTORY))
DISCORD_STATE_DENIAL = f"{DISCORD_STATE_DIRECTORY} is the Discord plugin's state (bot token, access list, inbox); it can't be read, listed, written or copied from, by any tool. Supported: nothing there; ask the requester to push files to a PR branch instead of attaching them, and the operator handles anything else"
# Programs that walk a whole tree, so naming home or / with them reaches the state directory.
TREE_WALKERS = {"find", "rg", "ag", "fd", "ditto", "rsync", "tar", "zip", "du", "mdfind", "mdls", "xattr", "pax", "cpio"}
RECURSIVE_WHEN_FLAGGED = {"grep", "egrep", "fgrep", "cp", "ls", "chmod", "chown"}
PREFERENCES_COMMAND_PATTERN = re.compile(re.escape(CONFIG["PREFERENCES_COMMAND"]) + r" (get [0-9]{15,21}|set [0-9]{15,21}( (frequency=(updates|quiet)|verbosity=(brief|detailed))){1,2})")
JOB_ID_TEXT = r"[0-9]{6}-[0-9a-f]{6}"
JOB_ID = re.compile(JOB_ID_TEXT)
CLEAR_COMMAND_PATTERN = re.compile(re.escape(CONFIG["CLEAR_COMMAND"]) + " " + JOB_ID_TEXT)
JOBS_COMMAND_PATTERN = re.compile(re.escape(CONFIG["JOBS_COMMAND"]) + rf" (start [0-9]{{15,21}}|list( [0-9]{{15,21}})?( [0-9]{{1,5}})?|show {JOB_ID_TEXT}|running|finish {JOB_ID_TEXT} (done|failed|blocked|cancelled) (?P<result>[A-Za-z0-9_./+@%-]+))")
JOB_TAG = "FABRIC_JOB"
JOB_TAG_ROUTE = f"prefix it with env {JOB_TAG}=<job id> (the id {{jobs}} start printed for the request this work is for), e.g. env {JOB_TAG}=<id> swift build ...; for the Editor, open --env {JOB_TAG}=<id> ...".format(jobs=CONFIG["JOBS_COMMAND"])
JOB_TAG_DENIAL = "builds, background commands and Editor launches carry the job id of the request they're for, so `clear` and status can tell whose work a process is. Supported: " + JOB_TAG_ROUTE
TRANSCRIPTS_OFF_LIMITS = f"other projects' transcripts under ~/.claude/projects are off limits, and this project's are read with file tools only. Supported: the Read, Grep and Glob tools on {FABRIC_PROJECT_DIRECTORY}, and Bash on this session's own tool-results/"
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
FORK_OWNER = CONFIG["FORK_OWNER"]
COMMIT_EMAIL = CONFIG["COMMIT_EMAIL"]
MAIN_CHECKOUT = CONFIG["CHECKOUT"]
# Scratchpads live here; the only place recursive deletes and hard resets are allowed.
DISPOSABLE_ROOT = CONFIG["SCRATCH_ROOT"]
# Recursive rm is also allowed on build output, which always ends in .noindex.
DISPOSABLE_SUFFIX = ".noindex"
WORKTREE_PREFIX = os.path.dirname(MAIN_CHECKOUT) + "/Fabric-"
RM_ROOTS = (
    DISPOSABLE_ROOT,
    MAIN_CHECKOUT,
    os.path.dirname(MAIN_CHECKOUT) + "/Fabric-",
    os.path.realpath(os.path.expanduser("~/.swiftpm/security/fingerprints")),
)
# Write subcommands settings.json allows; the guard pins them to the fork.
FORK_ONLY_GH_SUBCOMMANDS = {
    "pr": {"create", "edit", "ready", "comment", "review", "close", "reopen"},
    "issue": {"create", "edit", "comment", "close", "reopen"},
}
GH_REPO_FLAGS = ("-R", "--repo")
GITHUB_ITEM_URL = re.compile(r"^(https?://)?github\.com/[^/\s]+/[^/\s]+/(pull|issues)/\d+/?([#?]\S*)?$")
GH_API_OPTIONS_WITH_VALUE = {
    "-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field", "--input",
    "-q", "--jq", "-t", "--template", "-p", "--preview", "--cache", "--hostname",
}
GH_API_FIELD_OPTIONS = {"-f", "--raw-field", "-F", "--field", "--input"}
FORK_API_WRITE_ENDPOINT = re.compile(rf"^/?repos/{FORK_OWNER}/[^/]+/(pulls|issues)/", re.IGNORECASE)
DENIED_GH = [
    ("repo", "delete"), ("repo", "archive"), ("repo", "rename"), ("repo", "edit"),
    ("pr", "merge"), ("release", "delete"), ("auth", "token"), ("auth", "login"),
    ("auth", "logout"), ("auth", "refresh"), ("auth", "setup-git"), ("auth", "switch"), ("secret",), ("ssh-key",),
    ("gpg-key",), ("variable",), ("ruleset",),
]
# gh picks the credential by host and, for a host its config lacks, falls back to the
# operator's keychain login; so gh may only talk to github.com.
GH_ALLOWED_HOSTS = {"github.com", "api.github.com", "gist.github.com", "www.github.com", "uploads.github.com"}
GH_URL_HOST = re.compile(r"^[a-z][a-z0-9+.-]*://([^/\s?#]+)", re.IGNORECASE)
GH_HOST_DENIAL = "gh may only reach github.com: another host (--hostname, a URL, HOST/OWNER/REPO) makes gh fall back to the operator's personal keychain login. Supported: github.com URLs and OWNER/REPO"
# Token and key shapes that must never leave the machine: GitHub, Anthropic, Discord bot tokens, private keys.
SECRET_PATTERN = re.compile(
    r"github_pat_[A-Za-z0-9_]{20,}|\bgh[opsur]_[A-Za-z0-9]{30,}|\bsk-ant-[A-Za-z0-9_-]{20,}"
    r"|\b[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
SECRET_DENIAL = "this would publish what looks like a token or private key. Supported: leave credentials out of replies, gists, comments and bodies; if one leaked into a file, tell the operator"
GH_AUTH_DENIAL = "gh auth is limited to plain status: other subcommands and --show-token expose or change credentials. Supported: gh auth status"
# Report gists: secret (unlisted, link-readable), tagged, built from scratch files only.
GIST_MARKER = "[fabric-bot] "
GIST_READ_ONLY_SUBCOMMANDS = {"view", "list", "ls"}
GIST_ID_OR_URL = re.compile(r"^(https://gist\.github\.com/([^/\s]+/)?)?([0-9a-f]{20,40})/?$")
GIST_ROUTE = f"gh gist create --desc '{GIST_MARKER}...' <files under {DISPOSABLE_ROOT}>, and gh gist edit <id> with --add <file>, --filename <name> <file>, --remove <name> or --desc '{GIST_MARKER}...' on a gist whose description starts with '{GIST_MARKER.strip()}'"
# The guest's own cua-driver, served by spacesd. Not here: config, recording, browser, scripts, sessions, kill_app.
VM_DRIVER_PREFIX = "mcp__vm-driver__"
VM_DRIVER_TOOLS = {
    "list_apps", "list_windows", "get_window_state", "verify_state", "launch_app", "bring_to_front", "set_window_frame",
    "invoke_menu", "click", "double_click", "right_click", "drag", "type_text", "press_key", "hotkey", "set_value", "scroll",
    "get_screen_size", "get_desktop_state", "get_cursor_position", "move_cursor", "get_accessibility_tree", "zoom",
    "run_steps", "get_guide", "clipboard_read", "clipboard_write",
}
# Reads that leave windows alone.
VM_DRIVER_TOOLS_WITHOUT_LOCK = {
    "get_guide", "list_apps", "list_windows", "get_screen_size", "get_cursor_position", "get_desktop_state", "get_accessibility_tree", "clipboard_read",
}
# Input reaches only the Editor: driving Terminal or another app would run commands past the guard.
VM_DRIVER_INPUT_TOOLS = {
    "bring_to_front", "set_window_frame", "invoke_menu", "click", "double_click", "right_click", "drag", "type_text",
    "press_key", "hotkey", "set_value", "scroll", "run_steps",
}
VM_DRIVER_STEP_TOOLS = {"click", "double_click", "right_click", "set_value", "type_text", "press_key", "hotkey", "scroll", "drag", "move_cursor"}
# Arguments naming local files: screenshot_out_file, debug_image_out, clipboard file_path/image_path.
VM_DRIVER_PATH_KEY = re.compile(r"(file|path|_out)$")
EDITOR_BUNDLE_ID = "graphics.fabric.FabricEditor"
EDITOR_APP_NAMES = {"fabric editor", EDITOR_BUNDLE_ID.lower()}
EDITOR_EXECUTABLE_SUFFIX = "/Fabric Editor.app/Contents/MacOS/Fabric Editor"
# Word match anywhere, so env/bash -c/xargs wrappers are caught too.
HTTP_FETCH_PATTERN = re.compile(r"\b(curl|wget)\b")
PLACEHOLDER_PATTERN = re.compile(r"\{\{([A-Z_]+)\}\}")
BOT_TEMPLATE = os.path.join(CONFIG["BOT_DIRECTORY"], "BOT.md")
CLAUDE_MD_FILES = (os.path.join(CONFIG["HOME"], ".claude", "CLAUDE.md"), os.path.join(MAIN_CHECKOUT, "CLAUDE.md"))
DISCORD_SENDING_TOOLS = {"reply", "edit_message"}
PRIVATE_INSTRUCTIONS_DENIAL = f"the bot's own instructions are shared only as the BOT.md template, never as the filled-in prompt (it carries machine-specific configuration), and CLAUDE.md files are never shared raw. Supported: when asked, attach {BOT_TEMPLATE} with reply files; summarize CLAUDE.md or quote a single rule"
CLAUDE_LAUNCH_PATTERN = re.compile(r"--channels\b|discord@claude-plugins-official|plugin:discord")
KILL_ROUTE = "Supported: pkill -x \"Fabric Editor\"; kill <pid> for the bot's own builds, tests and tools; TaskStop for this session's own background tasks"
# Processes the bot must not signal besides its own ancestors: the guard server, the Discord plugin, spacesd and the driver, tmux.
PROTECTED_PROCESS_NAMES = {"claude", "tmux", "spacesd", "cua-driver", "launchd", "loginwindow", "WindowServer", "Finder", "Dock", "SystemUIServer"}
PROTECTED_PROCESS_ARGUMENTS = re.compile(r"guard\.py\S*\s+--serve|\bbun\b.*/discord/|spacesd|cua-driver")
PKILL_FLAGS = {"-f", "-x", "-i", "-n", "-o", "-l"}
KILLALL_FLAGS = {"-m", "-I", "-v", "-q"}
SIGNAL_FLAG = re.compile(r"^-([0-9]+|[A-Z]+[0-9A-Z]*)$")
CLAUDE_LAUNCH_DENIAL = "the bot doesn't start Claude sessions: a second session would duplicate the bot or escape its settings, and only one Discord client may run. Supported: do the work in this session, or use the Agent tool for a subagent"
HTTP_FETCH_DENIAL = "no downloading from the web (curl/wget, even wrapped or mentioned). Supported: ask the requester to push the files to a PR branch on a Fabric-related repo, git fetch it into a worktree, and use them from there"
# Fabric, Satin, Fabric-Samples on upstream and the fork, plus Fabric's other submodules.
RELATED_REPOSITORIES = {
    "fabric-project/fabric", "fabric-project/satin", "fabric-project/fabric-samples",
    *(f"{FORK_OWNER.lower()}/{name}" for name in ("fabric", "satin", "fabric-samples")),
    "vade/lygia", "syphon/syphon-framework", "vidvox/hap-in-avfoundation",
}
# Git common dirs: the main checkout's (its worktrees and submodules live inside it) and Fabric-Samples'.
RELATED_GIT_DIRECTORIES = (
    os.path.join(MAIN_CHECKOUT, ".git"),
    os.path.join(CONFIG["SAMPLES_CHECKOUT"], ".git"),
)
GIT_URL = re.compile(r"^([a-z][a-z0-9+.-]*://|[\w.-]+@[\w.-]+:|github\.com[:/])", re.IGNORECASE)
GIT_REMOTE_SUBCOMMANDS = {"fetch", "pull", "push", "ls-remote"}
# Config keys that redirect remotes or make git run other programs.
GIT_CONFIG_DANGEROUS_KEY = re.compile(r"^(remote|url|submodule|include|includeif|core|credential|protocol|http|alias|filter|diff|merge|gpg)\.", re.IGNORECASE)
GIT_CONFIG_READ_FLAGS = {"--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin", "--show-scope", "get", "list"}
GIT_ENVIRONMENT_ASSIGNMENT = re.compile(r"^GIT_[A-Z_]*=")
# settings.json env points gh at the bot's scoped token and git at HTTPS through it; these would undo that.
AUTH_ENVIRONMENT = re.compile(r"\b(GH_[A-Z_]+|GITHUB_[A-Z_]*TOKEN|GIT_CONFIG[A-Z_0-9]*|XDG_CONFIG_HOME)\b")
AUTH_ENVIRONMENT_DENIAL = "gh and git authenticate with the bot's own scoped token, set up by the operator; changing or clearing GH_*, GITHUB_*TOKEN, GIT_CONFIG* or XDG_CONFIG_HOME, or running env -i/-u, would swap in other credentials. Supported: plain gh and git commands"
BOT_TREE_ROOTS = (DISPOSABLE_ROOT, MAIN_CHECKOUT, os.path.dirname(MAIN_CHECKOUT) + "/Fabric-")
# Options of xargs that take a value, so the program it runs can be found.
XARGS_OPTIONS_WITH_VALUE = {"-E", "-I", "-J", "-L", "-n", "-P", "-R", "-S", "-s", "-d", "-a"}
FIND_EXEC_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir"}
DISCARDING_CHECKOUT_FLAGS = {"-f", "--force", "-B", "--", "-p", "--patch", "--ours", "--theirs", "-m", "--merge", "--overwrite-ignore"}
DISCARDING_SWITCH_FLAGS = {"-f", "--force", "--discard-changes", "-C", "--force-create", "-m", "--merge"}
OPEN_EDITOR_ROUTE = f"open --env FABRIC_JOB=<job id> \"<derived data>/Build/Products/Release/Fabric Editor.app\" (optionally -n, -F, -W, -g, --args ...) or open -a <that app> <file>.fabric, with the Editor and files under the Fabric checkout, Fabric-* worktrees or {CONFIG['SCRATCH_ROOT']}, while holding the Editor lock"
OPEN_FLAGS = {"-n", "--new", "-F", "--fresh", "-W", "--wait-apps", "-g", "--background", "-j", "--hide"}
SCREENCAPTURE_FLAGS = {"-x", "-C", "-m", "-o", "-S", "-a", "-r", "-d"}
SCREENCAPTURE_FLAGS_WITH_VALUE = {"-D", "-t", "-T", "-l", "-R"}
SCREENCAPTURE_ROUTE = f"driver screenshots (get_window_state, zoom), or screencapture -x [-l <window id>] [-R x,y,w,h] <file under {CONFIG['SCRATCH_ROOT']}>"
KEYCHAIN_DENIAL = "the keychain may hold credentials. Supported: nothing there; the bot's GitHub access is the scoped token gh already uses"
# Programs that run code: their script files get scanned for the Discord state folder.
CODE_RUNNERS = {"python3", "python", "bash", "zsh", "sh", "swift", "swiftc", "xcrun", "osascript", "perl", "ruby", "node"}
SWIFT_BUILD_SUBCOMMANDS = {"build", "package"}
# Compile parallelism cap shared by all of the bot's builds, so the VM's session and other tasks stay responsive.
MAXIMUM_BUILD_JOBS = int(CONFIG["BUILD_JOBS"])
SWIFT_COMPILING_SUBCOMMANDS = {"build", "test", "run"}
XCODEBUILD_NON_BUILDING_FLAGS = {"-list", "-showBuildSettings", "-showsdks", "-showdestinations", "-showTestPlans", "-version", "-help", "-usage", "-resolvePackageDependencies", "-checkFirstLaunchStatus"}
# Running build processes and their job-count flags; nested ones count with their parent.
BUILD_PROCESS_JOB_FLAGS = {"swift-build": ("-j", "--jobs"), "swift-test": ("-j", "--jobs"), "swift-run": ("-j", "--jobs"), "xcodebuild": ("-jobs",)}
TASK_ROOT = CONFIG["TASK_ROOT"]
# Kept built on origin/main by warm-main.sh; tasks borrow it through the lease and give it back.
WARM_ROOT = os.path.join(TASK_ROOT, "warm-main.noindex")
WARM_LEASE = os.path.join(WARM_ROOT, "lease")
WARM_ROUTE = f"give the warm tree back as BOT.md says (checkout --detach -f, clean, rm READY, rm -r {WARM_LEASE}); never remove it or its build folders"
BUILD_JOBS_DENIAL = f"builds are capped at {MAXIMUM_BUILD_JOBS} compile jobs so the VM stays responsive for the session and other tasks. Supported: swift build/test/run -j {MAXIMUM_BUILD_JOBS} (or --jobs {MAXIMUM_BUILD_JOBS}), xcodebuild ... -jobs {MAXIMUM_BUILD_JOBS}, or any lower count"
# One task at a time uses the VM. The guard writes holder.json on mkdir -p and refreshes its mtime on each of the holder's tool calls.
EDITOR_LOCK = CONFIG["EDITOR_LOCK"]
EDITOR_LOCK_HOLDER = os.path.join(EDITOR_LOCK, "holder.json")
EDITOR_LOCK_TASK = os.path.join(EDITOR_LOCK, "task.txt")
EDITOR_LOCK_STALE_SECONDS = 15 * 60
SESSION_REGISTRY = CONFIG["SESSION_REGISTRY"]
EDITOR_LOCK_ROUTE = f"mkdir -p {EDITOR_LOCK} takes the Editor desktop when it is free and otherwise says who holds it and whether the lock is stale; then write the task and requester to {EDITOR_LOCK_TASK}, and rm -r {EDITOR_LOCK} when done"

PROSE_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".html", ".csv", ".log"}


def decide(decision, reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": f"discord-bot guard: {reason}",
    }}))
    sys.exit(0)


DENIAL_FOOTER = " Use the supported route; don't rephrase the command to get past this. If the task truly needs the denied action, tell the requester the operator has to do it."


def deny(reason):
    decide("deny", reason.rstrip(".") + "." + DENIAL_FOOTER)


def readable_project_subpaths(session_id):
    # This session's own persisted tool output lives under the project directory too.
    subpaths = ["memory"]
    if session_id:
        subpaths.append(f"{session_id}/tool-results")
    return subpaths


def is_within(path, directory):
    return path == directory or path.startswith(directory + os.sep)


def touches_discord_state(path):
    return is_within(path, DISCORD_STATE_DIRECTORY) or path in DISCORD_STATE_ANCESTORS


def in_bot_trees(path):
    # A root ending in "-" is a prefix for sibling worktrees.
    return any(path.startswith(root) if root.endswith("-") else is_within(path, root) for root in BOT_TREE_ROOTS)


def persistent_write_target(path):
    """Whether writing path would change what the operator's own sessions or git load."""
    if f"{os.sep}.git{os.sep}" in path + os.sep or os.path.basename(path) == ".mcp.json":
        return True
    if is_within(path, os.path.join(FABRIC_PROJECT_DIRECTORY, "memory")):
        return True
    if is_within(path, DISPOSABLE_ROOT):
        return False
    return os.path.basename(path) in INSTRUCTION_FILE_NAMES or f"{os.sep}.claude{os.sep}" in path + os.sep


def check_persistent_write(path):
    if persistent_write_target(path):
        deny(PERSISTENT_WRITE_DENIAL.format(root=DISPOSABLE_ROOT) + f" ({path})")


def check_file_tool(tool_input, session_id):
    if DISCORD_STATE_PATTERN.search(str(tool_input.get("pattern", "")) + str(tool_input.get("glob", ""))):
        deny(DISCORD_STATE_DENIAL)
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
    if not raw_path:
        return
    path = os.path.realpath(os.path.expanduser(raw_path))
    if touches_discord_state(path):
        deny(DISCORD_STATE_DENIAL)
    if any(is_within(path, protected) for protected in PROTECTED_REAL_PATHS):
        deny(PROTECTED_REAL_PATH_DENIAL + f" ({raw_path})")
    # Earlier sessions' transcripts and memory; writes there were already denied as persistent.
    if is_within(path, FABRIC_PROJECT_DIRECTORY):
        return
    # Also catches searches rooted above the projects directory, such as Grep over ~/.claude.
    if is_within(path, PROJECTS_DIRECTORY) or is_within(PROJECTS_DIRECTORY, path):
        deny(TRANSCRIPTS_OFF_LIMITS)


def check_projects_references(command, session_id):
    # Memory is read with file tools only, so no shell command can write to it.
    readable = [f"/{FABRIC_PROJECT_NAME}/{subpath}" for subpath in readable_project_subpaths(session_id) if subpath != "memory"]
    for match in re.finditer(r"\.claude/projects", command):
        remainder = command[match.end():]
        path_text = re.split(r"[\s'\";&|)]", remainder, maxsplit=1)[0]
        if "/.." in path_text or not any(path_text.startswith(prefix) for prefix in readable):
            deny(TRANSCRIPTS_OFF_LIMITS)


def split_segments(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace_split = True
    lexer.commenters = ""
    segment = []
    try:
        for token in lexer:
            if token and set(token) <= set(";&|()\n"):
                if segment:
                    yield segment
                segment = []
            else:
                segment.append(token)
    except ValueError:
        # Unbalanced quotes or heredoc bodies: fall back to whitespace split.
        yield command.split()
        return
    if segment:
        yield segment


def strip_prefixes(tokens):
    wrappers = {"command", "builtin", "nohup", "time", "nice", "env", "xargs", "exec"}
    while tokens and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]) or tokens[0] in wrappers):
        if tokens[0] == "xargs":
            tokens = tokens[1:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[2:] if tokens[0] in XARGS_OPTIONS_WITH_VALUE else tokens[1:]
            continue
        tokens = tokens[1:]
    return tokens


def fed_by_xargs(segment):
    return "xargs" in segment[:len(segment) - len(strip_prefixes(segment))]


def write_targets(tokens):
    """Paths a command writes: redirections, and the destinations of common file-writing programs."""
    targets, arguments = [], []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if re.match(r"^[\d&]?(>>?|>\|)$", token):
            if index + 1 < len(tokens):
                targets.append(tokens[index + 1])
            index += 2
            continue
        redirect = re.match(r"^[\d&]?(>>?|>\|)([^&].*)$", token)
        if redirect:
            targets.append(redirect.group(2))
        elif not token.startswith("-"):
            arguments.append(token)
        index += 1
    program = tokens[0].rsplit("/", 1)[-1]
    if program in ("cp", "ditto", "ln", "install") and arguments:
        targets.append(arguments[-1])
    elif program in ("mv", "tee", "touch", "chmod", "truncate"):
        targets.extend(arguments)
    return targets


def resolve(path, working_directory):
    return os.path.realpath(os.path.join(working_directory, os.path.expanduser(path)))


def expand_home(token):
    return re.sub(r"^(\$HOME|\$\{HOME\})(?=/|$)", CONFIG["HOME"], os.path.expanduser(token))


def check_path_tokens(segment, working_directory):
    program = (strip_prefixes(segment) or [""])[0].rsplit("/", 1)[-1]
    flags = "".join(token for token in segment if re.match(r"^-[A-Za-z]+$", token))
    walks = program in TREE_WALKERS or (program in RECURSIVE_WHEN_FLAGGED and ("r" in flags or "R" in flags))
    for token in segment:
        if token.startswith("-") or len(token) > 1000:
            continue
        # Assignments and redirections name paths after their = or >.
        token = re.sub(r"^([A-Za-z_][A-Za-z0-9_]*=|\d?>>?|<)", "", token)
        if not token:
            continue
        path = os.path.join(working_directory, expand_home(token))
        import glob
        candidates = glob.glob(path)[:2000] if glob.has_magic(path) else [path]
        for candidate in candidates:
            real = os.path.realpath(candidate)
            if touches_discord_state(real) or (walks and is_within(DISCORD_STATE_DIRECTORY, real)):
                deny(DISCORD_STATE_DENIAL + f" ({token} reaches it)")
            if any(is_within(real, protected) or (walks and is_within(protected, real)) for protected in PROTECTED_REAL_PATHS):
                deny(PROTECTED_REAL_PATH_DENIAL + f" ({token} reaches it)")


def in_sibling_worktree(path):
    # Inside a Fabric-* worktree, not the worktree folder itself; Fabric-Samples is its own clone.
    if not path.startswith(WORKTREE_PREFIX) or is_within(path, CONFIG["SAMPLES_CHECKOUT"]):
        return False
    return os.sep in path[len(WORKTREE_PREFIX):].rstrip("/*")


def check_rm(arguments, working_directory):
    recursive = any(a in ("--recursive", "-R") or re.match(r"^-[A-Za-z]*[rR]", a) for a in arguments)
    targets = [a for a in arguments if not a.startswith("-")]
    if not targets:
        deny("rm without literal targets (fed by xargs or find) can't be checked. Supported: rm with literal paths; find <dir under " + DISPOSABLE_ROOT + "> ... -delete")
    for target in targets:
        if "$" in target or "`" in target:
            deny(f"rm target '{target}' uses a variable or substitution, so its real target can't be checked. Supported: rm with literal paths")
        path = resolve(target, working_directory)
        if not any(path.startswith(root) for root in RM_ROOTS):
            deny(f"rm of {path} is outside the bot's trees. Supported: rm under the Fabric checkout, Fabric-* worktrees, {DISPOSABLE_ROOT} and SwiftPM fingerprints")
        if recursive and not (is_within(path, DISPOSABLE_ROOT) or path.rstrip("/*").endswith(DISPOSABLE_SUFFIX) or in_sibling_worktree(path)):
            deny(f"recursive rm of {path} could wipe the main checkout or Fabric-Samples. Supported: rm -r under {DISPOSABLE_ROOT}, inside Fabric-* worktrees, or of *{DISPOSABLE_SUFFIX} build output; remove worktrees with git worktree remove")
        bare = path.rstrip("/*") or "/"
        if recursive and (is_within(bare, WARM_ROOT) or is_within(WARM_ROOT, bare)) and not is_within(bare, WARM_LEASE):
            deny(f"recursive rm of {path} would delete the warm main tree or its builds. Supported: {WARM_ROUTE}")


def check_find(arguments, working_directory):
    # Start paths come before the first expression.
    starts = []
    for argument in arguments:
        if argument.startswith(("-", "(", "!")):
            break
        starts.append(argument)
    starts = starts or ["."]
    if "-delete" in arguments:
        check_rm(["-r", *starts], working_directory)
    for index, argument in enumerate(arguments):
        if argument not in FIND_EXEC_ACTIONS:
            continue
        command = []
        for token in arguments[index + 1:]:
            if token in (";", "+"):
                break
            command.append(token)
        command = strip_prefixes(command)
        if command and command[0].rsplit("/", 1)[-1] in ("rm", "unlink", "rmdir"):
            # {} stands for whatever find matches, which lies anywhere under the start paths.
            rm_arguments = [a for a in command[1:] if a != "{}"]
            check_rm(["-r", *rm_arguments, *starts] if "{}" in command else rm_arguments, working_directory)
        elif command and command[0].rsplit("/", 1)[-1] in ("mv", "cp", "ditto", "tee", "truncate", "chmod"):
            if not all(is_within(resolve(start, working_directory), DISPOSABLE_ROOT) for start in starts):
                deny(f"find {argument} {command[0]} changes files outside {DISPOSABLE_ROOT}, which can't be checked per file. Supported: the same under {DISPOSABLE_ROOT}, or the program with literal paths")


def check_codesign(arguments):
    for index, argument in enumerate(arguments):
        if argument in ("-s", "--sign") or re.match(r"^-[A-Za-z]*s$", argument):
            identity = arguments[index + 1] if index + 1 < len(arguments) else ""
        elif argument.startswith("--sign="):
            identity = argument.partition("=")[2]
        else:
            continue
        if identity != "-":
            deny(f"codesign with identity '{identity}' would sign with the operator's keychain certificates. Supported: codesign -s - (ad hoc), codesign -d / --verify to inspect")


def check_git_push(arguments):
    positional = []
    for argument in arguments:
        if argument.startswith("--force-with-lease") or argument.startswith("--force-if-includes"):
            continue
        if argument in ("--force", "--mirror", "--all", "--prune", "--delete"):
            deny(f"git push {argument} can overwrite or delete remote branches in bulk. Supported: git push fork <branch>, and --force-with-lease=<branch>:<sha> for rewritten fork branches")
        if re.match(r"^-[A-Za-z]+$", argument) and set(argument[1:]) & {"f", "d"}:
            deny(f"git push {argument} forces or deletes. Supported: git push fork <branch>, and --force-with-lease=<branch>:<sha> for rewritten fork branches")
        if not argument.startswith("-"):
            positional.append(argument)
    if len(positional) < 2:
        deny("git push without an explicit remote and branch depends on config and may hit upstream. Supported: git push fork <branch>")
    remote = positional[0]
    fork_url = GIT_URL.match(remote) and (repository_slug(remote) or "").startswith(FORK_OWNER.lower() + "/")
    if remote != PERSONAL_FORK_REMOTE and not fork_url:
        deny(f"git push to {remote}: pushes go only to the fork; upstream changes go through the operator. Supported: git push fork <branch>, then gh pr create -R {FORK_OWNER}/<repo>")
    for refspec in positional[1:]:
        if refspec.startswith("+") or refspec.startswith(":"):
            deny(f"git push refspec '{refspec}' forces (+) or deletes (:) a remote ref. Supported: plain <branch> or <local>:<remote> refspecs, --force-with-lease for rewrites")


SAFE_GIT_CONFIG_OVERRIDE = re.compile(r"^(user\.(email|name)|core\.pager|color\.[\w.]+|advice\.\w+)=")


def repository_slug(url):
    match = re.match(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url, re.IGNORECASE)
    return f"{match.group(1)}/{match.group(2)}".lower() if match else None


def check_git_url(url):
    if repository_slug(url) not in RELATED_REPOSITORIES:
        deny(f"git may only talk to Fabric-related GitHub repos, not {url}. Supported: {', '.join(sorted(RELATED_REPOSITORIES))}, via the origin/fork remotes or their GitHub URLs")


def git_common_directory(path):
    # Walks up to the .git entry; a worktree or submodule .git file points at its gitdir, which may name a commondir.
    while True:
        entry = os.path.join(path, ".git")
        if os.path.isdir(entry):
            return os.path.realpath(entry)
        if os.path.isfile(entry):
            try:
                with open(entry) as handle:
                    pointer = handle.read().strip().removeprefix("gitdir:").strip()
                git_directory = os.path.realpath(os.path.join(path, pointer))
                with open(os.path.join(git_directory, "commondir")) as handle:
                    return os.path.realpath(os.path.join(git_directory, handle.read().strip()))
            except FileNotFoundError:
                return git_directory
            except OSError:
                return None
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def check_git_repository(working_directory, git_directory):
    common = git_directory or git_common_directory(working_directory)
    if not common or not any(is_within(common, root) for root in RELATED_GIT_DIRECTORIES):
        deny(f"git in {working_directory} is outside this work's repos. Supported: the Fabric checkout, its worktrees (git worktree add under {DISPOSABLE_ROOT}) and submodules, and Fabric-Samples")


def check_gitmodules(working_directory):
    # submodule init/update/sync copy URLs from .gitmodules, which a PR can change.
    try:
        with open(os.path.join(working_directory, ".gitmodules")) as handle:
            urls = re.findall(r"^\s*url\s*=\s*(\S+)", handle.read(), re.MULTILINE)
    except OSError:
        return
    for url in urls:
        check_git_url(url)


def check_git(tokens, working_directory):
    index = 1
    git_directory = None
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] in ("--git-dir", "--work-tree") or tokens[index].startswith(("--git-dir=", "--work-tree=")):
            value = tokens[index].partition("=")[2] or (tokens[index + 1] if index + 1 < len(tokens) else "")
            if tokens[index].startswith("--git-dir"):
                git_directory = resolve(value, working_directory)
            else:
                work_tree = resolve(value, working_directory)
                if not any(work_tree.startswith(root) if root.endswith("-") else is_within(work_tree, root) for root in BOT_TREE_ROOTS):
                    deny(f"git --work-tree {work_tree} would write files outside the bot's trees. Supported: work trees under the Fabric checkout, Fabric-* worktrees or {DISPOSABLE_ROOT}; prefer git worktree add")
        if tokens[index] == "-c" and not SAFE_GIT_CONFIG_OVERRIDE.match(tokens[index + 1] if index + 1 < len(tokens) else ""):
            deny(f"git -c {tokens[index + 1] if index + 1 < len(tokens) else ''} can change what git runs or where it connects. Supported: -c user.email/user.name, core.pager, color.*, advice.*")
        if tokens[index].startswith("--exec-path") or tokens[index].startswith("--config-env"):
            deny(f"git {tokens[index]} can change what git runs. Supported: plain git subcommands")
        if tokens[index] == "-C" and index + 1 < len(tokens):
            working_directory = resolve(tokens[index + 1], working_directory)
        index += 2 if tokens[index] in GIT_OPTIONS_WITH_VALUE else 1
    if index >= len(tokens):
        return
    subcommand, arguments = tokens[index], tokens[index + 1:]
    for argument in arguments:
        value = argument.partition("=")[2] if argument.startswith("--") else argument
        if GIT_URL.match(value):
            check_git_url(value)
    if subcommand in ("clone", "init"):
        deny(f"git {subcommand} would create a repo outside the Fabric checkout. Supported: git fetch into the existing checkout, then git worktree add under {DISPOSABLE_ROOT}")
    if subcommand in GIT_REMOTE_SUBCOMMANDS:
        positional = [a for a in arguments if not a.startswith("-")]
        # A path as the remote reads another repository on disk.
        if positional and not GIT_URL.match(positional[0]) and ("/" in positional[0] or positional[0].startswith(".")):
            deny(f"git {subcommand} {positional[0]} would read or write another repository on disk. Supported: remotes origin and fork, or Fabric-related GitHub URLs")
    if subcommand == "config" and not any(a in GIT_CONFIG_READ_FLAGS for a in arguments):
        if any(GIT_CONFIG_DANGEROUS_KEY.match(a) for a in arguments if not a.startswith("-")):
            deny("git config of remote, url, submodule, include, core, credential, alias, filter, diff, merge or gpg keys can redirect git or make it run programs. Supported: reading any key (--get, --list), setting user.* and similar local keys, git remote add with a Fabric-related URL")
    check_git_repository(working_directory, git_directory)
    if subcommand == "submodule" and any(a in ("init", "update", "sync", "add") for a in arguments):
        check_gitmodules(working_directory)
    if subcommand == "push":
        check_git_push(arguments)
    if subcommand == "branch" and any(a in ("-D", "--delete") or (a.startswith("-") and "D" in a[1:] and not a.startswith("--")) for a in arguments):
        if any(a in PROTECTED_BRANCHES for a in arguments):
            deny("deleting main/master is not allowed: other work branches from them. Supported: git branch -D of review/feature branches such as pr-<n>")
    if subcommand == "credential":
        deny("git credential can print stored tokens. Supported: nothing; git and gh already authenticate on their own")
    if subcommand == "config" and any(a in ("--global", "--system") for a in arguments):
        deny(f"git config --global/--system changes the operator's machine-wide git setup. Supported: repo-local config, or -c user.email={COMMIT_EMAIL} per command")
    # Stashes are shared by every worktree of a repo, including the operator's.
    if subcommand == "stash" and arguments[:1] in (["drop"], ["clear"]):
        deny(f"git stash {arguments[0]} would discard stashes, which every worktree shares with the operator's checkout. Supported: git stash push/list/show/apply/pop")
    discards_work = (subcommand == "reset" and "--hard" in arguments) or subcommand == "clean"
    if subcommand == "checkout":
        # A path, not a branch, overwrites working tree files.
        discards_work = discards_work or any(
            a in DISCARDING_CHECKOUT_FLAGS or re.match(r"^-[A-Za-z]*[fBpm]", a) and not a.startswith("--")
            or not a.startswith("-") and os.path.exists(resolve(a, working_directory)) for a in arguments)
    if subcommand == "switch":
        discards_work = discards_work or any(a in DISCARDING_SWITCH_FLAGS or re.match(r"^-[A-Za-z]*[fCm]", a) and not a.startswith("--") for a in arguments)
    if subcommand == "restore":
        staged_only = any(a in ("--staged", "-S") for a in arguments) and not any(a in ("--worktree", "-W") or re.match(r"^-[A-Za-z]*W", a) and not a.startswith("--") for a in arguments)
        discards_work = discards_work or not staged_only
    if discards_work and not is_within(working_directory, DISPOSABLE_ROOT):
        deny(f"git {subcommand} {' '.join(arguments)} in {working_directory} would discard uncommitted work outside the bot's own worktrees. Supported: the same command in a worktree under {DISPOSABLE_ROOT}")
    if subcommand == "worktree" and arguments[:1] == ["remove"]:
        for target in [a for a in arguments[1:] if not a.startswith("-")]:
            if not is_within(resolve(target, working_directory), DISPOSABLE_ROOT):
                deny(f"git worktree remove {target} would delete a worktree the bot did not create. Supported: removing worktrees under {DISPOSABLE_ROOT}")
            if is_within(resolve(target, working_directory), WARM_ROOT):
                deny(f"git worktree remove {target} would delete the warm main tree. Supported: {WARM_ROUTE}")


def github_owner(repository):
    # Accepts OWNER/REPO, HOST/OWNER/REPO and https:// URLs.
    path = re.sub(r"^(https?://)?github\.com/", "", repository.lstrip("="))
    return path.split("/", 1)[0].lower()


def check_gh_fork_target(group, arguments):
    # Without -R, gh picks the repo from the checkout's remotes, which may be upstream.
    subcommand = None
    repositories = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in GH_REPO_FLAGS:
            repositories.append(arguments[index + 1] if index + 1 < len(arguments) else "")
            index += 2
            continue
        if argument.startswith("--repo="):
            repositories.append(argument.removeprefix("--repo="))
        elif argument.startswith("-R") and len(argument) > 2:
            repositories.append(argument[2:])
        elif subcommand is None and not argument.startswith("-"):
            subcommand = argument
        index += 1
    if subcommand not in FORK_ONLY_GH_SUBCOMMANDS[group]:
        return
    fork_only = f"gh {group} {subcommand} writes must go to the fork, never upstream (the operator carries work over). Supported: -R {FORK_OWNER}/<repo>, with no PR/issue URL pointing elsewhere"
    if not repositories:
        deny(fork_only)
    # A PR or issue URL argument overrides -R.
    item_urls = [a for a in arguments if GITHUB_ITEM_URL.match(a)]
    if any(github_owner(target) != FORK_OWNER for target in repositories + item_urls):
        deny(fork_only)


def parse_gh_api(arguments):
    options = []
    positionals = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        name, separator, inline_value = argument.partition("=")
        if separator and name in GH_API_OPTIONS_WITH_VALUE:
            options.append((name, inline_value))
        elif argument in GH_API_OPTIONS_WITH_VALUE:
            options.append((argument, arguments[index + 1] if index + 1 < len(arguments) else ""))
            index += 1
        elif re.match(r"^-[XHfFqtp].", argument):
            options.append((argument[:2], argument[2:]))
        elif not argument.startswith("-"):
            positionals.append(argument)
        index += 1
    return options, positionals


def check_gh_api(arguments):
    options, positionals = parse_gh_api(arguments)
    endpoint = positionals[0] if positionals else ""
    fields = [(name, value) for name, value in options if name in GH_API_FIELD_OPTIONS]
    if endpoint == "graphql":
        if any(name == "--input" or "mutation" in value.lower() for name, value in fields):
            deny(f"gh api graphql mutations and --input can write anywhere. Supported: read-only queries passed with -f/-F; writes go through gh pr/issue -R {FORK_OWNER}/<repo> or gh api repos/{FORK_OWNER}/...")
        return
    methods = [value.upper() for name, value in options if name in ("-X", "--method")]
    method = methods[-1] if methods else ("POST" if fields else "GET")
    if method in ("GET", "HEAD"):
        return
    if not FORK_API_WRITE_ENDPOINT.match(endpoint) or re.search(r"/merge\b", endpoint):
        deny(f"gh api write to {endpoint} is outside the fork's PRs and issues. Supported: non-GET calls to repos/{FORK_OWNER}/<repo>/pulls/... and .../issues/... (no merge); GET anything on Fabric-related repos")


def check_gh_related_repositories(tokens):
    arguments = tokens[1:]
    targets = []
    for index, argument in enumerate(arguments):
        if argument in GH_REPO_FLAGS and index + 1 < len(arguments):
            targets.append(arguments[index + 1])
        elif argument.startswith("--repo="):
            targets.append(argument.removeprefix("--repo="))
        elif re.match(r"^-R[^-]", argument):
            targets.append(argument[2:])
        elif re.match(r"^(https?://)?github\.com/", argument):
            targets.append("/".join(re.sub(r"^(https?://)?github\.com/", "", argument).split("/")[:2]))
        elif re.match(r"^/?repos/[^/]+/[^/?]+", argument):
            targets.append("/".join(argument.lstrip("/").split("/")[1:3]).split("?")[0])
    words = [t for t in arguments if not t.startswith("-")]
    if words[:1] == ["repo"] and len(words) > 2 and "/" in words[2]:
        targets.append(words[2])
    for target in targets:
        slug = target.removeprefix("github.com/").removesuffix(".git").lower()
        if slug not in RELATED_REPOSITORIES:
            deny(f"gh may only target Fabric-related repos, not {target}. Supported: {', '.join(sorted(RELATED_REPOSITORIES))}")


def gist_description(gist_id):
    import subprocess
    try:
        result = subprocess.run(["gh", "api", f"gists/{gist_id}", "--jq", ".description"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def check_gist_upload_path(path, working_directory):
    # gh reads files itself, so Read rules don't stop it from publishing secrets.
    if not is_within(resolve(path, working_directory), DISPOSABLE_ROOT):
        deny(f"gist file {path} is outside {DISPOSABLE_ROOT}; gists are link-readable, so only report files written to the scratch area may go in. Supported: " + GIST_ROUTE)
    check_shared_file(resolve(path, working_directory))


def read_text(path):
    try:
        with open(path, errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def distinctive_lines(text):
    lines = (re.sub(r"^\s*(?:[-*|>]|\d+\.)\s*", "", line).strip() for line in text.splitlines())
    return {line for line in lines if len(line) >= 40}


def private_instruction_lines():
    # Template lines without placeholders read the same filled in, so only filled-in lines reveal configuration.
    template = read_text(BOT_TEMPLATE)
    filled = PLACEHOLDER_PATTERN.sub(lambda match: str(CONFIG.get(match.group(1), match.group(0))), template)
    return distinctive_lines(filled) - distinctive_lines(template), set().union(*(distinctive_lines(read_text(path)) for path in CLAUDE_MD_FILES))


def check_shared_text(text):
    if not text:
        return
    if SECRET_PATTERN.search(text):
        deny(SECRET_DENIAL)
    filled_lines, claude_lines = private_instruction_lines()
    if sum(line in text for line in filled_lines) >= 2 or sum(line in text for line in claude_lines) >= 3:
        deny(PRIVATE_INSTRUCTIONS_DENIAL)


def check_shared_file(path):
    if path == os.path.realpath(BOT_TEMPLATE):
        return
    if touches_discord_state(path):
        deny(DISCORD_STATE_DENIAL)
    if os.path.basename(path).lower() == "claude.md" or is_within(path, CONFIG["BOT_DIRECTORY"]) or is_within(path, os.path.join(CONFIG["HOME"], ".claude")):
        deny(PRIVATE_INSTRUCTIONS_DENIAL + f" ({path})")
    check_shared_text(read_text(path))


def check_discord(tool, tool_input):
    if tool not in DISCORD_SENDING_TOOLS:
        return
    check_shared_text(tool_input.get("text", ""))
    for raw in tool_input.get("files") or []:
        # The plugin reads attachments itself, past the Read rules.
        path = os.path.realpath(os.path.expanduser(str(raw)))
        if path != os.path.realpath(BOT_TEMPLATE) and not in_bot_trees(path):
            deny(f"attachment {raw} is outside the bot's trees. Supported: attach files from the Fabric checkouts, Fabric-* worktrees or {DISPOSABLE_ROOT} (copy a report there first), or the BOT.md template")
        check_shared_file(path)


def check_gh_gist(arguments, working_directory):
    subcommand = arguments[0] if arguments else ""
    if "--help" in arguments:
        return
    if "-w" in arguments or "--web" in arguments:
        deny("gh gist --web would open a browser on the operator's desktop. Supported: gh gist view <id> --raw")
    if subcommand in GIST_READ_ONLY_SUBCOMMANDS:
        return
    if subcommand not in ("create", "new", "edit"):
        deny(f"gh gist {subcommand} is not part of the report workflow (no delete, clone or rename). Supported: " + GIST_ROUTE)
    options = {}
    positionals = []
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        name, separator, inline_value = argument.partition("=")
        if name in ("-d", "--desc", "-a", "--add", "-f", "--filename", "-r", "--remove") and (separator or index + 1 < len(arguments)):
            value = inline_value if separator else arguments[index + 1]
            options.setdefault(name.lstrip("-")[:1] if len(name) > 2 else name[1], []).append(value)
            index += 1 if separator else 2
            continue
        if argument in ("-p", "--public", "-w", "--web") or argument.startswith("--public"):
            deny("report gists stay secret (unlisted, readable by anyone with the link) and the bot opens no browser. Supported: " + GIST_ROUTE)
        if argument.startswith("-") and argument != "-":
            deny(f"gh gist option {argument} is not part of the report workflow. Supported: " + GIST_ROUTE)
        positionals.append(argument)
        index += 1
    for description in options.get("d", []):
        if not description.startswith(GIST_MARKER):
            deny(f"gist descriptions must start with '{GIST_MARKER}' so the workflow can find them again. Supported: " + GIST_ROUTE)
    if subcommand in ("create", "new"):
        if not options.get("d"):
            deny(f"gh gist create needs --desc '{GIST_MARKER}...'. Supported: " + GIST_ROUTE)
        if not positionals or "-" in positionals:
            deny("gh gist create needs report files from the scratch area, not stdin. Supported: " + GIST_ROUTE)
        for path in positionals:
            check_gist_upload_path(path, working_directory)
        return
    if not positionals:
        deny("gh gist edit needs a gist id or URL. Supported: " + GIST_ROUTE)
    match = GIST_ID_OR_URL.match(positionals[0])
    if not match:
        deny(f"{positionals[0]} is not a gist id or gist.github.com URL. Supported: " + GIST_ROUTE)
    local_files = positionals[1:]
    if options.get("f") and not local_files:
        deny("gh gist edit --filename without a local file opens an editor, which hangs an unattended session. Supported: --filename <name> <local file>")
    if not (options.get("d") or options.get("a") or options.get("r") or local_files):
        deny("gh gist edit with no change opens an editor, which hangs an unattended session. Supported: " + GIST_ROUTE)
    for path in options.get("a", []) + local_files:
        check_gist_upload_path(path, working_directory)
    description = gist_description(match.group(3))
    if description is None:
        deny(f"couldn't confirm gist {match.group(3)} exists and belongs to the fork account. Supported: retry; find report gists with gh gist list --limit 100 --filter '\\[fabric-bot\\]'")
    if not description.startswith(GIST_MARKER):
        deny(f"gist {match.group(3)} wasn't created by the report workflow (description lacks '{GIST_MARKER.strip()}'). Supported: " + GIST_ROUTE)


def check_gh_host(arguments):
    for index, argument in enumerate(arguments):
        if argument == "--hostname" or argument.startswith("--hostname="):
            value = argument.partition("=")[2] if "=" in argument else (arguments[index + 1] if index + 1 < len(arguments) else "")
            if value.lower() != "github.com":
                deny(GH_HOST_DENIAL)
        match = GH_URL_HOST.match(argument)
        if match and match.group(1).lower().rsplit("@", 1)[-1] not in GH_ALLOWED_HOSTS:
            deny(GH_HOST_DENIAL)


def check_gh_auth(arguments):
    words = [a for a in arguments if not a.startswith("-")]
    if words[:1] != ["status"] or any(a in ("-t", "--show-token") or re.match(r"^-[A-Za-z]*t", a) for a in arguments):
        deny(GH_AUTH_DENIAL)


def check_gh_uploads(tokens, working_directory):
    """Files gh sends as bodies or fields, which gh reads itself past the Read rules."""
    words = [t for t in tokens[1:] if not t.startswith("-")]
    paths = []
    if words[:1] == ["api"]:
        options, _ = parse_gh_api(tokens[1:])
        paths += [value for name, value in options if name == "--input"]
        paths += [value.partition("=@")[2] for name, value in options if name in ("-F", "--field") and "=@" in value]
    elif words[:1] in (["pr"], ["issue"], ["release"]):
        for index, token in enumerate(tokens):
            if token in ("-F", "--body-file", "--notes-file") and index + 1 < len(tokens):
                paths.append(tokens[index + 1])
            elif token.startswith(("--body-file=", "--notes-file=")):
                paths.append(token.partition("=")[2])
    for raw in paths:
        if raw in ("", "-"):
            continue
        path = resolve(raw, working_directory)
        if not in_bot_trees(path):
            deny(f"gh would upload {raw}, which is outside the bot's trees. Supported: write the body under {DISPOSABLE_ROOT} first, then pass that file")
        check_shared_file(path)


def check_gh(tokens, working_directory):
    if SECRET_PATTERN.search(" ".join(tokens)):
        deny(SECRET_DENIAL)
    check_gh_uploads(tokens, working_directory)
    check_gh_host(tokens[1:])
    check_gh_related_repositories(tokens)
    words = [t for t in tokens[1:] if not t.startswith("-")]
    for denied in DENIED_GH:
        if tuple(words[:len(denied)]) == denied:
            deny(f"gh {' '.join(denied)} is not allowed: it merges, destroys repos/releases, or touches auth or secrets. Supported: read-only gh, and pr/issue writes on the fork; ask the operator for the rest")
    # Second position covers a repo flag placed before the command group.
    for group in FORK_ONLY_GH_SUBCOMMANDS:
        if group in words[:2]:
            arguments = tokens[1:]
            arguments.remove(group)
            check_gh_fork_target(group, arguments)
            break
    if words[:1] == ["gist"]:
        arguments = tokens[1:]
        arguments.remove("gist")
        check_gh_gist(arguments, working_directory)
    if words[:1] == ["api"]:
        arguments = tokens[1:]
        arguments.remove("api")
        check_gh_api(arguments)
    if words[:1] == ["auth"]:
        arguments = tokens[1:]
        arguments.remove("auth")
        check_gh_auth(arguments)


def file_mentions(path, pattern):
    try:
        with open(path, errors="ignore") as handle:
            return bool(pattern.search(handle.read(4_000_000)))
    except OSError:
        return False


def check_script_code(tokens, working_directory):
    program = tokens[0].rsplit("/", 1)[-1]
    if program == "swift" and len(tokens) > 1 and tokens[1] in SWIFT_BUILD_SUBCOMMANDS:
        return
    files = [(index, argument, resolve(argument, working_directory)) for index, argument in enumerate(tokens)
             if not argument.startswith("-") and os.path.isfile(resolve(argument, working_directory))]
    script_index = next((index for index, _, _ in files if index > 0), None)
    for index, argument, path in files:
        # Reports and data a script reads run nothing; a prose file given as the script still counts.
        if index not in (0, script_index) and os.path.splitext(path)[1].lower() in PROSE_EXTENSIONS:
            continue
        if file_mentions(path, DISCORD_STATE_PATTERN):
            deny(DISCORD_STATE_DENIAL + f" ({argument} names it)")


def compiles(program, tokens):
    if program == "swift":
        return len(tokens) >= 2 and tokens[1] in SWIFT_COMPILING_SUBCOMMANDS and "--help" not in tokens
    return program == "xcodebuild" and not XCODEBUILD_NON_BUILDING_FLAGS & set(tokens)


LOGGED_JOBS = None


def logged_jobs():
    global LOGGED_JOBS
    if LOGGED_JOBS is None:
        LOGGED_JOBS = set()
        for path in (CONFIG["JOBS_FILE"], CONFIG["JOBS_LOCAL_FILE"]):
            for line in read_text(path).splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("event") == "start":
                    LOGGED_JOBS.add(event.get("id"))
    return LOGGED_JOBS


def check_job_tag(value):
    if not JOB_ID.fullmatch(value) or value not in logged_jobs():
        deny(f"{JOB_TAG}={value} is not a logged job. Supported: " + JOB_TAG_ROUTE)


def segment_job_tag(segment):
    """The FABRIC_JOB value assigned in front of the segment's program, or None."""
    for token in segment:
        if token in ("command", "builtin", "nohup", "time", "nice", "env", "exec"):
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            break
        if token.startswith(JOB_TAG + "="):
            return token.split("=", 1)[1]
    return None


def build_job_count(tokens, flags):
    for index, token in enumerate(tokens):
        for flag in flags:
            if token == flag and index + 1 < len(tokens):
                return tokens[index + 1]
            if token.startswith(flag + "="):
                return token.split("=", 1)[1]
            if flag == "-j" and token.startswith("-j") and token[2:].isdigit():
                return token[2:]
    return None


PROC_PIDTBSDINFO, PROC_BSDINFO_SIZE, PROC_BSDINFO_PARENT_OFFSET = 3, 136, 16
PROC_PIDVNODEPATHINFO, PROC_VNODEPATHINFO_SIZE, PROC_VNODEPATHINFO_CWD_OFFSET = 9, 2352, 152
CTL_KERN, KERN_PROCARGS2 = 1, 49
MAXIMUM_PATH_LENGTH = 1024


LIBRARY = None


def system_library():
    """ctypes, libc and a KERN_PROCARGS2 buffer, loaded on first use."""
    global LIBRARY
    if LIBRARY is None:
        import ctypes
        LIBRARY = ctypes, ctypes.CDLL(None, use_errno=True), ctypes.create_string_buffer(1 << 20)
    return LIBRARY


def process_ids():
    ctypes, libc, _ = system_library()
    count = libc.proc_listallpids(None, 0)
    buffer = (ctypes.c_int * (count + 64))()
    count = libc.proc_listallpids(buffer, ctypes.sizeof(buffer))
    return buffer[:max(count, 0)]


def process_parent(pid):
    ctypes, libc, _ = system_library()
    info = ctypes.create_string_buffer(PROC_BSDINFO_SIZE)
    if libc.proc_pidinfo(pid, PROC_PIDTBSDINFO, ctypes.c_uint64(0), info, PROC_BSDINFO_SIZE) != PROC_BSDINFO_SIZE:
        return None
    return int.from_bytes(info.raw[PROC_BSDINFO_PARENT_OFFSET:PROC_BSDINFO_PARENT_OFFSET + 4], "little")


def process_arguments_raw(pid):
    ctypes, libc, buffer = system_library()
    name = (ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid)
    size = ctypes.c_size_t(ctypes.sizeof(buffer))
    if libc.sysctl(name, 3, buffer, ctypes.byref(size), None, 0) != 0 or size.value < 4:
        return None
    return ctypes.string_at(buffer, size.value)


def process_executable(pid):
    raw = process_arguments_raw(pid)
    return raw[4:].split(b"\0", 1)[0].decode(errors="replace") if raw else None


def process_arguments(pid):
    raw = process_arguments_raw(pid)
    if raw is None:
        return None
    argument_count = int.from_bytes(raw[:4], "little")
    # argc, the executable path, NUL padding, then argv.
    rest = raw[4:]
    rest = rest[rest.find(b"\0"):].lstrip(b"\0")
    return [argument.decode(errors="replace") for argument in rest.split(b"\0")[:argument_count]]


def process_directory(pid):
    ctypes, libc, _ = system_library()
    info = ctypes.create_string_buffer(PROC_VNODEPATHINFO_SIZE)
    if libc.proc_pidinfo(pid, PROC_PIDVNODEPATHINFO, ctypes.c_uint64(0), info, PROC_VNODEPATHINFO_SIZE) <= 0:
        return ""
    path = info.raw[PROC_VNODEPATHINFO_CWD_OFFSET:PROC_VNODEPATHINFO_CWD_OFFSET + MAXIMUM_PATH_LENGTH]
    return path.split(b"\0", 1)[0].decode(errors="replace")


def running_bot_builds():
    processes = {}
    for pid in process_ids():
        arguments = process_arguments(pid)
        if not arguments:
            continue
        tokens = " ".join(arguments).split()
        flags = BUILD_PROCESS_JOB_FLAGS.get(tokens[0].rsplit("/", 1)[-1]) if tokens else None
        if flags:
            processes[pid] = (process_parent(pid), tokens, flags)
    builds = []
    for pid, (parent, tokens, flags) in processes.items():
        if parent in processes:
            continue
        directory = process_directory(pid)
        # Arguments may spell the root /tmp/... or /private/tmp/...
        if not (is_within(directory, TASK_ROOT) or TASK_ROOT.removeprefix("/private") in " ".join(tokens)):
            continue
        count = build_job_count(tokens, flags)
        builds.append((pid, int(count) if count and count.isdigit() else MAXIMUM_BUILD_JOBS, directory))
    return builds


def check_build_jobs(program, tokens):
    if not compiles(program, tokens):
        return
    count = build_job_count(tokens, ("-j", "--jobs") if program == "swift" else ("-jobs",))
    if count is None or not count.isdigit() or not 1 <= int(count) <= MAXIMUM_BUILD_JOBS:
        deny(BUILD_JOBS_DENIAL)
    builds = running_bot_builds()
    used = sum(jobs for _, jobs, _ in builds)
    if used + int(count) > MAXIMUM_BUILD_JOBS:
        running = "; ".join(f"pid {pid}, {jobs} jobs, in {directory or 'unknown directory'}" for pid, jobs, directory in builds)
        spare = MAXIMUM_BUILD_JOBS - used
        deny(f"all bot builds together get {MAXIMUM_BUILD_JOBS} compile jobs, and {used} are taken by running builds ({running}). Supported: "
             + (f"run this one with {spare} jobs, or wait for those to finish" if spare > 0 else "wait for those to finish, then retry"))


def caller_identity(payload):
    # Subagent tool calls carry agent_id; the main thread's don't.
    return {"session": payload.get("session_id", ""), "agent": payload.get("agent_id", "")}


def read_editor_lock():
    try:
        with open(EDITOR_LOCK_HOLDER) as handle:
            holder = json.load(handle)
        if not isinstance(holder, dict):
            return None
        holder["idle"] = time.time() - os.path.getmtime(EDITOR_LOCK_HOLDER)
    except (OSError, ValueError):
        return None
    try:
        with open(EDITOR_LOCK_TASK) as handle:
            holder["task"] = handle.read().strip()[:300]
    except OSError:
        holder["task"] = ""
    return holder


def holds_editor_lock(holder, caller):
    return isinstance(holder, dict) and holder.get("session") == caller["session"] and holder.get("agent", "") == caller["agent"]


def session_running(session_id):
    if not os.path.isdir(SESSION_REGISTRY):
        # No registry to consult: only the idle limit applies.
        return True
    import glob
    for path in glob.glob(os.path.join(SESSION_REGISTRY, "*.json")):
        try:
            with open(path) as handle:
                entry = json.load(handle)
            if entry.get("sessionId") == session_id:
                os.kill(int(entry["pid"]), 0)
                return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return False


def editor_lock_staleness(holder):
    if holder is None:
        return "it has no readable holder.json"
    if not session_running(holder.get("session", "")):
        return f"session {holder.get('session')} is no longer running"
    if holder["idle"] >= EDITOR_LOCK_STALE_SECONDS:
        return f"its holder has made no tool calls for {int(holder['idle'] // 60)} minutes"
    return None


def describe_editor_lock(holder):
    if holder is None:
        return f"{EDITOR_LOCK} exists without a readable holder"
    who = f"session {holder.get('session')}" + (f", agent {holder['agent']}" if holder.get("agent") else ", main thread")
    idle = int(holder["idle"])
    return f"held by {who}, for task '{holder.get('task') or 'unknown: no task.txt'}', since {holder.get('taken', '?')}; its last tool call was {idle // 60} min {idle % 60} s ago"


def touch_editor_lock(caller):
    try:
        with open(EDITOR_LOCK_HOLDER) as handle:
            holder = json.load(handle)
        if holds_editor_lock(holder, caller):
            os.utime(EDITOR_LOCK_HOLDER)
    except (OSError, ValueError):
        pass


def take_editor_lock(caller):
    try:
        os.makedirs(os.path.dirname(EDITOR_LOCK), exist_ok=True)
        os.mkdir(EDITOR_LOCK)
    except FileExistsError:
        holder = read_editor_lock()
        if holds_editor_lock(holder, caller):
            return
        stale = editor_lock_staleness(holder)
        if stale:
            deny(f"the Editor VM lock is stale: {stale}. It was {describe_editor_lock(holder)}. Supported: break it with rm -r {EDITOR_LOCK}, tell that task's requester their VM session was ended, then mkdir -p {EDITOR_LOCK} again")
        deny(f"the Editor VM is in use, {describe_editor_lock(holder)}. The lock goes stale after {EDITOR_LOCK_STALE_SECONDS // 60} minutes without tool calls from its holder, or when the holder's session ends. Supported: tell the requester the VM is busy, keep doing work that doesn't need the Editor, and retry mkdir -p later")
    except OSError as error:
        deny(f"could not create {EDITOR_LOCK}: {error}")
    with open(EDITOR_LOCK_HOLDER, "w") as handle:
        json.dump({**caller, "taken": time.strftime("%Y-%m-%d %H:%M:%S")}, handle)


def check_mkdir(arguments, working_directory, caller):
    parents = any(a in ("-p", "--parents") or re.match(r"^-[A-Za-z]*p", a) for a in arguments)
    for target in (a for a in arguments if not a.startswith("-")):
        path = resolve(target, working_directory)
        if path == EDITOR_LOCK:
            if not parents:
                deny(f"take the Editor VM lock with mkdir -p, which succeeds when you already hold it. Supported: {EDITOR_LOCK_ROUTE}")
            take_editor_lock(caller)
        elif is_within(path, EDITOR_LOCK):
            deny(f"{EDITOR_LOCK} is the Editor VM lock; only task.txt belongs in it. Supported: {EDITOR_LOCK_ROUTE}")


def check_editor_lock_removal(path, caller):
    if not (is_within(path, EDITOR_LOCK) or is_within(EDITOR_LOCK, path)) or not os.path.isdir(EDITOR_LOCK):
        return
    holder = read_editor_lock()
    if holds_editor_lock(holder, caller) or editor_lock_staleness(holder):
        return
    deny(f"the Editor VM lock belongs to another task, {describe_editor_lock(holder)}. Supported: wait until it is released or goes stale ({EDITOR_LOCK_STALE_SECONDS // 60} minutes without tool calls, or its session ends); the operator can remove it by hand")


def check_editor_lock(caller, action="using it"):
    if not holds_editor_lock(read_editor_lock(), caller):
        deny(f"the Editor VM desktop is shared by every task, so {action} needs its lock, which this {'agent' if caller['agent'] else 'thread'} doesn't hold. Supported: {EDITOR_LOCK_ROUTE}")


def is_editor_process(pid):
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 and (process_executable(pid) or "").endswith(EDITOR_EXECUTABLE_SUFFIX)


def check_driver_target(arguments, tool):
    """Whether one call's (or one run_steps step's) arguments aim at the Editor. Returns True when they name it."""
    driver_route = "Supported: the Editor's pid (pgrep -x \"Fabric Editor\") with its window_id from list_windows, element tokens from get_window_state of its windows, or app \"Fabric Editor\" in run_steps"
    target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
    if arguments.get("scope") == "desktop" or target.get("kind") == "desktop":
        deny(f"vm-driver {tool} with a desktop scope or target reaches whatever app is in front, such as a Terminal that would run commands past the guard. " + driver_route)
    named = False
    for pid in (arguments.get("pid"), target.get("pid")):
        if pid is None:
            continue
        if not is_editor_process(pid):
            deny(f"vm-driver {tool} targets pid {pid}, which is not a running Fabric Editor; driving other apps (Terminal, System Settings) would act past the guard. " + driver_route)
        named = True
    app = arguments.get("app")
    if app is not None:
        if str(app).strip().lower() not in EDITOR_APP_NAMES:
            deny(f"vm-driver {tool} names app '{app}'; only the Fabric Editor may be driven. " + driver_route)
        named = True
    return named or bool(arguments.get("element_token"))


def check_driver_paths(value, tool):
    # Screenshot outputs and clipboard sources are files the driver opens itself.
    if isinstance(value, list):
        for item in value:
            check_driver_paths(item, tool)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if isinstance(item, str) and VM_DRIVER_PATH_KEY.search(key):
            path = os.path.realpath(os.path.expanduser(item))
            if touches_discord_state(path):
                deny(DISCORD_STATE_DENIAL)
            if any(is_within(path, protected) for protected in PROTECTED_REAL_PATHS):
                deny(PROTECTED_REAL_PATH_DENIAL + f" ({item})")
            if not in_bot_trees(path):
                deny(f"vm-driver {tool} {key} {item} is outside the bot's trees. Supported: files under {DISPOSABLE_ROOT} (screenshots go in the task folder), the Fabric checkout or Fabric-* worktrees")
            if "out" in key:
                check_persistent_write(path)
        else:
            check_driver_paths(item, tool)


def check_launch_app(tool_input):
    route = f"Supported: open the built app ({OPEN_EDITOR_ROUTE}), or launch_app with bundle_id {EDITOR_BUNDLE_ID} or name \"Fabric Editor\""
    bundle, name = tool_input.get("bundle_id"), tool_input.get("name")
    if bundle is not None and bundle != EDITOR_BUNDLE_ID:
        deny(f"launch_app may start only the Fabric Editor, not {bundle}. " + route)
    if bundle is None:
        if name is None:
            deny("launch_app needs the Editor's bundle_id or name. " + route)
        path = os.path.realpath(os.path.expanduser(str(name)))
        is_bundle_path = str(name).rstrip("/").endswith("Fabric Editor.app") and in_bot_trees(path)
        if str(name).strip().lower() not in EDITOR_APP_NAMES and not is_bundle_path:
            deny(f"launch_app may start only the Fabric Editor, not {name}. " + route)
    if tool_input.get("webkit_inspector_port") is not None:
        deny("launch_app webkit_inspector_port opens a debugging server. " + route)
    for url in tool_input.get("urls") or []:
        path = os.path.realpath(os.path.expanduser(str(url)))
        if re.match(r"^[a-z][a-z0-9+.-]*:", str(url), re.IGNORECASE) or not str(url).endswith(".fabric") or not in_bot_trees(path):
            deny(f"launch_app may open only .fabric compositions under the bot's trees, not {url}. " + route)


def check_vm_driver(tool, tool_input, caller):
    if tool not in VM_DRIVER_TOOLS:
        deny(f"vm-driver tool {tool} is outside the bot's GUI work (driver config, recordings, browsers, scripts, sessions, killing apps). Supported: {', '.join(sorted(VM_DRIVER_TOOLS))}")
    check_driver_paths(tool_input, tool)
    if tool == "launch_app":
        check_launch_app(tool_input)
    elif tool == "run_steps":
        default_named = check_driver_target(tool_input, tool)
        for step in tool_input.get("steps") or []:
            if not isinstance(step, dict):
                deny("run_steps steps must be objects")
            if "tool" in step:
                name, arguments = step.get("tool"), step.get("args") or {}
            else:
                actions = [key for key in step if key in VM_DRIVER_STEP_TOOLS]
                name, arguments = (actions[0], step[actions[0]]) if len(actions) == 1 else (None, {})
                if not actions and not ({"wait_for", "expect"} & set(step)):
                    deny(f"run_steps step {json.dumps(step)[:200]} names no action the guard knows. Supported: {', '.join(sorted(VM_DRIVER_STEP_TOOLS))}")
            if name is not None and name not in VM_DRIVER_STEP_TOOLS:
                deny(f"run_steps step tool {name} is not an input action. Supported: {', '.join(sorted(VM_DRIVER_STEP_TOOLS))}")
            if not isinstance(arguments, dict):
                deny("run_steps step args must be an object")
            named = check_driver_target(arguments, f"run_steps {name}")
            for check in [step.get("wait_for"), *(step.get("expect") or [])]:
                if isinstance(check, dict):
                    check_driver_target(check, "run_steps check")
            if name not in (None, "move_cursor") and not (named or default_named):
                deny("run_steps step without pid, app or element token would act on whatever window is in front. Supported: pid or app \"Fabric Editor\" on run_steps or on each step")
    elif tool in ("get_window_state", "verify_state", "set_window_frame", "bring_to_front"):
        if tool_input.get("pid") is None:
            deny(f"vm-driver {tool} needs the Editor's pid. Supported: pgrep -x \"Fabric Editor\" for the pid, list_windows for its window_id")
        check_driver_target(tool_input, tool)
    elif tool in VM_DRIVER_INPUT_TOOLS:
        if not check_driver_target(tool_input, tool):
            deny(f"vm-driver {tool} without a pid or element token would act on whatever app is in front. Supported: the Editor's pid (pgrep -x \"Fabric Editor\") with its window_id, or an element token from get_window_state")
    else:
        check_driver_target(tool_input, tool)
    if tool not in VM_DRIVER_TOOLS_WITHOUT_LOCK:
        check_editor_lock(caller)


def check_open(arguments, working_directory, caller):
    targets, index, tagged = [], 0, False
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--args":
            break
        if argument in ("--env", "-env"):
            value = arguments[index + 1] if index + 1 < len(arguments) else ""
            if not value.startswith(JOB_TAG + "="):
                deny(f"open --env {value}: only {JOB_TAG} may be set. Supported: " + OPEN_EDITOR_ROUTE)
            check_job_tag(value.split("=", 1)[1])
            tagged = True
            index += 2
            continue
        if argument in ("-a", "--application"):
            if index + 1 >= len(arguments):
                deny("open -a needs an app. Supported: " + OPEN_EDITOR_ROUTE)
            application = resolve(arguments[index + 1], working_directory)
            if not (application.endswith("/Fabric Editor.app") and in_bot_trees(application)):
                deny(f"open -a {arguments[index + 1]}: only a Fabric Editor built in the bot's trees may be opened. Supported: " + OPEN_EDITOR_ROUTE)
            index += 2
            continue
        if argument.startswith("-"):
            if argument not in OPEN_FLAGS:
                deny(f"open {argument} can reach other apps, URLs or files. Supported: " + OPEN_EDITOR_ROUTE)
        else:
            targets.append(argument)
        index += 1
    if not targets and "-a" not in arguments and "--application" not in arguments:
        deny("open needs the Editor app or a composition. Supported: " + OPEN_EDITOR_ROUTE)
    for target in targets:
        path = resolve(target, working_directory)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or not in_bot_trees(path) or not (path.endswith("/Fabric Editor.app") or path.endswith(".fabric")):
            deny(f"open {target}: only a Fabric Editor built in the bot's trees, or a .fabric composition there, may be opened; other apps (Terminal, scripts) would run past the guard. Supported: " + OPEN_EDITOR_ROUTE)
    if not tagged:
        deny(JOB_TAG_DENIAL)
    check_editor_lock(caller, "opening the Editor")


def check_screencapture(arguments, working_directory):
    outputs, index = [], 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in SCREENCAPTURE_FLAGS_WITH_VALUE:
            index += 2
            continue
        if argument.startswith("-"):
            if argument not in SCREENCAPTURE_FLAGS:
                deny(f"screencapture {argument} is interactive, records video or audio, or hands the image to another app or the clipboard. Supported: " + SCREENCAPTURE_ROUTE)
        else:
            outputs.append(argument)
        index += 1
    if not outputs:
        deny("screencapture needs an output file. Supported: " + SCREENCAPTURE_ROUTE)
    for output in outputs:
        if not is_within(resolve(output, working_directory), DISPOSABLE_ROOT):
            deny(f"screencapture output {output} is outside {DISPOSABLE_ROOT}. Supported: " + SCREENCAPTURE_ROUTE)


def protected_processes():
    """The guard's ancestors (the session, tmux, launchd) and the bot's infrastructure."""
    pids, pid = set(), os.getpid()
    while pid and pid not in pids:
        pids.add(pid)
        pid = process_parent(pid)
    names = {}
    for pid in process_ids():
        arguments = process_arguments(pid) or []
        executable = (process_executable(pid) or (arguments[:1] or [""])[0]).rsplit("/", 1)[-1]
        names[pid] = (executable, " ".join(arguments))
        if executable in PROTECTED_PROCESS_NAMES or PROTECTED_PROCESS_ARGUMENTS.search(" ".join(arguments)):
            pids.add(pid)
    return pids, names


def check_kill(program, arguments, segment):
    if fed_by_xargs(segment):
        deny(f"{program} fed by xargs can't be checked. " + KILL_ROUTE)
    protected, names = protected_processes()
    if program == "kill":
        if "-l" in arguments:
            return
        index, targets = 0, []
        while index < len(arguments):
            argument = arguments[index]
            if argument in ("-s", "-n"):
                index += 2
                continue
            if not SIGNAL_FLAG.match(argument) and argument != "--":
                targets.append(argument)
            index += 1
        if not targets:
            deny("kill needs literal pids. " + KILL_ROUTE)
        for target in targets:
            if not target.isdigit() or int(target) <= 1:
                deny(f"kill {target}: only literal pids can be checked; process groups, 0, -1 and variables reach many processes. " + KILL_ROUTE)
            if int(target) in protected:
                deny(f"kill {target} would stop the session, the guard, tmux, the Discord plugin or the GUI driver. " + KILL_ROUTE)
        return
    flags = PKILL_FLAGS if program == "pkill" else KILLALL_FLAGS
    patterns = []
    for argument in arguments:
        if argument in flags or SIGNAL_FLAG.match(argument):
            continue
        if argument.startswith("-"):
            deny(f"{program} {argument} can't be checked. " + KILL_ROUTE)
        patterns.append(argument)
    if not patterns:
        deny(f"{program} needs a process name. " + KILL_ROUTE)
    regex = program == "pkill" or "-m" in arguments
    for pattern in patterns:
        if regex:
            try:
                compiled = re.compile(pattern, re.IGNORECASE if ("-i" in arguments or "-I" in arguments) else 0)
            except re.error:
                deny(f"{program} pattern {pattern} can't be checked. " + KILL_ROUTE)
            matches = (lambda text, compiled=compiled: bool(compiled.fullmatch(text) if "-x" in arguments else compiled.search(text)))
        else:
            matches = (lambda text, pattern=pattern: text == pattern)
        for name in PROTECTED_PROCESS_NAMES:
            if matches(name):
                deny(f"{program} {pattern} would also stop {name}: the session, tmux, the GUI driver or a system process. " + KILL_ROUTE)
        for pid in protected:
            executable, command_line = names.get(pid, ("", ""))
            if matches(executable) or (regex and command_line and matches(command_line)):
                deny(f"{program} {pattern} would also stop pid {pid} ({executable}): the session, the guard, tmux, the Discord plugin or the GUI driver. " + KILL_ROUTE)


def main():
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input", {})
    session_id = payload.get("session_id", "")
    tool_name = payload.get("tool_name", "Bash")
    caller = caller_identity(payload)
    touch_editor_lock(caller)
    if tool_name.startswith(VM_DRIVER_PREFIX):
        check_vm_driver(tool_name.removeprefix(VM_DRIVER_PREFIX), tool_input, caller)
        return
    if tool_name.startswith("mcp__cua__"):
        deny("the cua Spaces server is not part of the bot's setup. Supported: the mcp__vm-driver__* tools for the Editor on this VM's desktop")
    if tool_name.startswith("mcp__plugin_discord_discord__"):
        check_discord(tool_name.removeprefix("mcp__plugin_discord_discord__"), tool_input)
        return
    if tool_name == "Monitor":
        # Monitor runs its command in the same shell as Bash, so it gets the Bash checks; a WebSocket is a web fetch.
        if tool_input.get("ws"):
            deny(HTTP_FETCH_DENIAL)
        tool_name = "Bash"
    if tool_name.startswith("mcp__cua-driver__"):
        deny("cua-driver is reached only as mcp__vm-driver__*, which the guard checks. Supported: the mcp__vm-driver__* tools")
    if tool_name != "Bash":
        if tool_name in ("Write", "Edit", "NotebookEdit"):
            check_persistent_write(os.path.realpath(os.path.expanduser(tool_input.get("file_path") or tool_input.get("notebook_path") or "")))
            if os.path.realpath(os.path.expanduser(tool_input.get("file_path") or "")) == EDITOR_LOCK_HOLDER:
                deny(f"holder.json is written by the guard. Supported: {EDITOR_LOCK_ROUTE}")
        check_file_tool(tool_input, session_id)
        return
    command = tool_input.get("command", "")
    # These scripts live in the protected bot folder; exactly these commands run them, nothing else reaches the folder.
    if command.strip() == CONFIG["QUOTA_COMMAND"] or CLEAR_COMMAND_PATTERN.fullmatch(command.strip()) or PREFERENCES_COMMAND_PATTERN.fullmatch(command.strip()):
        return
    jobs_command = JOBS_COMMAND_PATTERN.fullmatch(command.strip())
    if jobs_command:
        if jobs_command.group("result"):
            result = resolve(jobs_command.group("result"), payload.get("cwd") or MAIN_CHECKOUT)
            if not is_within(result, DISPOSABLE_ROOT):
                deny(f"the result file must be under {DISPOSABLE_ROOT}. Supported: write the result text to a file there, then {CONFIG['JOBS_COMMAND']} finish <job id> <status> <that file>")
            check_shared_file(result)
        return
    working_directory = payload.get("cwd") or MAIN_CHECKOUT
    check_projects_references(command, session_id)
    for fragment in PROTECTED_PATH_FRAGMENTS:
        if fragment in command:
            deny(f"command references '{fragment}', which holds credentials, Claude/bot configuration or git hooks. Supported: nothing there; ask the operator")
    if HTTP_FETCH_PATTERN.search(command):
        deny(HTTP_FETCH_DENIAL)
    if DISCORD_STATE_PATTERN.search(command):
        deny(DISCORD_STATE_DENIAL)
    if CLAUDE_LAUNCH_PATTERN.search(command):
        deny(CLAUDE_LAUNCH_DENIAL)
    if "holder.json" in command and "editor.lock" in command:
        deny(f"holder.json is written by the guard. Supported: read it with the Read tool; {EDITOR_LOCK_ROUTE}")
    if re.search(r"\bsed\b[^|;&]*\s-i", command):
        deny("sed -i is unreliable on macOS (BSD sed) and has silently corrupted files. Supported: the Edit tool, or a short python3 script; sed -n for reading")
    if AUTH_ENVIRONMENT.search(command):
        deny(AUTH_ENVIRONMENT_DENIAL)
    tagged = False
    for segment in split_segments(command):
        job_tag = segment_job_tag(segment)
        if job_tag is not None:
            check_job_tag(job_tag)
            tagged = True
        if segment[:1] == ["env"]:
            for token in segment[1:]:
                if token.startswith("-"):
                    deny(AUTH_ENVIRONMENT_DENIAL)
                if "=" not in token:
                    break
        if any(GIT_ENVIRONMENT_ASSIGNMENT.match(token) for token in segment):
            deny("GIT_* environment variables can point git at other repositories or programs. Supported: plain git in the Fabric trees; -c user.email=... for identity")
        check_path_tokens(segment, working_directory)
        tokens = strip_prefixes(segment)
        if not tokens:
            continue
        program = tokens[0].rsplit("/", 1)[-1]
        for target in write_targets(tokens):
            check_persistent_write(resolve(target, working_directory))
        if program == "cd" and len(tokens) > 1:
            working_directory = resolve(tokens[1], working_directory)
        elif program == "git":
            check_git(tokens, working_directory)
        elif program == "rm":
            if fed_by_xargs(segment):
                check_rm([], working_directory)
            check_rm(tokens[1:], working_directory)
            for target in (a for a in tokens[1:] if not a.startswith("-")):
                check_editor_lock_removal(resolve(target, working_directory), caller)
        elif program == "mv":
            for source in [a for a in tokens[1:] if not a.startswith("-")][:-1]:
                check_editor_lock_removal(resolve(source, working_directory), caller)
        elif program == "find":
            check_find(tokens[1:], working_directory)
        elif program == "codesign":
            check_codesign(tokens[1:])
        elif program == "mkdir":
            check_mkdir(tokens[1:], working_directory, caller)
        elif program == "gh":
            check_gh(tokens, working_directory)
        elif program == "claude":
            deny(CLAUDE_LAUNCH_DENIAL)
        elif program in ("kill", "killall", "pkill"):
            check_kill(program, tokens[1:], segment)
        elif program == "security" or (program == "xcrun" and tokens[1:2] == ["security"]):
            deny(KEYCHAIN_DENIAL)
        elif program == "sudo":
            deny("sudo is not allowed: the bot never changes the system. Supported: ask the operator")
        if job_tag is None and (compiles(program, tokens) or program == "Fabric Editor" or "Fabric Editor.app/Contents/MacOS" in tokens[0]):
            deny(JOB_TAG_DENIAL)
        check_build_jobs(program, tokens)
        if program in CODE_RUNNERS or tokens[0].startswith("./"):
            check_script_code(tokens, working_directory)
        if program == "screencapture":
            check_screencapture(tokens[1:], working_directory)
        elif program == "open":
            check_open(tokens[1:], working_directory, caller)
        elif program == "Fabric Editor" or "Fabric Editor.app/Contents/MacOS" in tokens[0]:
            check_editor_lock(caller, "running the Editor")
        elif program in ("cua", "cua-driver", "spacesd"):
            deny(f"the {program} CLI drives any app or changes the driver without the guard's checks. Supported: the mcp__vm-driver__* tools")
    if tool_input.get("run_in_background") and not tagged:
        deny(JOB_TAG_DENIAL)


def receive_request(connection):
    data = b""
    while chunk := connection.recv(1 << 16):
        data += chunk
    environment_length = int.from_bytes(data[:4], "big")
    environment = data[4:4 + environment_length]
    rest = data[4 + environment_length:]
    directory_length = int.from_bytes(rest[:4], "big")
    directory = rest[4:4 + directory_length].decode()
    payload = rest[4 + directory_length:].decode()
    variables = dict(entry.decode(errors="replace").split("=", 1) for entry in environment.split(b"\0") if b"=" in entry)
    return variables, directory, payload


def answer(connection):
    """Runs one check in a forked child, as the hook process would. Replies '=' plus the output only when the
    check finished; otherwise the client runs guard.py itself."""
    import io
    variables, directory, payload = receive_request(connection)
    os.environ.clear()
    os.environ.update(variables)
    try:
        os.chdir(directory)
    except OSError:
        pass
    sys.stdin, sys.stdout = io.StringIO(payload), io.StringIO()
    try:
        main()
    except SystemExit as exit:
        if exit.code not in (0, None):
            return
    connection.sendall(b"=" + sys.stdout.getvalue().encode())


def source_stamps():
    sources = [os.path.realpath(__file__), os.path.join(CONFIG["BOT_DIRECTORY"], "config.py"), os.path.join(CONFIG["BOT_DIRECTORY"], ".envrc")]
    stamps = []
    for path in sources:
        try:
            status = os.stat(path)
            stamps.append((path, status.st_mtime_ns, status.st_size))
        except OSError:
            stamps.append((path, None, None))
    return stamps


def serve(socket_path):
    """Answers hook calls for the session that started it, and exits when that session does. Restarts itself when
    the guard or its configuration changes."""
    import glob, io, select, socket, subprocess
    system_library()
    session = os.getppid()
    stamps = source_stamps()
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    os.chmod(socket_path, 0o600)
    listener.listen(64)
    bound = os.stat(socket_path).st_ino
    try:
        while os.getppid() == session:
            readable, _, _ = select.select([listener], [], [], 1)
            while True:
                try:
                    if os.waitpid(-1, os.WNOHANG)[0] == 0:
                        break
                except ChildProcessError:
                    break
            if not readable:
                continue
            connection, _ = listener.accept()
            if source_stamps() != stamps:
                connection.close()
                listener.close()
                os.execv(sys.executable, [sys.executable, "-I", os.path.realpath(__file__), "--serve", socket_path])
            if os.fork() == 0:
                listener.close()
                try:
                    answer(connection)
                finally:
                    connection.close()
                    os._exit(0)
            connection.close()
    finally:
        try:
            if os.stat(socket_path).st_ino == bound:
                os.unlink(socket_path)
        except OSError:
            pass


def checked_main():
    # An uncaught exception exits 1, which lets the tool call through.
    try:
        main()
    except Exception as error:
        decide("deny", f"the guard failed ({type(error).__name__}: {error}); this call is denied. Tell the requester the operator has to fix the guard")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        serve(sys.argv[2])
    else:
        checked_main()
