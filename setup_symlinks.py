import argparse
import json
import shutil
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

try:
    import termios
    import tty
except ImportError:  # non-Unix
    termios = None
    tty = None


def _read_key(stream) -> str:
    """Read one keystroke (or escape sequence) from a cbreak-mode stdin."""
    ch = stream.read(1)
    if ch != "\x1b":
        return ch
    # Possible escape sequence; read the rest if present.
    seq = ch
    nxt = stream.read(1)
    if not nxt:
        return seq
    seq += nxt
    if nxt == "[":
        while True:
            c = stream.read(1)
            if not c:
                break
            seq += c
            if c.isalpha() or c == "~":
                break
    return seq


def multiselect_checkbox(
    title: str,
    items: list[tuple[str, str, bool]],
    preselected: set[str],
) -> list[str]:
    """Interactive checkbox prompt.

    items: list of (key, description, locked) tuples. Locked items cannot be toggled.
    preselected: keys to start checked. Locked items are auto-checked regardless.
    Returns the list of selected keys in the order they appear in `items`.

    Falls back to a plain non-interactive listing if stdin is not a TTY or termios
    is unavailable.
    """
    locked_keys = {k for k, _d, locked in items if locked}
    selected: set[str] = set(preselected) | locked_keys
    keys = [k for k, _d, _l in items]

    is_tty = sys.stdin.isatty() and sys.stdout.isatty() and termios is not None
    if not is_tty:
        # Non-interactive fallback: keep required + preselected, print and continue.
        print(title)
        for key, desc, locked in items:
            mark = "x" if key in selected else " "
            tag = " (required)" if locked else ""
            print(f"  [{mark}] {key:<8} {desc}{tag}")
        print()
        return [k for k in keys if k in selected]

    cursor = 0
    help_line = (
        "Up/Down or j/k to move, Space to toggle, Enter to confirm, "
        "q or Ctrl-C to cancel."
    )
    total_lines = 2 + len(items)  # title + help + one per item

    def render(first: bool) -> None:
        out = sys.stdout
        if not first:
            out.write(f"\x1b[{total_lines}F")  # move to start of N lines up
            out.write("\x1b[J")  # clear to end of screen
        out.write(title + "\n")
        out.write(help_line + "\n")
        for i, (key, desc, locked) in enumerate(items):
            pointer = ">" if i == cursor else " "
            mark = "x" if key in selected else " "
            tag = " (required)" if locked else ""
            out.write(f"{pointer} [{mark}] {key:<8} {desc}{tag}\n")
        out.flush()

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        render(first=True)
        while True:
            key = _read_key(sys.stdin)
            if key in ("\x1b[A", "k"):  # up
                cursor = (cursor - 1) % len(items)
            elif key in ("\x1b[B", "j"):  # down
                cursor = (cursor + 1) % len(items)
            elif key == " ":
                k = keys[cursor]
                if k in locked_keys:
                    continue
                if k in selected:
                    selected.remove(k)
                else:
                    selected.add(k)
            elif key in ("\r", "\n"):
                break
            elif key in ("\x03", "q"):
                raise KeyboardInterrupt
            else:
                continue
            render(first=False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)

    print()
    return [k for k in keys if k in selected]


REQUIRED_AGENTS = ("agents", "claude")
OPTIONAL_AGENTS = ("codex", "copilot", "cursor", "gemini")
ALL_AGENTS = REQUIRED_AGENTS + OPTIONAL_AGENTS


@dataclass(frozen=True)
class AgentMapping:
    name: str
    repo_path: Path
    system_path: Path


class SetupError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set up symlinks between this repo and your agent skills directories. "
            "Idempotent: safe to re-run to add new agents or repair drift."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the setup without changing files or asking for confirmation.",
    )
    parser.add_argument(
        "--agents",
        type=str,
        default=None,
        help=(
            "Comma-separated list of agents to manage. Skips the interactive selection. "
            f"'agents' and 'claude' are always included. Optional: {', '.join(OPTIONAL_AGENTS)}."
        ),
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the current symlink topology and exit without making changes.",
    )
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def system_path_for(name: str) -> Path:
    home = Path.home()
    layout = {
        "claude": home / ".claude" / "skills",
        "agents": home / ".agents" / "skills",
        "codex": home / ".codex" / "skills",
        "copilot": home / ".copilot" / "skills",
        "cursor": home / ".cursor" / "skills",
        "gemini": home / ".gemini" / "antigravity" / "skills",
    }
    return layout[name]


def build_mapping(name: str, root: Path) -> AgentMapping:
    return AgentMapping(name, root / name, system_path_for(name))


def managed_root(root: Path) -> Path:
    return root / ".agent-skills-setup"


def backup_root(root: Path) -> Path:
    return managed_root(root) / "backup"


def backup_dir(root: Path, agent_name: str) -> Path:
    return backup_root(root) / agent_name


def backup_readme_path(root: Path) -> Path:
    return backup_root(root) / "README.md"


def config_path(root: Path) -> Path:
    return managed_root(root) / "config.json"


def load_saved_selection(root: Path) -> list[str] | None:
    path = config_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        agents = data.get("agents")
        if isinstance(agents, list) and all(isinstance(x, str) for x in agents):
            return [a for a in agents if a in ALL_AGENTS]
    except (json.JSONDecodeError, OSError):
        return None
    return None


def save_selection(root: Path, agents: list[str], *, dry_run: bool) -> None:
    if dry_run:
        return
    path = config_path(root)
    ensure_dir(path.parent)
    payload = {"agents": agents}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def create_symlink(link_path: Path, target: Path) -> None:
    link_path.symlink_to(target)


def iter_entries(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(path.iterdir(), key=lambda entry: entry.name)


def format_entry_names(entries: list[Path]) -> str:
    return ", ".join(entry.name for entry in entries)


def copy_directory(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise SetupError(f"Expected a directory at {src}")

    ensure_dir(dst.parent)
    temp_dir = dst.parent / f".{dst.name}.tmp"
    old_dir = dst.parent / f".{dst.name}.old"

    remove_path(temp_dir)
    remove_path(old_dir)
    shutil.copytree(src, temp_dir)

    if dst.exists() or dst.is_symlink():
        shutil.move(str(dst), str(old_dir))

    shutil.move(str(temp_dir), str(dst))
    remove_path(old_dir)


def classify_repo(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if not path.exists():
        return "missing"
    if not path.is_dir():
        return "not_dir"
    return "has_skills" if iter_entries(path) else "empty"


def classify_system(path: Path, repo_path: Path) -> str:
    if path.is_symlink():
        try:
            resolved = path.resolve()
        except OSError:
            return "broken_symlink"
        return "symlink_to_repo" if resolved == repo_path.resolve() else "symlink_other"
    if not path.exists():
        return "missing"
    if not path.is_dir():
        return "not_dir"
    return "has_content" if iter_entries(path) else "empty"


def describe_repo_state(path: Path) -> str:
    state = classify_repo(path)
    if state == "symlink":
        return f"symlink -> {path.resolve()}"
    if state == "not_dir":
        return "exists but is not a directory"
    if state == "missing":
        return "missing"
    if state == "empty":
        return "empty directory"
    entries = iter_entries(path)
    return f"{len(entries)} item(s): {format_entry_names(entries)}"


def describe_system_state(path: Path, repo_path: Path) -> str:
    state = classify_system(path, repo_path)
    if state == "symlink_to_repo":
        return f"symlink -> {repo_path} (configured)"
    if state == "symlink_other":
        return f"symlink -> {path.resolve()} (foreign)"
    if state == "broken_symlink":
        return "broken symlink"
    if state == "not_dir":
        return "exists but is not a directory"
    if state == "missing":
        return "missing"
    entries = iter_entries(path)
    return f"directory with {len(entries)} item(s): {format_entry_names(entries)}"


def collect_preflight_problems(mappings: list[AgentMapping]) -> list[str]:
    """Only flags state that the per-agent flow cannot recover from."""
    problems: list[str] = []
    for mapping in mappings:
        if mapping.repo_path.exists() and not mapping.repo_path.is_dir() and not mapping.repo_path.is_symlink():
            problems.append(
                f"Remove {mapping.repo_path} because it exists but is not a directory."
            )
        if (
            mapping.system_path.exists()
            and not mapping.system_path.is_dir()
            and not mapping.system_path.is_symlink()
        ):
            problems.append(
                f"Remove {mapping.system_path} because it exists but is not a directory."
            )
    return problems


def write_backup_readme(
    root: Path, mappings: list[AgentMapping], *, dry_run: bool
) -> None:
    readme_path = backup_readme_path(root)

    if dry_run:
        print(f"Dry run: would write recovery notes to {readme_path}")
        return

    ensure_dir(readme_path.parent)

    lines = [
        "# Backup Recovery Notes",
        "",
        "This folder contains backups made by `setup_symlinks.py` before it changed your system skill directories.",
        "",
        "If setup stopped halfway through, use these steps for any agent you want to restore:",
        "",
        "1. Remove the system skills symlink if one exists.",
        "2. Remove the partially imported repo folder for that agent if you do not want to keep it.",
        "3. Copy the matching backup folder back to the original system path.",
        "",
        "A backup folder only exists for an agent after the script has successfully created it.",
        "",
        "Agent paths:",
        "",
    ]

    for mapping in mappings:
        lines.extend(
            [
                f"- {mapping.name}",
                f"  backup: {backup_dir(root, mapping.name)}",
                f"  system: {mapping.system_path}",
                f"  repo:   {mapping.repo_path}",
                "",
            ]
        )

    lines.extend(
        [
            "Example restore commands on macOS or Linux:",
            "",
            "```sh",
            "rm -rf ~/.agents/skills",
            "cp -R /path/to/agent-skills/.agent-skills-setup/backup/agents ~/.agents/skills",
            "```",
            "",
            "After you restore a system directory, make sure the matching repo folder is either removed or reset to the state you want before running setup again.",
            "",
        ]
    )

    readme_path.write_text("\n".join(lines), encoding="utf-8")


def print_intro(root: Path, mappings: list[AgentMapping], *, dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "LIVE RUN"
    print(f"== {mode} ==")
    print(f"Repo root:   {root}")
    print(f"Backup root: {backup_root(root)}")
    print()
    print("Selected agents and current state:")

    for mapping in mappings:
        print(f"- {mapping.name}")
        print(f"  repo:   {mapping.repo_path}")
        print(f"  state:  {describe_repo_state(mapping.repo_path)}")
        print(f"  system: {mapping.system_path}")
        print(f"  state:  {describe_system_state(mapping.system_path, mapping.repo_path)}")

    print()


def print_status(root: Path) -> None:
    print(f"Repo root: {root}")
    saved = load_saved_selection(root) or []
    print(f"Saved selection: {', '.join(saved) if saved else '(none)'}")
    print()
    for name in ALL_AGENTS:
        mapping = build_mapping(name, root)
        marker = "*" if name in saved else " "
        print(f"{marker} {name}")
        print(f"    repo:   {describe_repo_state(mapping.repo_path)}")
        print(f"    system: {describe_system_state(mapping.system_path, mapping.repo_path)}")


def confirm_or_exit(message: str) -> None:
    answer = input(f"{message} [Y/n]: ").strip().lower()
    if answer in {"", "y", "yes"}:
        return

    print("Setup cancelled. No more changes will be made.")
    raise SystemExit(1)


def prompt_agent_selection(saved: list[str] | None) -> list[str]:
    descriptions = {
        "agents": "~/.agents/skills",
        "claude": "~/.claude/skills",
        "codex": "~/.codex/skills",
        "copilot": "~/.copilot/skills",
        "cursor": "~/.cursor/skills",
        "gemini": "~/.gemini/antigravity/skills",
    }
    items: list[tuple[str, str, bool]] = []
    for name in ALL_AGENTS:
        locked = name in REQUIRED_AGENTS
        items.append((name, descriptions[name], locked))

    preselected: set[str] = set(REQUIRED_AGENTS)
    if saved:
        preselected.update(saved)

    return multiselect_checkbox(
        title="Select agents to manage:",
        items=items,
        preselected=preselected,
    )


def parse_agents_flag(value: str) -> list[str]:
    chosen: list[str] = []
    for token in value.split(","):
        name = token.strip().lower()
        if not name:
            continue
        if name not in ALL_AGENTS:
            raise SetupError(f"Unknown agent: {name}")
        if name not in chosen:
            chosen.append(name)
    # Enforce required agents.
    for required in REQUIRED_AGENTS:
        if required not in chosen:
            chosen.append(required)
    return chosen


def determine_selection(args: argparse.Namespace, root: Path) -> list[str]:
    if args.agents is not None:
        return parse_agents_flag(args.agents)

    saved = load_saved_selection(root)
    if saved is not None:
        print(f"Found saved selection: {', '.join(saved)}")
        answer = input("Use saved selection? [Y/n] (n = edit): ").strip().lower()
        if answer in {"", "y", "yes"}:
            return saved

    return prompt_agent_selection(saved)


def rollback_agent(
    mapping: AgentMapping,
    root: Path,
    *,
    repo_existed_before: bool,
    system_existed_before: bool,
) -> None:
    print(f"Attempting rollback for {mapping.name}...")

    remove_path(mapping.system_path)

    agent_backup = backup_dir(root, mapping.name)
    if system_existed_before and agent_backup.exists():
        copy_directory(agent_backup, mapping.system_path)
        print(f"Restored the original system directory from {agent_backup}")

    remove_path(mapping.repo_path)
    if repo_existed_before:
        ensure_dir(mapping.repo_path)

    print(f"Rollback finished for {mapping.name}.")


def plan_action(mapping: AgentMapping) -> tuple[str, str]:
    """Return (action, human_description) for the per-agent state."""
    repo_state = classify_repo(mapping.repo_path)
    system_state = classify_system(mapping.system_path, mapping.repo_path)

    if system_state == "symlink_to_repo":
        return "skip_configured", "Already configured (system symlinks into repo)."

    if system_state in {"symlink_other", "broken_symlink"}:
        return (
            "skip_foreign",
            f"System path is a {system_state.replace('_', ' ')}; will not touch.",
        )

    if repo_state == "symlink":
        return "skip_repo_symlink", "Repo path is itself a symlink; will not touch."

    if repo_state in {"empty", "missing"} and system_state == "has_content":
        return "import_and_link", "Back up system dir, import into repo, replace with symlink."

    if repo_state in {"empty", "missing"} and system_state in {"empty", "missing"}:
        return "link_only", "Create empty repo dir and symlink system path to it."

    if repo_state == "has_skills" and system_state in {"empty", "missing"}:
        return "adopt_repo", "Repo already has skills; just symlink system path to it."

    if repo_state == "has_skills" and system_state == "has_content":
        return "conflict", (
            "Both repo and system already have content. Resolve manually: pick one as "
            "the source of truth and clear the other before re-running."
        )

    return "error", f"Unhandled state combo: repo={repo_state}, system={system_state}"


def setup_agent(mapping: AgentMapping, root: Path) -> None:
    action, description = plan_action(mapping)

    print(f"== {mapping.name} ==")
    print(f"Repo:   {mapping.repo_path}  [{describe_repo_state(mapping.repo_path)}]")
    print(f"System: {mapping.system_path}  [{describe_system_state(mapping.system_path, mapping.repo_path)}]")
    print(f"Plan:   {description}")

    if action.startswith("skip"):
        print()
        return

    if action in ("error", "conflict"):
        print("Skipping. Resolve manually and re-run.")
        print()
        return

    confirm_or_exit(f"Proceed with {mapping.name}?")

    repo_existed_before = mapping.repo_path.exists()
    system_existed_before = mapping.system_path.exists()
    agent_backup = backup_dir(root, mapping.name)

    try:
        if action == "import_and_link":
            if agent_backup.exists():
                raise SetupError(
                    f"Backup already exists at {agent_backup}; remove it before re-importing."
                )
            print(f"Backing up {mapping.system_path} -> {agent_backup}")
            copy_directory(mapping.system_path, agent_backup)
            print(f"Importing into {mapping.repo_path}")
            copy_directory(mapping.system_path, mapping.repo_path)
            remove_path(mapping.system_path)

        elif action == "link_only":
            ensure_dir(mapping.repo_path)

        elif action == "adopt_repo":
            remove_path(mapping.system_path)

        ensure_dir(mapping.system_path.parent)
        print(f"Creating symlink {mapping.system_path} -> {mapping.repo_path}")
        create_symlink(mapping.system_path, mapping.repo_path)

        if not mapping.system_path.is_symlink() or mapping.system_path.resolve() != mapping.repo_path.resolve():
            raise SetupError(
                f"Created {mapping.system_path}, but it does not point to {mapping.repo_path}."
            )

        print("Done.")
        print()
    except Exception as exc:
        print()
        print(f"Setup failed while working on {mapping.name}.")
        try:
            rollback_agent(
                mapping,
                root,
                repo_existed_before=repo_existed_before,
                system_existed_before=system_existed_before,
            )
        except Exception as rollback_exc:
            raise SetupError(
                f"Setup failed for {mapping.name}, and rollback also failed: {rollback_exc}"
            ) from exc
        raise


def print_failure_help(root: Path) -> None:
    readme_path = backup_readme_path(root)
    print(file=sys.stderr)
    print("Setup did not finish cleanly.", file=sys.stderr)
    print(
        f"Any backups that were created are under {backup_root(root)}.",
        file=sys.stderr,
    )
    print(
        f"Recovery instructions are in {readme_path}.",
        file=sys.stderr,
    )
    if not readme_path.exists():
        print(
            "That README was not written yet, which usually means the script stopped before any backup work began.",
            file=sys.stderr,
        )


def dry_run_summary(mappings: list[AgentMapping]) -> None:
    print("Dry run summary:")
    for mapping in mappings:
        action, description = plan_action(mapping)
        print(f"- {mapping.name}: {action}")
        print(f"    {description}")
    print()
    print("Dry run complete. No files were changed.")


def main() -> int:
    args = parse_args()
    root = repo_root()

    if args.status:
        print_status(root)
        return 0

    selection = determine_selection(args, root)
    mappings = [build_mapping(name, root) for name in selection]

    print_intro(root, mappings, dry_run=args.dry_run)

    problems = collect_preflight_problems(mappings)
    if problems:
        message_lines = [
            "Setup cannot continue because some paths are in unrecoverable shapes:",
            "",
        ]
        message_lines.extend(f"- {problem}" for problem in problems)
        raise SetupError("\n".join(message_lines))

    write_backup_readme(root, mappings, dry_run=args.dry_run)
    save_selection(root, selection, dry_run=args.dry_run)

    if args.dry_run:
        dry_run_summary(mappings)
        return 0

    print("This script will work through each selected agent one at a time.")
    print("Already-configured agents are skipped automatically.")
    print()
    confirm_or_exit("Start setup?")
    print()

    for mapping in mappings:
        setup_agent(mapping, root)

    print("Setup complete.")
    print(f"Backups (if any) are stored under {backup_root(root)}.")
    print(f"Saved selection: {config_path(root)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        print_failure_help(repo_root())
        raise SystemExit(1)
