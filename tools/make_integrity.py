"""Write exam-scribe/scripts/integrity.json: the SHA-256 of every file the skill ships.

    python tools/make_integrity.py           # after changing any file of the skill, before packaging
    python tools/make_integrity.py --check   # exit 1 if the manifest is out of date

The scripts compare the installed skill with this list and stop when a file differs, so an agent cannot quietly
change a checker to get past it. Users who customise the skill on purpose run this tool to accept their changes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exam-scribe" / "scripts"))
from examscribe_lib.integrity import MANIFEST, make_manifest  # noqa: E402


def main() -> int:
    data = make_manifest()
    text = json.dumps(data, indent=1, sort_keys=True) + "\n"
    if "--check" in sys.argv[1:]:
        current = MANIFEST.read_text(encoding="utf-8").replace("\r\n", "\n") if MANIFEST.exists() else ""
        if current != text:
            print(f"{MANIFEST} is out of date: run python tools/make_integrity.py")
            return 1
        print(f"{MANIFEST} is up to date ({len(data['files'])} files).")
        return 0
    MANIFEST.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {MANIFEST} ({len(data['files'])} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
