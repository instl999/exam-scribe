"""Download the real books used by trials/realbook_eval.py into trials/corpus/ (about 240 MB in all).

    python trials/get_corpus.py

Books already in the folder are skipped. Sources and licences: trials/corpus/README.md.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

BOOKS = {
    "es-openstax-quimica-2ed.pdf": "https://assets.openstax.org/oscms-prodcms/media/documents/Quimica-2ed-WEB.pdf",
    "zh-d2l-pytorch.pdf": "https://zh-v2.d2l.ai/d2l-zh-pytorch.pdf",
    "ja-mext-joho1-ch1.pdf": "https://www.mext.go.jp/content/20200722-mxt_jogai02-100013300_003.pdf",
    "de-bpb-izpb332-demokratie.pdf": "https://www.bpb.de/system/files/dokument_pdf/"
                                     "170510_BPB_667-17_IzpB%20332%20Demokratie_10_barrierefrei.pdf",
    "en-scan-household-chemistry-1914.pdf": "https://archive.org/download/elementaryhouse00snelgoog/"
                                            "elementaryhouse00snelgoog.pdf",
}


def main() -> None:
    out = Path(__file__).resolve().parent / "corpus"
    out.mkdir(exist_ok=True)
    for name, url in BOOKS.items():
        dest = out / name
        if dest.exists():
            print(f"have {name}")
            continue
        print(f"downloading {name} ...", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ExamScribe corpus download)"})
        part = dest.with_name(dest.name + ".part")
        with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        part.replace(dest)
        print(f"  {dest.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
