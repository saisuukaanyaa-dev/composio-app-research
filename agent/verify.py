"""Verification loop: score every claim in a research pass against crawled evidence.

Each claim becomes one of:
  supported    - a readable fetched page contains a matching signal
  unsupported  - readable evidence exists but nothing backs the claim
  broken_link  - the cited docs/auth URL does not resolve (4xx/5xx/error)
  no_evidence  - nothing readable could be fetched (JS-only page or bot wall)
It also raises review flags (e.g. strong auth signals for a method the pass did
not claim) that feed the human/agent correction queue.

Usage: python agent/verify.py data/pass1_llm.psv --label pass1
"""
import argparse, json, re, sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from common import load_records  # noqa: E402

READABLE = 800


def _root(rec):
    """Registrable domain of the app's own docs, e.g. 'pipedrive.com'."""
    host = urlparse(rec["docs_url"]).netloc
    return ".".join(host.split(".")[-2:])


def readable(p):
    return p["status"] == 200 and p["chars"] >= READABLE


def url_status(pages, url):
    for p in pages:
        if p["url"] == url:
            if p["status"] in (404, 410):
                return "broken_link"
            if p["status"] != 200:
                return "no_evidence"  # bot wall / network error: not proof the link is wrong
            return "supported" if readable(p) else "no_evidence"
    return "no_evidence"


def verify_record(rec):
    ev_path = ROOT / "evidence" / f"{rec['id']}.json"
    pages = json.loads(ev_path.read_text(encoding="utf-8"))["pages"] if ev_path.exists() else []
    good = [p for p in pages if readable(p)]
    hits = Counter()
    for p in good:
        hits.update(p["signals"])
    gh_path = ROOT / "evidence" / "mcp" / f"{rec['id']}.json"
    gh = json.loads(gh_path.read_text(encoding="utf-8")) if gh_path.exists() else {"status": "none_found", "repos": []}

    def check(key):
        if not good:
            return "no_evidence"
        return "supported" if hits.get(key) else "unsupported"

    flags = []
    claims = [{"field": "docs_url", "value": rec["docs_url"], "status": url_status(pages, rec["docs_url"])}]
    if rec["auth_url"] != rec["docs_url"]:
        claims.append({"field": "auth_url", "value": rec["auth_url"], "status": url_status(pages, rec["auth_url"])})
    for m in rec["auth"].split("+"):
        if m not in ("none", "unknown"):
            claims.append({"field": "auth", "value": m, "status": check(f"auth:{m}")})
    for a in rec["api"].split("+"):
        if a not in ("none",):
            claims.append({"field": "api", "value": a, "status": check(f"api:{a}")})
    if rec["access"] != "unknown":
        claims.append({"field": "access", "value": rec["access"], "status": check(f"access:{rec['access']}")})
    if rec["mcp"] in ("official", "community"):
        st = check("mcp")
        if st != "supported" and gh["status"] != "none_found":
            if rec["mcp"] == "community" or gh["status"] == "official_repo":
                st = "supported"
        claims.append({"field": "mcp", "value": rec["mcp"], "status": st})
    if rec["mcp"] == "none" and gh["status"] == "official_repo":
        flags.append("GitHub has a vendor-owned MCP repo but pass says none: " + ", ".join(r["repo"] for r in gh["repos"] if r["vendor_owned"]))

    flags = []
    claimed = set(rec["auth"].split("+"))
    for k, n in hits.items():
        if k.startswith("auth:") and n >= 5 and k[5:] not in claimed and k[5:] not in ("hmac", "bearer_token", "basic"):
            flags.append(f"strong evidence for unclaimed auth '{k[5:]}' ({n} hits)")
    if rec["mcp"] == "none" and hits.get("mcp", 0) >= 2:
        flags.append(f"MCP mentioned on docs ({hits['mcp']} hits) but pass says none")
    if rec["access"] in ("self_serve", "trial") and hits.get("access:partner", 0) >= 3 and not hits.get("access:self_serve"):
        flags.append("docs push 'contact sales' but pass says self-serve")
    # Loop 3 rules, generalized from misses found in the hand-checked sample
    vendor_mcp = sum(len(re.findall(r"(?:official|our|remote|hosted)\s+mcp|mcp server|\bmcp\b(?=[^.]{0,40}(?:setup|get started|install|connect))",
                                    p["text"], re.I)) for p in good if urlparse(p["final_url"]).netloc.endswith(_root(rec)))
    if rec["mcp"] == "community" and vendor_mcp >= 1:
        flags.append(f"vendor's own site documents an MCP server ({vendor_mcp} hits) but pass says community")
    free_plan = any(re.search(r"free plan|free forever|free tier|\$0\b|free account|hobby", p["text"], re.I) for p in good)
    timed_trial = any(re.search(r"\b\d{1,2}[- ]day free trial|free \d{1,2}[- ]day trial", p["text"], re.I) for p in good)
    if rec["access"] == "self_serve" and timed_trial and not free_plan:
        flags.append("docs advertise a time-limited free trial and no free plan, but pass says self_serve")
    for c in claims:
        if c["status"] in ("broken_link", "unsupported"):
            flags.append(f"{c['field']}={c['value']} is {c['status']}")
    return {"id": rec["id"], "name": rec["name"], "category": rec["category"], "claims": claims, "flags": flags,
            "readable_pages": len(good), "pages": len(pages), "github_mcp": gh["status"],
            "github_mcp_repos": [r["repo"] for r in gh["repos"][:3]]}


def summarize(results):
    st = Counter(c["status"] for r in results for c in r["claims"])
    total = sum(st.values())
    by_field = {}
    for r in results:
        for c in r["claims"]:
            by_field.setdefault(c["field"], Counter())[c["status"]] += 1
    checkable = st["supported"] + st["unsupported"] + st["broken_link"]
    omission = sum(1 for r in results for f in r["flags"] if "unclaimed" in f or "but pass says" in f)
    return {"claims": total, "status": dict(st),
            "supported_rate": round(st["supported"] / total, 3),
            "precision_on_checkable": round(st["supported"] / checkable, 3) if checkable else None,
            "omission_flags": omission,
            "by_field": {k: dict(v) for k, v in by_field.items()},
            "apps_flagged": sum(1 for r in results if r["flags"]),
            "apps_no_evidence": sum(1 for r in results if r["readable_pages"] == 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    results = [verify_record(r) for r in load_records(a.records)]
    summary = summarize(results)
    out = ROOT / "verification" / f"{a.label}_report.json"
    out.write_text(json.dumps({"label": a.label, "records": a.records, "summary": summary, "results": results}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"\nreview queue ({summary['apps_flagged']} apps):")
    for r in results:
        if r["flags"]:
            print(f"  #{r['id']} {r['name']}: " + "; ".join(r["flags"]))


if __name__ == "__main__":
    main()
