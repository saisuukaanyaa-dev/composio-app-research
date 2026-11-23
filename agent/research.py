"""Research agent: crawl each app's docs and extract evidence signals.

Stage 1 (always): fetch docs_url, auth_url and the homepage, follow up to
MAX_EXTRA same-site links whose URL/anchor looks like auth / pricing / MCP /
developer pages, and cache plain text to evidence/<id>.json.

Stage 2 (optional, --llm): send the cached evidence to an OpenAI-compatible
chat model and ask it to fill the research schema, citing a fetched URL for
each answer. Writes data/llm_from_evidence.psv.

Usage:
    python agent/research.py                       # crawl all 100
    python agent/research.py --ids 1 2 3 --force   # re-crawl some apps
    python agent/research.py --llm                 # also synthesize with an LLM
"""
import argparse, concurrent.futures as cf, json, os, re, subprocess, sys, threading, time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:  # use the OS trust store (corporate TLS inspection breaks certifi)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

BROWSERS = [os.getenv("BROWSER_PATH"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/usr/bin/chromium", "/usr/bin/google-chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from common import load_records, save_records, SIGNALS, signal_hits  # noqa: E402

EVID = ROOT / "evidence"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
MAX_EXTRA = 5
MAX_CHARS = 80_000
LINK_HINT = re.compile(r"auth|oauth|api[-_ ]?key|token|pricing|plans|mcp|developer|getting[-_ ]started|rate[-_ ]limit", re.I)


def parse(url, final_url, status, html, via):
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    links = [(urljoin(final_url, a["href"]).split("#")[0], a.get_text(" ", strip=True)[:80]) for a in soup.find_all("a", href=True)]
    return {"url": url, "final_url": final_url, "status": status, "via": via, "title": title[:200],
            "text": text[:MAX_CHARS], "chars": len(text), "links": links}


def fetch_http(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}, timeout=25, allow_redirects=True)
        ctype = r.headers.get("content-type", "")
        html = r.text if ("html" in ctype or "text" in ctype or "json" in ctype) else ""
        return parse(url, r.url, r.status_code, html, "http")
    except Exception as e:
        return {"url": url, "final_url": url, "status": 0, "via": "http", "title": "", "text": "", "chars": 0, "links": [], "error": str(e)[:200]}


BROWSER_SLOTS = threading.Semaphore(4)


def fetch_browser(url):
    """Render with headless Edge/Chrome so JS docs and bot walls can be read like a human would."""
    exe = next((p for p in BROWSERS if p and Path(p).exists()), None)
    if not exe:
        return None
    with BROWSER_SLOTS:
        try:
            html = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-agent={UA}",
                                   "--virtual-time-budget=10000", "--dump-dom", url],
                                  capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=60).stdout
        except Exception as e:
            return {"url": url, "final_url": url, "status": 0, "via": "browser", "title": "", "text": "", "chars": 0, "links": [], "error": str(e)[:200]}
    page = parse(url, url, 200 if html.strip() else 0, html, "browser")
    if re.search(r"\b(404|page not found|page doesn.t exist|could not be found)\b", page["title"], re.I):
        page["status"] = 404
    return page


PROXY_BLOCK = re.compile(r"This Page Is Restricted|internet usage polic|Proxy name|Your IP Address", re.I)


def scrub(page):
    """Corporate proxy block/error pages are not evidence and contain user/IP details: drop their text."""
    if PROXY_BLOCK.search(page.get("text", "")[:3000]) or PROXY_BLOCK.search(page.get("title", "")):
        page.update(status=451, text="", chars=0, title="(blocked by network proxy)", links=[], error="network proxy block page")
    return page


def fetch(url):
    page = scrub(fetch_http(url))
    if page["status"] in (404, 410):
        return page
    if page["status"] != 200 or page["chars"] < 800:
        rendered = fetch_browser(url)
        if rendered:
            rendered = scrub(rendered)
        if rendered and rendered["chars"] > page["chars"]:
            rendered["http_status"] = page["status"]
            return rendered
    return page


def homepage(hint):
    host = hint.split()[0].strip().rstrip("/")
    host = re.sub(r"^https?://", "", host)
    return "https://" + host


def crawl(rec, force=False, merge=False):
    out = EVID / f"{rec['id']}.json"
    if out.exists() and not force and not merge:
        return json.loads(out.read_text(encoding="utf-8"))
    prev = json.loads(out.read_text(encoding="utf-8"))["pages"] if (merge and out.exists()) else []
    seeds = []
    for u in (rec["docs_url"], rec["auth_url"], homepage(rec["hint"])):
        if u and u not in seeds and u not in {p["url"] for p in prev}:
            seeds.append(u)
    pages = [fetch(u) for u in seeds]
    seen = {p["final_url"] for p in pages + prev} | set(seeds) | {p["url"] for p in prev}
    domains = {urlparse(p["final_url"]).netloc for p in pages if p["status"] == 200}
    candidates = []
    for p in pages:
        for href, label in p["links"]:
            if href in seen or urlparse(href).netloc not in domains:
                continue
            if LINK_HINT.search(href) or LINK_HINT.search(label):
                candidates.append(href)
                seen.add(href)
    pages += [fetch(u) for u in candidates[:MAX_EXTRA]]
    for p in pages:
        p.pop("links", None)
        p["signals"] = signal_hits(p["text"])
    pages = prev + pages
    doc = {"id": rec["id"], "name": rec["name"], "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "pages": pages}
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc


LLM_PROMPT = """You are researching whether an app can become an AI-agent toolkit.
Using ONLY the evidence pages below, return JSON with keys:
one_liner, auth (list from: oauth2, api_key, basic, bearer_token, jwt, hmac, oauth1, none, unknown),
access (one of: self_serve, trial, paid, approval, partner, unknown), access_note,
api (e.g. REST, GraphQL, REST+GraphQL, CLI, MCP, none), breadth (broad|medium|narrow),
mcp (official|community|none), verdict (ready|ready_with_review|blocked), blocker,
docs_url, auth_url (must be URLs from the evidence). Use "unknown" rather than guessing.
App: {name} ({hint})
Evidence:
{evidence}"""


def llm_synthesize(rec, doc):
    from openai import OpenAI  # optional dependency
    client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL"))
    ev = "\n\n".join(f"URL: {p['final_url']}\n{p['text'][:6000]}" for p in doc["pages"] if p["status"] == 200)
    msg = LLM_PROMPT.format(name=rec["name"], hint=rec["hint"], evidence=ev[:40000])
    resp = client.chat.completions.create(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), messages=[{"role": "user", "content": msg}],
                                          response_format={"type": "json_object"})
    data = json.loads(resp.choices[0].message.content)
    new = dict(rec)
    for k, v in data.items():
        if k in new:
            new[k] = "+".join(v) if isinstance(v, list) else str(v)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "data" / "pass1_llm.psv"))
    ap.add_argument("--ids", nargs="*", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--merge", action="store_true", help="add pages for new URLs to existing evidence (used for corrected passes)")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    EVID.mkdir(exist_ok=True)
    recs = [r for r in load_records(a.input) if not a.ids or int(r["id"]) in a.ids]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        docs = list(ex.map(lambda r: crawl(r, a.force, a.merge), recs))
    ok = sum(any(p["status"] == 200 and p["chars"] > 800 for p in d["pages"]) for d in docs)
    print(f"crawled {len(docs)} apps; {ok} have at least one readable page; {sum(len(d['pages']) for d in docs)} pages total")
    if a.llm:
        out = [llm_synthesize(r, d) for r, d in zip(recs, docs)]
        save_records(out, ROOT / "data" / "llm_from_evidence.psv")
        print("wrote data/llm_from_evidence.psv")


if __name__ == "__main__":
    main()
