"""Apply reviewed corrections (data/corrections.json) to a pass to produce the next pass.

Every change is an auditable record: {id, field, before, after, reason, evidence, found_by}.
`before` must match the current value, so stale corrections fail loudly.

Usage: python agent/apply_corrections.py data/pass1_llm.psv data/pass2_verified.psv
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from common import load_records, save_records  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
rows = {r["id"]: r for r in load_records(src)}
fixes = json.loads((ROOT / "data" / "corrections.json").read_text(encoding="utf-8"))
for f in fixes:
    r = rows[str(f["id"])]
    if r[f["field"]] != f["before"]:
        sys.exit(f"stale correction for #{f['id']} {f['field']}: expected {f['before']!r}, found {r[f['field']]!r}")
    r[f["field"]] = f["after"]
save_records(list(rows.values()), dst)
print(f"applied {len(fixes)} corrections across {len({f['id'] for f in fixes})} apps -> {dst}")
