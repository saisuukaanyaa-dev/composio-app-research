# Composio toolkit research: 100 apps

Can each of 100 apps become an AI-agent toolkit today? This repo answers that question for every app (auth, self-serve vs gated, API surface, MCP, verdict and evidence). The research is done by an agent pipeline that **verifies its own answers against live docs**.

**Deliverable:** [`site/index.html`](site/index.html), a single self-contained case study page. It also ships [`site/data.json`](site/data.json) and [`site/llms.txt`](site/llms.txt) for agents.

## Results at a glance
| Metric | Pass 1 (LLM draft) | Pass 2 (after verification loops) |
|---|---|---|
| Field accuracy, hand-checked stratified sample (20 apps × 5 fields) | 73/93 (78.5%) | 88/93 (94.6%) |
| Claims backed by fetched evidence (all 100 apps) | 91.2% | 92.3% |
| Omission flags (the docs show something the pass didn't claim) | 71 | 35 |
| Broken evidence links | 3 | 0 |

## Pipeline
```
data/pass1_llm.psv ── research.py ──► evidence/<id>.json   (HTTP + headless-browser fallback; links to auth/pricing/MCP pages)
                    └ mcp_check.py ──► evidence/mcp/<id>.json (GitHub search for MCP servers, vendor-owned = official)
                         verify.py ──► verification/pass1_report.json + review queue (flags)
       inspect_evidence.py (human) ──► data/corrections.json   (before → after, reason, evidence URL, who found it)
              apply_corrections.py ──► data/pass2_verified.psv
                         verify.py ──► verification/pass2_report.json
     verification/sample_review.csv   (stratified hand-checked sample; misses → new verifier rules)
                     build_site.py ──► site/index.html, site/data.json, site/llms.txt
```

| Script | What it does |
|---|---|
| `agent/research.py` | Crawls `docs_url`, `auth_url` and the homepage, follows up to 5 same-site auth/pricing/MCP/developer links, and caches the text as evidence. Uses the OS trust store (corporate TLS) and falls back to headless Edge/Chrome for JS-only docs and bot walls. `--llm` re-derives records from evidence with any OpenAI-compatible model (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`). `--merge` adds pages for corrected URLs. |
| `agent/mcp_check.py` | Searches GitHub for MCP servers per app. Set `GITHUB_TOKEN` to avoid the 10 req/min limit. Pass ids to limit the scope. |
| `agent/verify.py` | Scores every claim as `supported` / `unsupported` / `broken_link` / `no_evidence` and raises review flags: unclaimed auth, missed MCP, vendor MCP labelled community, trial labelled free, dead URLs. |
| `agent/inspect_evidence.py` | Reviewer tool: prints the snippets behind a signal (`python agent/inspect_evidence.py 95 mcp`) or page statuses (`--status`). |
| `agent/apply_corrections.py` | Applies `data/corrections.json`. Each `before` must match the current value, so stale fixes fail loudly. |
| `agent/build_site.py` | Computes every number and pattern on the page from the final data. |

## Run it
```bash
pip install -r requirements.txt
python agent/research.py                     # ~10 min for 100 apps (cached; --force to refetch)
python agent/mcp_check.py                    # optional, slow without GITHUB_TOKEN
python agent/verify.py data/pass1_llm.psv --label pass1
python agent/inspect_evidence.py 17 mcp      # review a flag
python agent/apply_corrections.py data/pass1_llm.psv data/pass2_verified.psv
python agent/research.py --input data/pass2_verified.psv --merge --ids 10 16 47 50 59 85 90 92
python agent/verify.py data/pass2_verified.psv --label pass2
REPO_URL=https://github.com/<you>/<repo> python agent/build_site.py
```
Open `site/index.html` directly, or deploy the `site/` folder to any static host (GitHub Pages, Netlify, Vercel).

## Where a human was needed
- **Judging flags:** keyword evidence is noisy. Plaid's "OAuth" means bank-side OAuth, and Magento's means OAuth 1.0a.
- **Dead or moved docs and rebrands:** fanbasis → Commas, Coda → Superhuman Docs, iPayX's real product, and the LiveAgent, PitchBook and DealCloud URLs.
- **Access tier:** "contact sales" on a marketing site doesn't mean the API is gated.
- **The hand-checked sample:** it caught misses the automated loop didn't, and those became new rules (loop 3).

## Honest limits
- The pass-1 draft came from an LLM (in this repo, Copilot produced `data/pass1_llm.psv` with the same schema the `--llm` mode uses). It is treated as a hypothesis, never as evidence.
- The keyword verifier proves that a word is on the page, not that the claim is right, which is why there is a review step and a sample.
- Sample grading was AI-assisted against cached live docs. The `human_confirmed` column in `verification/sample_review.csv` is for human sign-off.
- No paid accounts were used. Gated access is reported, with evidence, as the finding.

## Data schema (`data/*.psv`, pipe-delimited)
`id|name|category|hint|one_liner|auth|access|access_note|api|breadth|mcp|verdict|blocker|docs_url|auth_url`
- `auth`: `+`-joined values from `oauth2, api_key, bearer_token, basic, jwt, hmac, oauth1, none, unknown`
- `access`: `self_serve | trial | paid | approval | partner | unknown`
- `mcp`: `official | community | none`
- `verdict`: `ready | ready_with_review | blocked`
