"""Reviewer helper: show the evidence snippets behind a signal for one app.

Usage: python agent/inspect_evidence.py 95 mcp
       python agent/inspect_evidence.py 26 --status      # page fetch statuses
"""
import json, re, sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from common import SIGNALS  # noqa: E402

app = sys.argv[1]
doc = json.loads((ROOT / "evidence" / f"{app}.json").read_text(encoding="utf-8"))
if "--status" in sys.argv:
    for p in doc["pages"]:
        print(p["status"], p["chars"], p["url"], "->", p["final_url"], p.get("error", ""))
    sys.exit()
key = sys.argv[2]
pat = re.compile(SIGNALS.get(key, key), re.I)
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 4
for p in doc["pages"]:
    ms = list(pat.finditer(p["text"]))[:limit]
    for m in ms:
        s = p["text"][max(0, m.start() - 110): m.end() + 110]
        print(f"[{p['final_url']}] ...{s}...")

