# Fabric Discord bot: restricted session

This project configures a Claude Code session, driven from Discord, working on Fabric and Satin inside a macOS VM dedicated for this task. The VM provides a decent security boundary, and has enough GPU support to run Fabric Editor with good performance.

The policy, in spirit:
- **Stay in scope.** Work happens in the Fabric and Satin checkouts, a scratch area, and the operator's fork. Nothing goes upstream; the operator carries work over by hand.
- **Never ask.** The session runs in `dontAsk`: what isn't allowed is denied, and each guard denial names the supported route.
- **Keep secrets out of reach.** The bot has its own scoped GitHub token and is kept from the gh config, keychain, Discord bot token, Claude login, spacesd token and other projects' transcripts.
- **Share the VM.** The VM is the bot's, but tasks share it: one Editor user at a time, a build job cap, own worktrees. No new Claude sessions.
- **Can't loosen its own leash.** The bot can't edit this folder, Claude settings, hooks or plugins.

How, in brief: allow/deny rules in `settings.json`; `guard.py`, a fail-closed PreToolUse hook for what rules can't express; and `BOT.md`, appended to the system prompt, which explains the rules and the expected workflows. Each denial names the supported route. `run.sh` is the only entry point; machine-local values live in a gitignored `.envrc` (`cp .envrc.example .envrc`). `tests/` holds a test script for each area of the guard.

**Scope of the protection:** the guard and rules are guardrails against mistakes and against the model being steered by content it reads (PR bodies, comments, attachments), not a sandbox. The bot runs as the guest's only user with `python3`, `bash` and `zsh` allowed, so a determined actor can get around the pattern checks; containment comes from the VM. Seatbelt sandbox mode stays off because it breaks git push, `gh`, and likely SwiftPM.

## Trust model

- The VM is the boundary. A mistake or a steered bot can damage the guest, which resetting the VM undoes. What it can still reach: its own Anthropic login, Discord bot token and GitHub token, the fork and gists on `{{FORK_OWNER}}`, public repos, and the internet over NAT. The guard keeps the bot from reading those credentials and limits what it does with them.
- One or two allowlisted Discord users, authorized for tasks on Fabric and Satin. Allowlist changes happen only in the operator's terminal (`/discord:access`, denied to the bot).
- Why `dontAsk`: the Discord plugin relays permission prompts to the allowlisted users' DMs, and the first answer wins. No client setting keeps prompts terminal-only. So nothing prompts, and the guard never answers `ask`. Operator-only actions happen in another session.

## Expected work

Defined in `BOT.md`: PR reviews of Fabric-Project/Fabric and Fabric-Project/Satin with evidence on the fork, builds, tests, bug repros, code questions, and feature work on fork branches.

## This repo

What runs in the guest, and no secrets or machine-local values. `{{NAME}}` stands for a value from `.envrc` or derived from it in `config.py`.
