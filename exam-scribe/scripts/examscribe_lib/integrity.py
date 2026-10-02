"""Guards against changes made outside ExamScribe's own commands.

Two things are protected, because a model that cannot get past a check may be tempted to change the check or the
record of what passed:

* the skill's own files. `scripts/integrity.json` lists the SHA-256 of every file the skill ships (line endings
  normalised, so a Windows checkout does not count as a change). If a script, reference or SKILL.md differs, every
  command stops: a changed checker could pass anything.
* the files of a workspace that only the scripts write (state, extracted pages, inventory, verification records and
  the canary keys). Every time a script writes one, its digest goes into `.integrity.json` and a copy into
  `.backup/`. Before each command the files are compared with that record; a file changed by anything else stops
  the work until `restore` puts the scripts' last version back. Drafts and worksheets are the model's to edit and are
  not protected here (their own checks cover them).

This is a tripwire for honest mistakes and lazy shortcuts, not a vault: an agent determined to cheat can read and
rewrite anything it can read and write. The instructions say why that would be pointless.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
MANIFEST = SKILL_DIR / "scripts" / "integrity.json"
REGISTRY = ".integrity.json"
BACKUP_DIR = ".backup"
CONFIG_NAME = "examscribe.json"
SKIP_ENV = "EXAMSCRIBE_SKIP_INTEGRITY"     # the test suite only

# files of a workspace that only the scripts write (paths relative to the workspace, "/" separated)
PROTECTED = ("state.json", "source/pages.jsonl", "source/outline.json", "source/quality.json", "source/figures.json",
             "inventory/*.json", "chapters/*/verify/*.json")
# skill files that are not part of the published skill (never checked)
NOT_SHIPPED = ("scripts/integrity.json", "evals/*")


def _skip() -> bool:
    return bool(os.environ.get(SKIP_ENV))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_digest(path: Path) -> str:
    """SHA-256 of a file with CRLF turned into LF (git on Windows may check text files out with CRLF)."""
    return _digest(path.read_bytes().replace(b"\r\n", b"\n"))


# =============================================================================== the skill's own files

def skill_files(skill_dir: Path = SKILL_DIR) -> list[str]:
    out = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        rel = p.relative_to(skill_dir).as_posix()
        if any(fnmatch.fnmatch(rel, pat) for pat in NOT_SHIPPED):
            continue
        out.append(rel)
    return out


def make_manifest(skill_dir: Path = SKILL_DIR) -> dict:
    return {"about": "SHA-256 of every file of the ExamScribe skill (CRLF read as LF). The scripts stop when a file "
                     "differs: a changed checker could pass anything.",
            "files": {rel: normalized_digest(skill_dir / rel) for rel in skill_files(skill_dir)}}


def manifest_digest() -> str | None:
    return normalized_digest(MANIFEST) if MANIFEST.exists() else None


def skill_changes() -> list[str]:
    """Files of the installed skill that differ from its manifest (empty when there is no manifest)."""
    if _skip() or not MANIFEST.exists():
        return []
    try:
        listed = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["files"]
    except (ValueError, KeyError, OSError):
        return ["scripts/integrity.json (unreadable)"]
    bad = []
    for rel, digest in listed.items():
        p = SKILL_DIR / rel
        if not p.is_file():
            bad.append(f"{rel} (missing)")
        elif normalized_digest(p) != digest:
            bad.append(rel)
    return bad


# =============================================================================== workspace files

def _workspace_root(path: Path) -> Path | None:
    for parent in list(path.parents)[:6]:
        if (parent / CONFIG_NAME).is_file():
            return parent
    return None


def _protected(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in PROTECTED)


def _load(root: Path) -> dict | None:
    p = root / REGISTRY
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.setdefault("files", {})
        return data
    except (ValueError, OSError):
        return {"files": {}, "unreadable": True}


def _save(root: Path, data: dict) -> None:
    p = root / REGISTRY
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for _ in range(20):                      # Windows: another process may hold the file for a moment
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, p)


def protected_files(root: Path) -> list[str]:
    out = []
    for pat in PROTECTED:
        for p in root.glob(pat):
            if p.is_file():
                out.append(p.relative_to(root).as_posix())
    return sorted(set(out))


def note_write(path: Path) -> None:
    """Called after the scripts write a file: record a protected file's digest and keep a copy of it."""
    if _skip():
        return
    path = Path(path).resolve()
    root = _workspace_root(path)
    if root is None:
        return
    rel = path.relative_to(root).as_posix()
    if not _protected(rel):
        return
    data = path.read_bytes()
    reg = _load(root) or {"files": {}}
    if reg.get("unreadable"):
        return                                # check_workspace reports it
    reg["files"][rel] = _digest(data)
    _save(root, reg)
    backup = root / BACKUP_DIR / rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(data)


def snapshot(root: Path) -> None:
    """Record every protected file as it is now (a new workspace, or one made before this guard existed)."""
    reg = {"files": {}, "skill": manifest_digest()}
    for rel in protected_files(root):
        data = (root / rel).read_bytes()
        reg["files"][rel] = _digest(data)
        backup = root / BACKUP_DIR / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(data)
    _save(root, reg)


def workspace_changes(root: Path) -> list[str]:
    """Protected files changed (or added) since the scripts last wrote them."""
    if _skip():
        return []
    reg = _load(root)
    if reg is None:
        snapshot(root)
        return []
    if reg.get("unreadable"):
        return [f"{REGISTRY} (unreadable)"]
    bad = []
    for rel in protected_files(root):
        digest = _digest((root / rel).read_bytes())
        if rel not in reg["files"]:
            bad.append(f"{rel} (not written by the scripts)")
        elif reg["files"][rel] != digest:
            bad.append(rel)
    return bad


def skill_binding_problem(root: Path) -> str | None:
    """The workspace remembers whether the skill had a manifest; one that disappears later was removed by hand."""
    if _skip():
        return None
    reg = _load(root)
    if reg is None or reg.get("unreadable"):
        return None
    current = manifest_digest()
    if reg.get("skill") and current is None:
        return "scripts/integrity.json was removed from the skill"
    if current and reg.get("skill") != current:          # the skill was installed or updated: remember it
        reg["skill"] = current
        _save(root, reg)
    return None


def restore(root: Path) -> list[str]:
    """Put back the scripts' last version of every changed protected file; set aside files the scripts never wrote.

    Every restore is logged in the registry (`incidents`), and the verification report lists them, so a reader
    knows the records were touched by hand even after they were put right."""
    reg = _load(root)
    if reg is None or reg.get("unreadable"):
        snapshot(root)
        reg = _load(root) or {"files": {}}
        reg.setdefault("incidents", []).append({"time": time.strftime("%Y-%m-%d %H:%M"), "files": [REGISTRY],
                                                "action": "the record of the scripts' files was missing or "
                                                          "unreadable; the workspace was recorded as it is now"})
        _save(root, reg)
        return [f"{REGISTRY}: recorded the workspace as it is now"]
    done, touched = [], []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for rel in protected_files(root):
        p = root / rel
        digest = _digest(p.read_bytes())
        if reg["files"].get(rel) == digest:
            continue
        touched.append(rel)
        backup = root / BACKUP_DIR / rel
        if rel in reg["files"] and backup.is_file() and _digest(backup.read_bytes()) == reg["files"][rel]:
            shutil.copyfile(backup, p)
            done.append(f"{rel}: put back the scripts' last version")
        elif rel in reg["files"]:
            # no usable copy is left (the backup folder was changed too): keep the file, but say so for good
            reg["files"][rel] = digest
            done.append(f"{rel}: no copy of the scripts' version is left, so the changed file was kept; the "
                        "verification report will say that this record was edited by hand")
        else:
            aside = root / BACKUP_DIR / "rejected" / f"{rel}.{stamp}"
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(aside))
            done.append(f"{rel}: not written by the scripts, moved to {aside.relative_to(root).as_posix()}")
    if touched:
        reg.setdefault("incidents", []).append({"time": time.strftime("%Y-%m-%d %H:%M"), "files": touched,
                                                "action": "; ".join(done)})
    _save(root, reg)
    return done


def incidents(root: Path) -> list[dict]:
    """Hand edits of script-owned files that `restore` dealt with (shown in the verification report)."""
    reg = _load(root)
    return list((reg or {}).get("incidents", []))
