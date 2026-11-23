"""Second evidence source for MCP claims: search public GitHub for MCP servers.

Docs sites often don't mention MCP servers that live on GitHub, so the
verifier also accepts a GitHub repo as evidence. A repo counts as "official"
when the owner looks like the vendor (owner contains the app/domain token).
Results are cached in evidence/mcp/<id>.json. Unauthenticated search is
limited to 10 req/min, so this sleeps between calls (set GITHUB_TOKEN to speed up).

Usage: python agent/mcp_check.py [--force] [ids...]
"""
import json, os, re, sys, time
from pathlib import Path

import requests

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from common import load_records  # noqa: E402

OUT = ROOT / "evidence" / "mcp"
OUT.mkdir(parents=True, exist_ok=True)
ALIASES = {"Jira": ["atlassian"], "QuickBooks": ["intuit"], "Sentry": ["getsentry"], "Snowflake": ["snowflake-labs"],
           "Meta Ads": ["meta", "facebook"], "Threads (Meta)": ["meta"], "WhatsApp Business": ["meta", "whatsapp"],
           "Google Ads": ["google", "googleads"], "LinkedIn Ads": ["linkedin"], "NotebookLM": ["google"],
           "Monday.com": ["mondaycom"], "Lark (Larksuite)": ["larksuite"], "Devin": ["cognition", "deepwiki"],
           "Salesforce Commerce Cloud": ["salesforce", "sfcc"], "Magento (Adobe Commerce)": ["adobe", "magento"],
           "Amazon Selling Partner": ["amzn", "amazon"], "YouTube Transcript": ["transcriptapi"], "Mermaid CLI": ["mermaid-js"],
           "Paygent Connect": ["nmi"], "Bright Data": ["brightdata", "luminati"], "MongoDB Atlas": ["mongodb"], "Neo4j": ["neo4j"]}


def tokens(rec):
    base = re.sub(r"\(.*?\)", "", rec["name"]).strip().lower()
    toks = {re.sub(r"[^a-z0-9]", "", base)}
    dom = re.sub(r"^https?://", "", rec["hint"].split()[0]).split("/")[0]
    toks.add(dom.split(".")[-2] if dom.count(".") >= 1 else dom)
    toks.update(ALIASES.get(rec["name"], []))
    return {t for t in toks if len(t) >= 3}


def search(rec):
    q = re.sub(r"\(.*?\)", "", rec["name"]).strip()
    headers = {"Accept": "application/vnd.github+json"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    for attempt in range(3):
        r = requests.get("https://api.github.com/search/repositories", headers=headers, timeout=30,
                         params={"q": f'"{q}" mcp in:name,description', "sort": "stars", "per_page": 10})
        if r.status_code == 403 and "rate limit" in r.text.lower():
            time.sleep(65)
            continue
        r.raise_for_status()
        break
    toks = tokens(rec)
    repos = []
    for it in r.json().get("items", []):
        owner = it["owner"]["login"].lower()
        text = (it["name"] + " " + (it["description"] or "")).lower()
        if "mcp" not in text and "model context protocol" not in text:
            continue
        repos.append({"repo": it["full_name"], "stars": it["stargazers_count"], "url": it["html_url"],
                      "vendor_owned": any(t in owner for t in toks)})
    return repos


def main():
    force = "--force" in sys.argv
    only = {a for a in sys.argv[1:] if a.isdigit()}
    delay = 1 if os.getenv("GITHUB_TOKEN") else 6.5
    for rec in load_records(ROOT / "data" / "pass1_llm.psv"):
        if only and rec["id"] not in only:
            continue
        path = OUT / f"{rec['id']}.json"
        if path.exists() and not force:
            continue
        repos = search(rec)
        status = "official_repo" if any(r["vendor_owned"] for r in repos) else ("community_repo" if repos else "none_found")
        path.write_text(json.dumps({"id": rec["id"], "name": rec["name"], "status": status, "repos": repos}, indent=1), encoding="utf-8")
        print(f"#{rec['id']} {rec['name']}: {status} {[r['repo'] for r in repos[:3]]}", flush=True)
        time.sleep(delay)


if __name__ == "__main__":
    main()
