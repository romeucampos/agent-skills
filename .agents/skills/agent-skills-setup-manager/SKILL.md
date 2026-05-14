---
name: agent-skills-setup-manager
description: Set up, repair, re-run, or inspect the agent-skills monorepo. Use when the user wants to install the monorepo for the first time, add a new agent (codex/copilot/cursor/gemini) to an existing setup, check the status of their symlinks, repair drift, or ask any "set up my agent skills" / "configure agent-skills-monorepo" question. Operates on the repo whose root contains `setup_symlinks.py` and `AGENTS.md` describing the agent-skills monorepo. Do NOT use for unrelated skill authoring or other repos.
---

# Agent Skills Setup Manager

You are helping a user manage an **agent-skills monorepo** — a repo that owns their coding-agent skills and exposes them via symlinks from `~/.<agent>/skills` and `~/.agents/skills`.

## When this skill applies

Trigger phrases include: "set up agent skills", "install agent-skills-monorepo", "add codex to my setup", "repair my skills symlinks", "what agents am I managing", "show me my skills topology".

Do **not** invoke this skill for routine skill authoring (creating a new skill file) — only for setup / repair / topology questions about the monorepo itself.

## Finding the repo

The repo root is identifiable by:
- A `setup_symlinks.py` file at the root.
- An `AGENTS.md` describing the monorepo.
- Top-level folders matching agent names (`agents/`, `claude/`, optionally `codex/`, `copilot/`, `cursor/`, `gemini/`).

If you can't locate the repo, ask the user for the path. Do not guess.

## Required vs optional agents

- `agents/` → `~/.agents/skills` is **canonical** and always managed.
- `claude/` → `~/.claude/skills` is a **required mirror** (Claude Code does not read `~/.agents/skills`).
- `codex/`, `copilot/`, `cursor/`, `gemini/` are **optional**; the user opts in per-agent.

## Standard flows

### Flow A: First-time setup

1. Confirm the user wants to run setup. Show the repo root you detected.
2. Ask which optional agents to include (alongside the required `agents` + `claude`). List the optional ones; default to none if the user doesn't care.
3. Run the dry-run first so the user can see the plan:
   ```sh
   python3 setup_symlinks.py --dry-run --agents=<comma,separated,list>
   ```
4. Summarize what the dry run will do per agent in plain English. Highlight any backups about to be created.
5. Ask for explicit confirmation, then run:
   ```sh
   python3 setup_symlinks.py --agents=<comma,separated,list>
   ```
   The script is interactive and asks for confirmation at each step; relay its prompts to the user.
6. After completion, run `python3 setup_symlinks.py --status` and show the result.

### Flow B: Add an agent to an existing setup

1. Run `python3 setup_symlinks.py --status` to see what is already configured.
2. Confirm which new agent the user wants to add.
3. Build the new comma-separated list = previously configured + the new one.
4. Run dry-run then live run as in Flow A. Already-configured agents are skipped automatically.

### Flow C: Repair drift

1. Run `python3 setup_symlinks.py --status` and analyze the output.
2. For any agent whose system path is not a symlink to the repo folder, decide with the user:
   - If the system path is a foreign symlink or a non-directory, surface this and stop — do not auto-resolve.
   - If the system path is a regular directory, re-running setup with that agent in the selection will import-and-link or merge it.
3. Run the script with the appropriate `--agents=` flag.

### Flow D: Status check

Run `python3 setup_symlinks.py --status` and explain the output in plain language. Mention any agents that are not configured but available, and any drift.

## Guardrails

- **Never** delete the `.agent-skills-setup/backup/` directory without explicit user permission. It is the user's safety net.
- **Never** force or `--no-verify` anything. The script has no force mode by design.
- **Never** edit individual skills as part of setup work — that's out of scope for this skill.
- Always show the dry-run plan before running for real, even if the user is in a hurry.
- If the script reports an unhandled state combination, stop and ask the user. Do not improvise.

## Installing new skills into the repo

When the user asks you to **add or create a new skill** inside this repo (separate from setup):

- Ask: "Install this skill into `agents/`, `claude/`, or both?" Default suggestion is **both**.
- Remind the user that they can set a durable preference in the repo's `AGENTS.md` (e.g. "always install new skills into both" or "agents-only by default") so they don't get asked every time.
- If `AGENTS.md` already specifies a preference, follow it without re-asking.
- Avoid placing user skills into `codex/`, `copilot/`, `cursor/`, or `gemini/` unless the user explicitly says so.

## Quick reference

| Task | Command |
| --- | --- |
| Show topology | `python3 setup_symlinks.py --status` |
| Preview setup | `python3 setup_symlinks.py --dry-run` |
| Interactive setup | `python3 setup_symlinks.py` |
| Non-interactive selection | `python3 setup_symlinks.py --agents=agents,claude,codex` |
| Saved selection file | `.agent-skills-setup/config.json` |
| Backups | `.agent-skills-setup/backup/<agent>/` |
| Recovery notes | `.agent-skills-setup/backup/README.md` |
