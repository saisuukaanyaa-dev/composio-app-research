"""Build the single-page case study (site/index.html) + machine-readable data.json / llms.txt.

All headline numbers are computed from the final verified pass, so the page can't drift from the data.
Usage: python agent/build_site.py
"""
import csv, html, json, os, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from common import load_records  # noqa: E402

V = ROOT / "verification"
FINAL = ROOT / "data" / "pass2_verified.psv"
CATS = ["CRM and Sales", "Support and Helpdesk", "Communications and Messaging", "Marketing, Ads, Email and Social", "Ecommerce",
        "Data, SEO and Scraping", "Developer, Infra and Data platforms", "Productivity and Project Management", "Finance and Fintech",
        "AI, Research and Media-native"]
ACCESS = ["self_serve", "trial", "paid", "approval", "partner", "unknown"]
ACCESS_LABEL = {"self_serve": "Self-serve (free)", "trial": "Free trial", "paid": "Paid plan", "approval": "App review / approval",
                "partner": "Partner / contact sales", "unknown": "Unknown"}
VERDICT_LABEL = {"ready": "Ready", "ready_with_review": "Ready with caveat", "blocked": "Blocked"}
AUTH_LABEL = {"oauth2": "OAuth 2.0", "api_key": "API key", "bearer_token": "Bearer / PAT", "basic": "Basic", "jwt": "JWT / key-pair",
              "hmac": "HMAC signing", "oauth1": "OAuth 1.0a", "none": "None (local CLI)", "unknown": "Unknown"}


def blocker_bucket(r):
    b = (r["blocker"] + " " + r["access_note"]).lower()
    if r["verdict"] == "ready" and r["access"] in ("self_serve", "trial"):
        return "None"
    if any(k in b for k in ("enterprise", "contract", "merchant account", "license", "tenant", "customer account", "customer workspace", "demo-led", "sales")):
        return "Enterprise contract / customer account"
    if any(k in b for k in ("review", "approval", "verification", "application", "developer token")):
        return "Platform app review / approval"
    if "paid" in b or "plan" in b or "credits" in b:
        return "Paid plan required"
    if any(k in b for k in ("no public", "no general", "no hosted", "not public", "rebrand")):
        return "No (stable) public API"
    if any(k in b for k in ("per-store", "per-instance", "self-host", "base url")):
        return "Self-hosted / per-instance URL"
    if any(k in b for k in ("kyc", "geo")):
        return "KYC / compliance"
    return "Other caveat" if r["verdict"] != "ready" else "None"


def load_report(label):
    p = V / f"{label}_report.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main():
    recs = load_records(FINAL)
    p1 = {r["id"]: r for r in load_records(ROOT / "data" / "pass1_llm.psv")}
    reports = {k: load_report(k) for k in ("pass1_naivecrawl", "pass1", "pass2")}
    ver = {r["id"]: r for r in reports["pass2"]["results"]}
    corrections = json.loads((ROOT / "data" / "corrections.json").read_text(encoding="utf-8"))
    sample = []
    sp = V / "sample_review.csv"
    if sp.exists():
        sample = list(csv.DictReader(open(sp, encoding="utf-8")))

    n = len(recs)
    auth_c = Counter(m for r in recs for m in r["auth"].split("+"))
    oauth_apps = sum("oauth2" in r["auth"].split("+") for r in recs)
    key_only = sum(set(r["auth"].split("+")) <= {"api_key", "bearer_token", "basic", "hmac"} for r in recs)
    access_c = Counter(r["access"] for r in recs)
    verdict_c = Counter(r["verdict"] for r in recs)
    mcp_c = Counter(r["mcp"] for r in recs)
    for r in recs:
        r["blocker_bucket"] = blocker_bucket(r)
    block_c = Counter(r["blocker_bucket"] for r in recs if r["blocker_bucket"] != "None")
    by_cat = defaultdict(list)
    for r in recs:
        by_cat[r["category"]].append(r)
    cat_rows = []
    for c in CATS:
        rs = by_cat[c]
        cat_rows.append({"cat": c, "n": len(rs), "access": Counter(r["access"] for r in rs), "verdict": Counter(r["verdict"] for r in rs),
                         "open": sum(r["access"] in ("self_serve", "trial") for r in rs), "mcp": sum(r["mcp"] == "official" for r in rs)})
    most_open = sorted(cat_rows, key=lambda x: -x["open"])
    easy = [r for r in recs if r["verdict"] == "ready" and r["access"] in ("self_serve", "trial")]
    outreach = [r for r in recs if r["access"] in ("partner", "approval") or r["verdict"] == "blocked"]

    s1n, s1, s2 = (reports[k]["summary"] for k in ("pass1_naivecrawl", "pass1", "pass2"))

    # sample (hand-graded) accuracy
    def acc(col):
        vals = [x[col] for x in sample if x.get(col) in ("1", "0")]
        return (sum(v == "1" for v in vals), len(vals))
    fields = ["auth", "access", "api", "mcp", "verdict"]
    samp = {f: {"p1": acc(f"p1_{f}"), "p2": acc(f"p2_{f}")} for f in fields}
    tot1 = [sum(samp[f]["p1"][i] for f in fields) for i in (0, 1)]
    tot2 = [sum(samp[f]["p2"][i] for f in fields) for i in (0, 1)]
    pct = lambda a, b: f"{(100 * a / b):.0f}%" if b else "n/a"  # noqa: E731

    oauth_and_key = sum("oauth2" in r["auth"].split("+") and bool(set(r["auth"].split("+")) & {"api_key", "bearer_token", "basic"}) for r in recs)
    names = lambda acc: ", ".join(r["name"] for r in recs if r["access"] == acc)  # noqa: E731

    def gate(c):
        g = Counter({k: v for k, v in c["access"].items() if k not in ("self_serve", "trial")}).most_common(1)
        return ACCESS_LABEL[g[0][0]].lower() if g else "none"

    headline = [
        f"<b>OAuth 2.0 dominates, but keys are the fast lane.</b> {oauth_apps}/{n} apps offer OAuth 2.0 and {key_only} are key/token-only. "
        f"{oauth_and_key} of the {oauth_apps} OAuth apps <i>also</i> issue a personal key or token, so a toolkit can ship on keys first and add OAuth for multi-tenant use. "
        f"The OAuth-only ones include the app-review platforms (Google Ads, LinkedIn, Amazon, Pinterest, Threads) and accounting (QuickBooks, Xero).",
        f"<b>{access_c['self_serve'] + access_c['trial']}/{n} are self-serve</b> ({access_c['self_serve']} free, {access_c['trial']} via free trial). "
        f"The gates are concentrated. {access_c['approval']} need platform app review ({names('approval')}). "
        f"{access_c['partner']} are partner / contact-sales ({names('partner')}), and {access_c['paid']} need a paid plan.",
        f"<b>Openness tracks category.</b> Fully open: " + ", ".join(f"{c['cat']} ({c['open']}/{c['n']})" for c in most_open if c['open'] == c['n']) +
        ". Most gated: " + ", ".join(f"{c['cat']} ({c['open']}/{c['n']}, mostly {gate(c)})" for c in most_open[-2:]) + ".",
        f"<b>The #1 blocker is commercial, not technical.</b> " + ", ".join(f"{k} ({v})" for k, v in block_c.most_common(3)) +
        f". Only {verdict_c['blocked']} apps are truly blocked today; {verdict_c['ready']} are ready and {verdict_c['ready_with_review']} are buildable with a caveat.",
        f"<b>MCP is already mainstream.</b> {mcp_c['official']}/{n} apps ship an official MCP server and {mcp_c['community']} more have community ones. "
        f"Several gated or API-less products (Clay, Otter, DealCloud, iPayX) now expose MCP before, or instead of, a broad REST API.",
        f"<b>{len(easy)} easy wins vs {len(outreach)} need outreach.</b> Easy wins are self-serve, documented and verdict ready; outreach means partnership, app review or a contract.",
    ]

    def bar(counter, labels, total, cls=""):
        out = []
        for k, v in counter.most_common():
            out.append(f'<div class="bar"><span class="bl">{html.escape(labels.get(k, k))}</span><span class="bt"><span class="bf {cls}" style="width:{100*v/total:.1f}%"></span></span><span class="bv">{v}</span></div>')
        return "\n".join(out)

    def matrix():
        head = "".join(f"<th>{ACCESS_LABEL[a]}</th>" for a in ACCESS if access_c[a])
        rows = []
        for c in cat_rows:
            cells = "".join(f'<td class="h{min(c["access"][a],5)} a-{a}">{c["access"][a] or ""}</td>' for a in ACCESS if access_c[a])
            rows.append(f"<tr><th>{c['cat']}</th>{cells}<td><b>{c['open']}/{c['n']}</b></td><td>{c['verdict']['ready']}/{c['verdict']['ready_with_review']}/{c['verdict']['blocked']}</td><td>{c['mcp']}</td></tr>")
        return f"<table class='matrix'><tr><th>Category</th>{head}<th>Self-serve</th><th>Ready / caveat / blocked</th><th>Official MCP</th></tr>{''.join(rows)}</table>"

    table_data = []
    for r in recs:
        v = ver[r["id"]]
        sup = sum(c["status"] == "supported" for c in v["claims"])
        changed = sorted({c["field"] for c in corrections if str(c["id"]) == r["id"]})
        table_data.append({**{k: r[k] for k in r}, "blocker_bucket": r["blocker_bucket"], "claims_supported": sup, "claims_total": len(v["claims"]),
                           "claim_status": v["claims"], "github_mcp": v["github_mcp"], "github_mcp_repos": v["github_mcp_repos"],
                           "corrected_fields": changed, "pass1": {k: p1[r["id"]][k] for k in ("auth", "access", "mcp", "verdict", "api", "docs_url")}})

    loops = [("Pass 1, naive HTTP crawl (first run)", s1n), ("Pass 1, same final evidence pool", s1), ("Pass 2, after reviewed corrections", s2)]
    loop_rows = "".join(
        f"<tr><td>{name}</td><td>{s['claims']}</td><td><b>{100*s['supported_rate']:.1f}%</b></td><td>{100*s['precision_on_checkable']:.1f}%</td>"
        f"<td>{s['status'].get('unsupported',0)}</td><td>{s['status'].get('broken_link',0)}</td><td>{s['status'].get('no_evidence',0)}</td><td><b>{s.get('omission_flags','-')}</b></td><td>{s['apps_flagged']}</td></tr>"
        for name, s in loops)
    field_rows = ""
    for f in ["docs_url", "auth_url", "auth", "api", "access", "mcp"]:
        a, b = s1["by_field"].get(f, {}), s2["by_field"].get(f, {})
        ta, tb = sum(a.values()) or 1, sum(b.values()) or 1
        field_rows += f"<tr><td>{f}</td><td>{100*a.get('supported',0)/ta:.0f}%</td><td>{100*b.get('supported',0)/tb:.0f}%</td></tr>"
    corr_kind = Counter(c["field"] for c in corrections)
    corr_rows = "".join(
        f"<tr><td>#{c['id']} {html.escape(p1[str(c['id'])]['name'])}</td><td>{c['field']}</td><td class='old'>{html.escape(c['before'] or '-')}</td>"
        f"<td class='new'>{html.escape(c['after'] or '-')}</td><td>{html.escape(c['reason'])}</td><td><a href='{html.escape(c['evidence'])}' target=_blank>evidence</a></td><td>{html.escape(c['found_by'])}</td></tr>"
        for c in corrections)
    samp_rows = "".join(f"<tr><td>{f}</td><td>{samp[f]['p1'][0]}/{samp[f]['p1'][1]} ({pct(*samp[f]['p1'])})</td><td>{samp[f]['p2'][0]}/{samp[f]['p2'][1]} ({pct(*samp[f]['p2'])})</td></tr>" for f in fields)
    misses = [x for x in sample if any(x.get(f"p2_{f}") == "0" for f in fields)]
    miss_rows = "".join(f"<tr><td>#{x['id']} {html.escape(x['name'])}</td><td>{html.escape(x['notes'])}</td></tr>" for x in sample if x.get("notes"))
    human_done = sum(1 for x in sample if x.get("human_confirmed", "").strip())
    residual = [r for r in reports["pass2"]["results"] if r["flags"]]
    residual_rows = "".join(f"<li><b>#{r['id']} {html.escape(r['name'])}</b>: {html.escape('; '.join(r['flags']))}</li>" for r in residual)

    data_json = {"generated_from": "data/pass2_verified.psv", "schema": {"auth": list(AUTH_LABEL), "access": ACCESS, "verdict": list(VERDICT_LABEL)},
                 "patterns": [html.unescape(h.replace("<b>", "").replace("</b>", "")) for h in headline],
                 "verification": {"pass1_naivecrawl": s1n, "pass1": s1, "pass2": s2, "hand_sample": samp, "corrections": len(corrections)},
                 "apps": table_data}
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site" / "data.json").write_text(json.dumps(data_json, indent=1), encoding="utf-8")

    tpl = (ROOT / "agent" / "template.html").read_text(encoding="utf-8")
    out = (tpl.replace("{{HEADLINE}}", "".join(f"<li>{h}</li>" for h in headline))
              .replace("{{N}}", str(n))
              .replace("{{AUTH_BARS}}", bar(auth_c, AUTH_LABEL, n, "auth"))
              .replace("{{ACCESS_BARS}}", bar(access_c, ACCESS_LABEL, n, "acc"))
              .replace("{{VERDICT_BARS}}", bar(verdict_c, VERDICT_LABEL, n, "ver"))
              .replace("{{BLOCK_BARS}}", bar(block_c, {}, n, "blk"))
              .replace("{{MCP_BARS}}", bar(mcp_c, {"official": "Official MCP", "community": "Community MCP", "none": "No MCP found"}, n, "mcp"))
              .replace("{{MATRIX}}", matrix())
              .replace("{{EASY}}", ", ".join(r["name"] for r in easy))
              .replace("{{OUTREACH}}", "".join(f"<li><b>{html.escape(r['name'])}</b>: {html.escape(r['blocker'] or ACCESS_LABEL[r['access']])}</li>" for r in outreach))
              .replace("{{OM1}}", str(s1["omission_flags"])).replace("{{OM2}}", str(s2["omission_flags"])).replace("{{N_NOT_EASY}}", str(n - len(easy)))
              .replace("{{NO_EVID}}", ", ".join(r["name"] for r in reports["pass2"]["results"] if r["readable_pages"] == 0) or "none")
              .replace("{{N_EASY}}", str(len(easy))).replace("{{N_OUT}}", str(len(outreach)))
              .replace("{{LOOP_ROWS}}", loop_rows).replace("{{FIELD_ROWS}}", field_rows)
              .replace("{{P1_RATE}}", f"{100*s1n['supported_rate']:.0f}%").replace("{{P2_RATE}}", f"{100*s2['supported_rate']:.0f}%")
              .replace("{{P1_PREC}}", f"{100*s1n['precision_on_checkable']:.0f}%").replace("{{P2_PREC}}", f"{100*s2['precision_on_checkable']:.0f}%")
              .replace("{{SAMPLE_N}}", str(len(sample))).replace("{{SAMPLE_ROWS}}", samp_rows)
              .replace("{{S1}}", pct(*tot1)).replace("{{S2}}", pct(*tot2))
              .replace("{{S1_RAW}}", f"{tot1[0]}/{tot1[1]}").replace("{{S2_RAW}}", f"{tot2[0]}/{tot2[1]}")
              .replace("{{HUMAN_DONE}}", str(human_done))
              .replace("{{MISS_ROWS}}", miss_rows or "<tr><td colspan=2>No sample yet</td></tr>")
              .replace("{{N_CORR}}", str(len(corrections))).replace("{{N_CORR_APPS}}", str(len({c['id'] for c in corrections})))
              .replace("{{CORR_KIND}}", ", ".join(f"{k} ({v})" for k, v in corr_kind.most_common()))
              .replace("{{CORR_ROWS}}", corr_rows)
              .replace("{{RESIDUAL}}", residual_rows).replace("{{N_RESIDUAL}}", str(len(residual)))
              .replace("{{REPO}}", os.getenv("REPO_URL", "https://github.com/YOUR_USER/composio-app-research"))
              .replace("{{DATA}}", json.dumps(table_data).replace("</", "<\\/")))
    (ROOT / "site" / "index.html").write_text(out, encoding="utf-8")
    llms = ["# Composio toolkit research: 100 apps", "", "Machine-readable data: data.json (same folder).", "", "## Patterns"] + \
           [f"- {p}" for p in data_json["patterns"]] + ["", "## Apps (name | category | auth | access | api | mcp | verdict | docs)"] + \
           [f"- {r['name']} | {r['category']} | {r['auth']} | {r['access']} | {r['api']} | {r['mcp']} | {r['verdict']} | {r['docs_url']}" for r in recs]
    (ROOT / "site" / "llms.txt").write_text("\n".join(llms), encoding="utf-8")
    print(f"built site/index.html ({len(out)//1024} KB), data.json, llms.txt")


if __name__ == "__main__":
    main()
