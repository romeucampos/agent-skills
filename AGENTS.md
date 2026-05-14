# AGENTS.md

## Project Overview

- Repository for coding-agent skills across multiple tools.
- `agents/` is the canonical user-skill folder and maps to `~/.agents/skills`.
- `claude/` is a required mirror of `agents/` and maps to `~/.claude/skills`. Claude Code does not read `~/.agents/skills`, so skills you want Claude to use must also live here.
- `codex/`, `copilot/`, `cursor/`, `gemini/` are optional per-agent folders. Users opt into these during setup.
- The repo is intentionally blank in the top-level agent folders. The template ships one project-local skill, `agent-skills-setup-manager`, under `.agents/skills/` and `.claude/skills/`, which manages this repo itself.

## Source-of-truth Rules

- New skills go into `agents/` first.
- By default a new skill should also be installed into `claude/` so Claude Code can use it.
- **Whenever you (the agent) are about to create or install a skill into this repo, ask the user first:** "Install this skill into `agents/`, `claude/`, or both?" Default suggestion is "both."
- Remind the user that they can set a durable default by editing this `AGENTS.md` (e.g. "always install new skills into both" or "agents-only by default") so they don't have to answer that question every time.
- If the user has expressed a preference in this file, follow it without re-asking.
- Avoid putting user skills into `codex/`, `copilot/`, `cursor/`, or `gemini/` unless the user explicitly says so. Those folders are for agents whose system directory layout is separate from `~/.agents/skills`.

## Repo Shape

- `setup_symlinks.py`: interactive setup script. Validates, backs up, imports, and symlinks the selected agent directories. Idempotent — safe to re-run.
- `.agent-skills-setup/config.json`: persists the user's agent selection.
- `.agent-skills-setup/backup/`: per-agent backups created during setup.
- `.agent-skills-setup/backup/README.md`: recovery instructions written before live changes begin.
- `.agents/skills/agent-skills-setup-manager/` and `.claude/skills/agent-skills-setup-manager/`: the project-local skill that helps agents drive setup, repair, status checks, and re-runs. These hidden folders are scoped to this repo (project-level skills) and are not symlinked anywhere.

## Development Commands

- `python3 setup_symlinks.py --dry-run`: preview validation, backup, import, and symlink actions.
- `python3 setup_symlinks.py`: run the interactive setup flow.
- `python3 setup_symlinks.py --status`: print the current symlink topology and saved selection.
- `python3 setup_symlinks.py --agents=agents,claude,codex`: run non-interactively with a specific agent selection (`agents` and `claude` are always included).

## Important Notes

- The script is idempotent. Already-configured agents (system path is a symlink into the matching repo folder) are skipped automatically.
- The script keeps simple, readable logic: no force mode, no destructive shortcuts. It refuses to touch foreign symlinks or non-directory paths.
- Backups under `.agent-skills-setup/backup/<agent>/` are important and are not auto-deleted.
- After setup, edits inside the repo folders or the system skill directories both modify the same files.

## Validation

- Use `python3 setup_symlinks.py --dry-run` first when changing setup logic.
- After a real setup, each configured system skill directory should resolve to the matching repo folder.
- `python3 setup_symlinks.py --status` is a fast way to confirm the topology.
