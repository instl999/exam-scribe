"""Show or replace the chapter/section outline with a simple text format.

    chapter ch01 | 1 | Energy and Its Units
      section 1.1 | 1 | What Is Energy?
      section 1.2 | 3 | Units of Energy
      end ch01-end1 | 4 | Key Terms
    other | 15 | Answer Key

The middle column is the printed page label where the part starts.
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import ESError, Workspace, read_text, write_json
from .ingest import _find_heading_y

LINE_RE = re.compile(r"^\s*(chapter|section|end|other)\s*(\S*)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$", re.I)


def outline_text(ws: Workspace) -> str:
    o = ws.outline
    lab = lambda pos: ws.pages[min(pos["page"], len(ws.pages) - 1)]["label"]
    out = ["# ExamScribe outline (method: " + o.get("method", "?") + "). Edit and load with: outline <ws> --from-text <file>",
           "# kind id | start page label | title"]
    for c in o["chapters"]:
        out.append(f"chapter {c['id']} | {lab(c['start'])} | {c['title']}")
        for s in c["sections"]:
            kind = "section" if s["kind"] == "content" else "end"     # end matter and front matter: not studied
            out.append(f"  {kind} {s['id']} | {lab(s['start'])} | {s['title']}")
    for x in o.get("other", []):
        out.append(f"other | {lab(x['start'])} | {x['title']}")
    return "\n".join(out)


def load_outline_text(ws: Workspace, path: Path) -> str:
    rows = []
    for no, line in enumerate(read_text(path).splitlines(), start=1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            raise ESError(f"Line {no} is not 'kind id | page | title': {line.strip()}")
        kind, iid, page, title = m.group(1).lower(), m.group(2), m.group(3), m.group(4)
        p = ws.page_by_label(page)
        if p is None:
            raise ESError(f"Line {no}: no page labeled '{page}'.")
        y = _find_heading_y(p["paras"], title) or 0
        rows.append({"kind": kind, "id": iid, "page": p["index"], "y": max(0, y - (40 if kind == "chapter" else 0)),
                     "title": title})
    if not any(r["kind"] == "chapter" for r in rows):
        raise ESError("The outline needs at least one 'chapter' line.")
    starts = [(r["page"], r["y"]) for r in rows]
    chapters, other = [], []
    for i, r in enumerate(rows):
        nxt = starts[i + 1] if i + 1 < len(rows) else (len(ws.pages) - 1, 1e9)
        if r["kind"] == "other":
            other.append({"title": r["title"], "start": {"page": r["page"], "y": 0}, "end": {"page": nxt[0], "y": nxt[1]}})
            continue
        if r["kind"] == "chapter":
            num = re.sub(r"\D", "", r["id"]) or str(len(chapters) + 1)
            chapters.append({"id": r["id"], "number": num.lstrip("0") or "0", "title": r["title"], "kind": "chapter",
                             "start": {"page": r["page"], "y": r["y"]}, "end": None, "sections": []})
            continue
        if not chapters:
            raise ESError(f"'{r['kind']} {r['id']}' comes before any chapter line.")
        chapters[-1]["sections"].append({"id": r["id"], "title": r["title"],
                                         "kind": "end" if r["kind"] == "end" else "content",
                                         "start": {"page": r["page"], "y": r["y"]}})
    # ends
    flat = []
    for c in chapters:
        flat.append(c)
    for ci, c in enumerate(chapters):
        nxt_chapter = chapters[ci + 1]["start"] if ci + 1 < len(chapters) else None
        later_other = [o["start"] for o in other if (o["start"]["page"], o["start"]["y"]) > (c["start"]["page"], c["start"]["y"])]
        candidates = [x for x in [nxt_chapter] + later_other if x]
        end = min(candidates, key=lambda x: (x["page"], x["y"])) if candidates else {"page": len(ws.pages) - 1, "y": 1e9}
        c["end"] = dict(end)
        for si, s in enumerate(c["sections"]):
            s["end"] = dict(c["sections"][si + 1]["start"]) if si + 1 < len(c["sections"]) else dict(end)
        if not c["sections"]:
            c["sections"] = [{"id": f"{c['number']}.0", "title": c["title"], "kind": "content",
                              "start": dict(c["start"]), "end": dict(end)}]
    outline = {"method": "manual", "confirmed": True, "needs_review": False, "chapters": chapters, "other": other,
               "label_method": ws.outline.get("label_method"), "body_size": ws.outline.get("body_size")}
    write_json(ws.outline_path, outline)
    st = ws.state
    st.setdefault("stages", {}).pop("inventory", None)
    st["chapters"] = {}
    st["plan_confirmed"] = False
    st.pop("outline_review", None)
    scope = ws.config.get("scope") or {}
    if isinstance(scope.get("chapters"), list) and not all(c in {x["id"] for x in chapters} for c in scope["chapters"]):
        scope["chapters"] = "all"         # old chapter ids no longer exist; the page scope (if any) still applies
        ws.save_config()
    ws.save_state()
    ws.reload()
    return f"Outline replaced: {len(chapters)} chapter(s). The inventory will be rebuilt on the next `next`."


def confirm_outline(ws: Workspace) -> str:
    o = ws.outline
    o["confirmed"] = True
    o["needs_review"] = False
    write_json(ws.outline_path, o)
    ws.state.pop("outline_review", None)
    ws.save_state()
    return f"Outline confirmed: {len(o['chapters'])} chapter(s)."
