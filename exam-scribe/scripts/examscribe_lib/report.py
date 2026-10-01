"""The verification report: what was checked, what passed, and exactly what a human should double-check."""
from __future__ import annotations

import re

from . import verify as V
from .common import Workspace, read_json, read_text, rel, write_text
from .esm import covers, is_unsure, parse
from .render import badge, esc, page
from .ui import T, claim_text, flag_reason, use_language


def _doubtful_pages(ws: Workspace, flags_by_label: dict) -> dict:
    """Pages of the studied chapters whose text may be wrong (layout-only flags such as two-column are left out)."""
    keep = {"scanned-no-text", "garbled", "ocr", "math-heavy", "extraction-error"}
    in_scope: set[str] = set()
    for ch in ws.chapters_in_scope():
        for p in ws.pages[ch["start"]["page"]:ch["end"]["page"] + 1]:
            in_scope.add(p["label"])
    return {k: [f for f in v if f in keep] for k, v in flags_by_label.items() if k in in_scope and set(v) & keep}


def report_data(ws: Workspace) -> dict:
    quality = read_json(ws.quality_path, {}) or {}
    data = {"chapters": [], "totals": {"ok": 0, "warn": 0, "pending": 0, "unsure": 0, "skipped": 0, "planted": 0,
                                       "caught": 0, "rejected": 0, "q_ok": 0, "q_warn": 0, "q_pending": 0},
            "extraction": _doubtful_pages(ws, quality.get("pages", {})), "conflicts": []}
    for rec in ws.state.get("materials", {}).values():
        for tid, c in (rec.get("conflicts") or {}).items():
            data["conflicts"].append({"term": tid, **c})
    for ch in ws.chapters_in_scope():
        cid = ch["id"]
        if not ws.draft_dir(cid).exists():
            data["chapters"].append({"id": cid, "title": ch["title"], "started": False})
            continue
        inv = ws.inventory(cid)
        trust = V.chapter_trust(ws, cid)
        verdicts = V.load_verdicts(ws, cid)
        cs = ws.state.get("chapters", {}).get(cid, {})
        flagged = [dict(loc=loc, **v) for loc, v in trust["claims"].items() if v["status"] == "warn"]
        unsure, skipped, blocks_present, q_covers = [], [], {}, set()
        for path in V.draft_files(ws, cid):
            doc = parse(read_text(path), path)
            for b in doc.blocks:
                blocks_present[b.id] = b
                if b.get("skip"):
                    skipped.append({"id": b.id, "reason": b.value("skip"), "file": rel(path, ws.root), "line": b.line})
                for f in b.fields:
                    if is_unsure(f.value):
                        unsure.append({"id": b.id, "field": f.key, "reason": f.value[6:].lstrip(": "),
                                       "file": rel(path, ws.root), "line": f.line})
                if b.kind == "question" and not b.get("skip"):
                    q_covers.update(x for x in re.split(r"[,\s]+", b.value("covers")) if x)
                if b.kind == "must-know":
                    for f in b.all("point"):
                        q_covers.update(covers(f.value))
        coverage = {"covered": 0, "skipped": 0, "missing": []}
        for it in inv["items"]:
            if it["kind"] not in ("term", "equation", "example", "figure", "table"):
                continue
            b = blocks_present.get(it["id"])
            if b is None:
                coverage["missing"].append(it["id"])
            elif b.get("skip"):
                coverage["skipped"] += 1
            else:
                coverage["covered"] += 1
        los = [it["id"] for it in inv["items"] if it["kind"] == "objective"]
        sums = [it["id"] for it in inv["items"] if it["kind"] == "summary"]
        stats = verdicts.get("canary_stats", {})
        qs = trust["questions"]
        chd = {"id": cid, "title": ch["title"], "started": True, "counts": trust["counts"], "flagged": flagged,
               "formulas": trust["formulas"], "questions": qs, "unsure": unsure, "skipped": skipped,
               "coverage": coverage, "lo_untested": [x for x in los if x not in q_covers],
               "summary_uncovered": [x for x in sums if x not in q_covers], "canaries": stats,
               "accepted_flags": cs.get("flags", {})}
        data["chapters"].append(chd)
        t = data["totals"]
        for k in ("ok", "warn", "pending"):
            t[k] += trust["counts"].get(k, 0)
        t["unsure"] += len(unsure)
        t["skipped"] += len(skipped)
        t["planted"] += stats.get("planted", 0)
        t["caught"] += stats.get("caught", 0)
        t["rejected"] += stats.get("rejected_batches", 0)
        for v in qs.values():
            t["q_" + v["status"]] += 1
    return data


def report_text(ws: Workspace) -> str:
    d = report_data(ws)
    t = d["totals"]
    lines = ["VERIFICATION REPORT",
             f"Claims: {t['ok']} verified, {t['warn']} to check, {t['pending']} not yet verified.",
             f"Questions: {t['q_ok']} answer keys confirmed, {t['q_warn']} disputed, {t['q_pending']} pending.",
             f"Attention tests: {t['caught']}/{t['planted']} planted false claims caught; {t['rejected']} batch(es) redone.",
             f"Marked UNSURE by the writer: {t['unsure']}; skipped blocks: {t['skipped']}."]
    for c in d["chapters"]:
        if not c.get("started"):
            lines.append(f"- {c['id']} {c['title']}: not started")
            continue
        cov = c["coverage"]
        lines.append(f"- {c['id']} {c['title']}: {c['counts']['ok']} ok / {c['counts']['warn']} check / "
                     f"{c['counts']['pending']} pending; inventory covered {cov['covered']}, skipped {cov['skipped']}, "
                     f"missing {len(cov['missing'])}; objectives without a question: {len(c['lo_untested'])}")
        for f in c["flagged"][:10]:
            lines.append(f"    check {f['file']}:{f['line']} [{f['block']}] {f['claim'][:90]} — "
                         f"{'; '.join(f['reasons'])[:120]}")
    if d["extraction"]:
        lines.append("Pages with extraction warnings: " + ", ".join(f"p.{k} ({', '.join(v)})" for k, v in
                                                                     list(d["extraction"].items())[:15]))
    if d["conflicts"]:
        lines.append(f"Instructor material differs from the book for {len(d['conflicts'])} term(s).")
    return "\n".join(lines)


def _fill(text: str, **parts: str) -> str:
    """Escaped page text with HTML parts (badges, bold numbers) put in at its placeholders."""
    marks = {k: chr(0xE000 + i) for i, k in enumerate(parts)}
    out = esc(T(text, **marks))
    for k, m in marks.items():
        out = out.replace(m, parts[k])
    return out


def render_report(ws: Workspace) -> dict:
    use_language(ws)
    d = report_data(ws)
    t = d["totals"]
    colon = T(": ")
    parts = [f"<h1>{esc(T('Verification report'))}</h1>",
             "<p>" + _fill("{ok} claims verified · {warn} to check · {pending} not yet verified",
                           **{k: f"{badge(k)} <strong>{t[k]}</strong>" for k in ("ok", "warn", "pending")}) + "</p>",
             "<p>" + _fill("Answer keys: {ok} confirmed by an independent solver, {warn} disputed, {pending} pending.",
                           ok=f"<strong>{t['q_ok']}</strong>", warn=f"<strong>{t['q_warn']}</strong>",
                           pending=str(t["q_pending"])) + "</p>",
             "<p>" + _fill("Attention tests: the checker caught {caught} of {planted} planted false claims; {rejected} "
                           "batch(es) had to be redone.", caught=f"<strong>{t['caught']}</strong>",
                           planted=f"<strong>{t['planted']}</strong>", rejected=str(t["rejected"])) + "</p>",
             "<p class='muted'>" + esc(T("How to read this: every claim in the notes quotes the book; a script confirmed "
                                         "each quote is on the cited page and recomputed every calculation; then an "
                                         "independent checker compared each claim with the book text. Anything below "
                                         "needs a human look before you rely on it.")) + "</p>"]
    for c in d["chapters"]:
        if not c.get("started"):
            parts.append(f"<h2>{esc(c['id'])} {esc(c['title'])}</h2><p class='muted'>{esc(T('Not started yet.'))}</p>")
            continue
        cov = c["coverage"]
        parts.append(f"<h2>{esc(c['id'])} {esc(c['title'])}</h2>")
        missing = colon + ", ".join(cov["missing"]) if cov["missing"] else ""
        parts.append("<p>" + esc(T("Coverage of the book’s key items: {covered} covered, {skipped} skipped (reasons below), "
                                   "{missing} missing{list}.", covered=cov["covered"], skipped=cov["skipped"],
                                   missing=len(cov["missing"]), list=missing)) + " " +
                     esc(T("Learning objectives without a question: {list}.",
                           list=", ".join(c["lo_untested"]) or T("none"))) + "</p>")
        if c["flagged"]:
            rows = "".join(f"<tr><td>{esc(f['block'])}<br><span class='muted'>{esc(f['file'])}:{f['line']}</span></td>"
                           f"<td>{esc(claim_text(f['claim']))}</td><td>p.{esc(', p.'.join(dict.fromkeys(f['pages'])))}</td>"
                           f"<td>{esc('; '.join(flag_reason(r) for r in f['reasons']))}</td></tr>" for f in c["flagged"])
            heads = "".join(f"<th>{esc(T(h))}</th>" for h in ("Where", "Claim", "Book", "Why flagged"))
            parts.append(f"<h3>{esc(T('Claims to check'))}</h3><div class='scroll'><table><tr>{heads}</tr>{rows}</table></div>")
        bad_f = {k: v for k, v in c["formulas"].items() if v["status"] == "warn"}
        if bad_f:
            parts.append(f"<h3>{esc(T('Formulas to check against the printed book'))}</h3><ul>" +
                         "".join(f"<li>{esc(k)}{esc(colon)}{esc(flag_reason(v.get('reason', '')))}</li>"
                                 for k, v in bad_f.items()) + "</ul>")
        bad_q = {k: v for k, v in c["questions"].items() if v["status"] == "warn"}
        if bad_q:
            parts.append(f"<h3>{esc(T('Questions with disputed answer keys (left out of practice sets)'))}</h3><ul>" +
                         "".join(f"<li>{esc(k)}{esc(colon)}{esc(v.get('reason', ''))}</li>" for k, v in bad_q.items()) + "</ul>")
        if c["unsure"]:
            parts.append(f"<h3>{esc(T('Marked UNSURE by the writer'))}</h3><ul>" +
                         "".join(f"<li>{esc(u['id'])}.{esc(u['field'])}{esc(colon)}{esc(u['reason'])} "
                                 f"<span class='muted'>({esc(u['file'])}:{u['line']})</span></li>" for u in c["unsure"]) + "</ul>")
        if c["skipped"]:
            parts.append(f"<h3>{esc(T('Skipped items'))}</h3><ul>" + "".join(
                f"<li>{esc(s['id'])}{esc(colon)}{esc(s['reason'])}</li>" for s in c["skipped"]) + "</ul>")
    if d["extraction"]:
        items = list(d["extraction"].items())
        more = f"<li>{esc(T('… and {n} more', n=len(items) - 80))}</li>" if len(items) > 80 else ""
        note = T("Quotes from these pages are marked for checking (on OCR pages: quotes with numbers). Pictures of these "
                 "pages are in {folder} (or run: {command}).", folder="source/page-images/",
                 command="page <workspace> <page> --image")
        parts.append(f"<h2>{esc(T('Pages where text extraction may be unreliable'))}</h2><p class='muted'>{esc(note)}</p><ul>" +
                     "".join(f"<li>p.{esc(k)}: {esc(', '.join(v))}</li>" for k, v in items[:80]) + more + "</ul>")
    if d["conflicts"]:
        parts.append(f"<h2>{esc(T('Instructor material vs. book'))}</h2><ul>" + "".join(
            f"<li>{esc(c['term'])}: {esc(c['verdict'])} — {esc(c['explain'])} ({esc(c['material'])})</li>"
            for c in d["conflicts"]) + "</ul>")
    path = ws.site_dir / "report.html"
    write_text(path, page(ws, T("Verification report"), "\n".join(parts), crumb=T("Verification report")))
    md = ws.export_dir / "verification-report.md"
    write_text(md, "```\n" + report_text(ws) + "\n```\n")
    return {"path": path, "md": md, "totals": t}
