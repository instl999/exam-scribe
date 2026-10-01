"""Load a chapter's drafts into one structure (blocks by section + trust) for rendering and exports."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import verify as V
from .common import Workspace, read_text, rel
from .esm import Block, parse
from .lint import block_key

RANK = {"ok": 0, "pending": 1, "warn": 2}


@dataclass
class NoteBlock:
    blk: Block
    file: str
    section: str | None

    @property
    def id(self) -> str:
        return self.blk.id

    @property
    def kind(self) -> str:
        return self.blk.kind

    @property
    def key(self) -> str:
        return block_key(self.blk)


@dataclass
class ChapterNotes:
    ws: Workspace
    ch: dict
    inv: dict
    blocks: list[NoteBlock] = field(default_factory=list)
    trust: dict = field(default_factory=dict)

    def section_blocks(self, sid: str) -> list[NoteBlock]:
        return [b for b in self.blocks if b.section == sid and b.kind not in ("question",)]

    def of_kind(self, *kinds: str) -> list[NoteBlock]:
        return [b for b in self.blocks if b.kind in kinds]

    def chapter_block(self, kind: str) -> NoteBlock | None:
        for b in self.blocks:
            if b.kind == kind and b.id == self.ch["id"]:
                return b
        return None

    def questions(self) -> list[NoteBlock]:
        return [b for b in self.blocks if b.kind == "question" and not b.blk.get("skip")]

    # ------------------------------------------------------------------ trust
    def field_status(self, nb: NoteBlock, key: str, occurrence: int) -> tuple[str, list[str]]:
        prefix = f"{nb.file}#{nb.key}#{key}#{occurrence}#"
        found = [v for loc, v in self.trust.get("claims", {}).items() if loc.startswith(prefix)]
        if not found:
            return "", []
        worst = max(found, key=lambda v: RANK[v["status"]])
        reasons = [r for v in found for r in v.get("reasons", [])]
        return worst["status"], reasons

    def block_status(self, nb: NoteBlock) -> str:
        if nb.kind == "question":
            return self.trust.get("questions", {}).get(nb.id, {}).get("status", "pending")
        prefix = f"{nb.file}#{nb.key}#"
        found = [v["status"] for loc, v in self.trust.get("claims", {}).items() if loc.startswith(prefix)]
        if nb.kind == "formula":
            f = self.trust.get("formulas", {}).get(nb.id)
            if f:
                found.append(f["status"])
        if not found:
            return "pending" if not nb.blk.get("skip") else ""
        return max(found, key=lambda s: RANK[s])


def _section_of(bid: str, file_section: str | None, inv_items: dict) -> str | None:
    it = inv_items.get(bid)
    if it and it.get("section"):
        return it["section"]
    m = re.match(r"^Q-(.+)-\d+$", bid)
    if m:
        part = m.group(1)
        return re.sub(r"\.p\d+$", "", part)
    return file_section


def load_chapter(ws: Workspace, cid: str, with_trust: bool = True) -> ChapterNotes:
    ch = ws.chapter(cid)
    inv = ws.inventory(cid)
    items = {it["id"]: it for it in inv["items"]}
    notes = ChapterNotes(ws, ch, inv)
    for path in V.draft_files(ws, cid):
        doc = parse(read_text(path), path)
        fsec = None if path.name == "chapter.md" else re.sub(r"\.p\d+$", "", path.stem)
        if fsec and fsec.endswith("-all"):
            fsec = None
        for blk in doc.blocks:
            sec = None if path.name == "chapter.md" else _section_of(blk.id, fsec, items)
            notes.blocks.append(NoteBlock(blk, rel(path, ws.root), sec))
    if with_trust and notes.blocks:
        notes.trust = V.chapter_trust(ws, cid)
    return notes
