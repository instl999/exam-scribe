"""Create a ready-to-write workspace from the sample textbook (for development and tests).

    python tools/dev_setup.py <workspace-dir> [--tier strict] [--formats mcq,problems,short-answer]

Runs init, ingest, the intake answers and plan confirmation, then prints the first task card.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exam-scribe" / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from examscribe_lib.common import Workspace, setup_console  # noqa: E402
from examscribe_lib.config import init_workspace, set_key  # noqa: E402
from examscribe_lib.ingest import ingest  # noqa: E402


def make(ws_dir: Path, tier: str = "strict", formats: str = "mcq,problems,short-answer",
         book: Path | None = None) -> Workspace:
    if book is None:
        book = ROOT / "tests" / "fixtures" / "out" / "sample-textbook.pdf"
        if not book.exists():
            import make_book
            make_book.build(book)
    if ws_dir.exists():
        shutil.rmtree(ws_dir)
    ws = init_workspace(ws_dir, book, tier, None, "en")
    ingest(ws)
    for k, v in (("exam.date", "2026-12-15"), ("exam.formats", formats), ("exam.book_policy", "closed"),
                 ("scope.chapters", "all"), ("subject", "chemistry"), ("study.hours_per_day", "2"),
                 ("output.language", "en"), ("intake.done", "true")):
        set_key(ws, k, v)
    from examscribe_lib.priority import compute_priorities
    compute_priorities(ws)
    ws.state["plan_confirmed"] = True
    ws.save_state()
    return ws


if __name__ == "__main__":
    setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--tier", default="strict")
    ap.add_argument("--formats", default="mcq,problems,short-answer")
    a = ap.parse_args()
    w = make(Path(a.workspace).resolve(), a.tier, a.formats)
    from examscribe_lib.pipeline import compute_next, render_card
    print(render_card(w, compute_next(w)))
