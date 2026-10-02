#!/usr/bin/env python3
"""Install the ExamScribe skill for Codex, Claude Code or any agent that reads Agent Skills (a folder with SKILL.md).

    python install.py                      # every agent found on this computer (Codex, Claude Code)
    python install.py --codex              # ~/.agents/skills/exam-scribe   (Codex CLI, IDE and app)
    python install.py --claude             # ~/.claude/skills/exam-scribe   (Claude Code)
    python install.py --codex --project .  # ./.agents/skills/exam-scribe   (only this project)
    python install.py --dest DIR           # DIR/exam-scribe                (any other agent's skills folder)
    python install.py --uninstall --codex  # remove it again

Afterwards, install the Python packages once:  python -m pip install -r <installed folder>/requirements.txt
For the Claude apps (claude.ai, desktop), upload exam-scribe.skill from the GitHub release instead.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "exam-scribe"
NAME = "exam-scribe"
HOME = Path.home()
AGENTS = {
    # agent: (user-level skills folder, project-level skills folder, how to tell it is installed)
    "codex": (HOME / ".agents" / "skills", Path(".agents") / "skills", [HOME / ".codex"]),
    "claude": (HOME / ".claude" / "skills", Path(".claude") / "skills", [HOME / ".claude"]),
}


def _is_examscribe(folder: Path) -> bool:
    skill = folder / "SKILL.md"
    return skill.is_file() and "name: exam-scribe" in skill.read_text(encoding="utf-8", errors="replace")[:400]


def install(dest_parent: Path) -> Path:
    dest = dest_parent / NAME
    if dest.exists():
        if not _is_examscribe(dest):
            raise SystemExit(f"{dest} exists and is not ExamScribe; not touching it.")
        shutil.rmtree(dest)
        verb = "Updated"
    else:
        verb = "Installed"
    dest_parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "evals"))
    print(f"{verb} ExamScribe in {dest}")
    return dest


def uninstall(dest_parent: Path) -> None:
    dest = dest_parent / NAME
    if _is_examscribe(dest):
        shutil.rmtree(dest)
        print(f"Removed {dest}")
    else:
        print(f"Nothing to remove at {dest}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the ExamScribe skill.")
    ap.add_argument("--codex", action="store_true", help="install for Codex (~/.agents/skills)")
    ap.add_argument("--claude", action="store_true", help="install for Claude Code (~/.claude/skills)")
    ap.add_argument("--project", default=None, help="install into this project folder instead of your home folder")
    ap.add_argument("--dest", default=None, help="install into this skills folder (any agent)")
    ap.add_argument("--uninstall", action="store_true", help="remove ExamScribe instead")
    a = ap.parse_args()
    if not (SRC / "SKILL.md").is_file():
        raise SystemExit(f"Run this from the ExamScribe repository: {SRC} not found.")
    targets: list[Path] = []
    if a.dest:
        targets.append(Path(a.dest).expanduser().resolve())
    chosen = [n for n in AGENTS if getattr(a, n)]
    if not chosen and not a.dest:
        chosen = [n for n, (_, _, marks) in AGENTS.items() if any(m.exists() for m in marks)]
        if not chosen:
            print("No Codex or Claude Code folder found in your home folder. Choose one: --codex, --claude or "
                  "--dest DIR.")
            return 1
        print("Found: " + ", ".join(chosen))
    for n in chosen:
        user_dir, project_dir, _ = AGENTS[n]
        targets.append((Path(a.project).resolve() / project_dir) if a.project else user_dir)
    for t in targets:
        if a.uninstall:
            uninstall(t)
        else:
            dest = install(t)
            print(f"  Next (once): {Path(sys.executable).name} -m pip install -r \"{dest / 'requirements.txt'}\"")
    if not a.uninstall:
        print("Restart the agent if it is running, then ask it, for example: \"Here is my chemistry textbook; the "
              "exam is on 15 December: make me study notes for chapters 2 to 4.\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
