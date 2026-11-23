# One-command pipeline (Windows PowerShell). Usage: .\run_all.ps1 [-Recrawl] [-RepoUrl https://github.com/you/repo]
param([switch]$Recrawl, [string]$RepoUrl = "")
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
pip install -r requirements.txt
if ($Recrawl) { python agent/research.py --force } else { python agent/research.py }
python agent/verify.py data/pass1_llm.psv --label pass1
python agent/apply_corrections.py data/pass1_llm.psv data/pass2_verified.psv
python agent/verify.py data/pass2_verified.psv --label pass2
if ($RepoUrl) { $env:REPO_URL = $RepoUrl }
python agent/build_site.py
Write-Host "Done. Open site/index.html"
