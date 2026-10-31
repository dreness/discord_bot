#!/usr/bin/env python3 -I
"""Machine-local values for the bot, read from .envrc next to this file (gitignored; see .envrc.example).
Templates (settings.json, BOT.md, prompts) name them as {{NAME}}.
  config.py get NAME          print one value
  config.py render            build the guard client and render settings.json and BOT.md into rendered/,
                              plus settings-dry-run.json, which leaves the Discord plugin off, and mcp.json
                              (mode 0600), which carries the spacesd token for the vm-driver MCP server
  config.py render SRC [DEST] render one template, to stdout without DEST"""
import json
import os
import re
import sys

DIRECTORY = os.path.dirname(os.path.realpath(__file__))
ENVRC = os.path.join(DIRECTORY, ".envrc")
REQUIRED = ("CHECKOUT", "FORK_OWNER", "COMMIT_EMAIL")
TEMPLATES = ("settings.json", "BOT.md")
RENDERED_DIRECTORY = os.path.join(DIRECTORY, "rendered")
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def read_envrc():
    # Only the file counts, not the environment, so nothing the bot sets can change the guard's view.
    raw = {}
    with open(ENVRC) as handle:
        for line in handle:
            match = re.match(r"^\s*(?:export\s+)?FABRIC_BOT_([A-Z_]+)=(.*?)\s*$", line)
            if match:
                value = match.group(2)
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                raw[match.group(1)] = os.path.expanduser(os.path.expandvars(value))
    missing = [name for name in REQUIRED if not raw.get(name)]
    if missing:
        raise ValueError(f"{ENVRC} lacks " + ", ".join("FABRIC_BOT_" + name for name in missing))
    return raw


def values():
    raw = read_envrc()
    home = os.path.realpath(os.path.expanduser("~"))
    checkout = os.path.realpath(raw["CHECKOUT"])
    temp_root = os.path.realpath(raw.get("TEMP_ROOT") or f"/private/tmp/claude-{os.getuid()}")
    # Claude Code names a project's directories after its path, every other character a hyphen.
    build_jobs = raw.get("BUILD_JOBS") or "10"
    if not build_jobs.isdigit() or int(build_jobs) < 1:
        raise ValueError(f"{ENVRC}: FABRIC_BOT_BUILD_JOBS must be a positive integer")
    project_slug = re.sub(r"[^A-Za-z0-9]", "-", checkout)
    # The Fabric project's part of the temp root, which holds the bot's scratchpads; other projects' sessions stay out of reach.
    scratch_root = os.path.join(temp_root, project_slug)
    bot_directory_from_home = os.path.relpath(DIRECTORY, home)
    return {
        "HOME": home,
        "BOT_DIRECTORY": DIRECTORY,
        # Matched as a substring of commands, so ~/... spellings are caught too.
        "BOT_DIRECTORY_FRAGMENT": DIRECTORY if bot_directory_from_home.startswith("..") else bot_directory_from_home,
        "CHECKOUT": checkout,
        "SAMPLES_CHECKOUT": os.path.join(os.path.dirname(checkout), "Fabric-Samples"),
        "FORK_OWNER": raw["FORK_OWNER"],
        "COMMIT_EMAIL": raw["COMMIT_EMAIL"],
        # Compile jobs all of the bot's builds may run at once.
        "BUILD_JOBS": str(int(build_jobs)),
        # The guest's spacesd, which serves cua-driver over Streamable HTTP.
        "DRIVER_MCP_URL": raw.get("DRIVER_MCP_URL") or "http://127.0.0.1:3211/mcp",
        "DRIVER_TOKEN_FILE": os.path.realpath(raw.get("DRIVER_TOKEN_FILE") or os.path.join(home, ".cua/spacesd/token")),
        "TEMP_ROOT": temp_root,
        "SCRATCH_ROOT": scratch_root,
        "PROJECT_SLUG": project_slug,
        "TASK_ROOT": os.path.join(scratch_root, "discord-bot"),
        "GUARD_SOCKET": os.path.join(DIRECTORY, "rendered", "guard.sock"),
        "EDITOR_LOCK": os.path.join(scratch_root, "discord-bot", "editor.lock"),
        # Claude Code registers each running session here as <pid>.json.
        "SESSION_REGISTRY": os.path.realpath(raw.get("SESSION_REGISTRY") or os.path.join(home, ".claude/sessions")),
        # The Discord plugin's token, access list and inbox; the plugin reads DISCORD_STATE_DIR from its environment.
        "DISCORD_STATE_DIR": os.path.realpath(raw.get("DISCORD_STATE_DIR") or os.path.join(home, ".claude/channels/discord")),
        "GH_CONFIG_DIR": os.path.realpath(raw.get("GH_CONFIG_DIR") or os.path.join(home, ".config/gh-fabric-bot")),
        # The observer proxy (empty: none); run.sh uses it only while it answers its health probe.
        "LLM_PROXY": raw.get("LLM_PROXY", ""),
        "LLM_PROXY_CA": os.path.realpath(raw.get("LLM_PROXY_CA") or os.path.join(home, ".mitmproxy/mitmproxy-ca-cert.pem")),
        # The quota relay, read by quota-status.py.
        "QUOTA_URL": raw.get("QUOTA_URL") or "http://127.0.0.1:8791/quota",
        "QUOTA_COMMAND": os.path.join(DIRECTORY, "quota-status.py"),
        # Run by the bot for `clear`: a fresh session once the current turn ends.
        "CLEAR_COMMAND": os.path.join(DIRECTORY, "session-restart.py"),
        # The Cua Volume mount and the requesters' preferences on it.
        "CUA_VOLUME": os.path.realpath(raw.get("CUA_VOLUME") or os.path.join(home, "Cua Volume")),
        "PREFERENCES_FILE": raw.get("PREFERENCES_FILE") or os.path.join(home, "Cua Volume/spaces/local-fabric-bot/discord-bot/preferences.json"),
        "PREFERENCES_COMMAND": os.path.join(DIRECTORY, "preferences.py"),
        # The job ledger (requests and results), and where it goes while the volume isn't mounted (inside the protected bot folder).
        "JOBS_FILE": raw.get("JOBS_FILE") or os.path.join(home, "Cua Volume/spaces/local-fabric-bot/discord-bot/jobs.jsonl"),
        "JOBS_LOCAL_FILE": raw.get("JOBS_LOCAL_FILE") or os.path.join(DIRECTORY, "local-state", "jobs.jsonl"),
        "JOBS_COMMAND": os.path.join(DIRECTORY, "jobs.py"),
        # This project's session transcripts, readable with file tools only.
        "TRANSCRIPT_DIRECTORY": os.path.join(home, ".claude/projects", project_slug),
    }


def render(text, config=None, json_escaped=False):
    config = config or values()

    def substitute(match):
        if match.group(1) not in config:
            raise KeyError(f"unknown placeholder {match.group(0)}")
        value = config[match.group(1)]
        return json.dumps(value)[1:-1] if json_escaped else value

    return PLACEHOLDER.sub(substitute, text)


def render_file(source, destination=None, config=None):
    with open(source) as handle:
        text = render(handle.read(), config, json_escaped=source.endswith(".json"))
    if destination is None:
        sys.stdout.write(text)
        return
    with open(destination, "w") as handle:
        handle.write(text)


def build_guard_client(config):
    """Built before the settings that name it: a hook command that can't run blocks every tool call."""
    client = os.path.join(RENDERED_DIRECTORY, "guard-client")
    source = os.path.join(DIRECTORY, "guard-client.c")
    if os.path.exists(client) and os.path.getmtime(client) >= os.path.getmtime(source):
        return
    import subprocess
    subprocess.run(["/usr/bin/clang", "-O2", "-o", client, source], check=True)


def write_mcp_config(config):
    """The token goes only into rendered/, never into a template. Without a readable token the file is left out and run.sh says so."""
    destination = os.path.join(RENDERED_DIRECTORY, "mcp.json")
    try:
        with open(config["DRIVER_TOKEN_FILE"]) as handle:
            token = handle.read().strip()
    except OSError as error:
        print(f"config.py: no vm-driver MCP config: {error}", file=sys.stderr)
        if os.path.exists(destination):
            os.remove(destination)
        return
    server = {
        "type": "http",
        "url": config["DRIVER_MCP_URL"],
        "headers": {"Authorization": f"Bearer {token}", "X-Cua-Agent-Session": "discord-bot"},
    }
    descriptor = os.open(destination + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump({"mcpServers": {"vm-driver": server}}, handle, indent=2)
    os.replace(destination + ".tmp", destination)


def main(arguments):
    if arguments[:1] == ["get"] and len(arguments) == 2:
        print(values()[arguments[1]])
    elif arguments == ["render"]:
        config = values()
        # sun_path holds 104 bytes with its NUL.
        if len(os.fsencode(config["GUARD_SOCKET"])) > 103:
            sys.exit(f"{config['GUARD_SOCKET']} is too long for a unix socket; move this folder to a shorter path")
        os.makedirs(RENDERED_DIRECTORY, exist_ok=True)
        build_guard_client(config)
        for name in TEMPLATES:
            render_file(os.path.join(DIRECTORY, name), os.path.join(RENDERED_DIRECTORY, name), config)
        # A dry run beside the bot must not start a second Discord client.
        with open(os.path.join(RENDERED_DIRECTORY, "settings.json")) as handle:
            settings = json.load(handle)
        settings["enabledPlugins"] = {name: False for name in settings.get("enabledPlugins", {})}
        with open(os.path.join(RENDERED_DIRECTORY, "settings-dry-run.json"), "w") as handle:
            json.dump(settings, handle, indent=2)
        write_mcp_config(config)
    elif arguments[:1] == ["render"] and len(arguments) in (2, 3):
        render_file(*arguments[1:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
