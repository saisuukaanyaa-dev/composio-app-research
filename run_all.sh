#!/usr/bin/env bash
# One-command pipeline (macOS/Linux). Usage: ./run_all.sh [--recrawl]
set -e
export PYTHONIOENCODING=utf-8
pip install -r requirements.txt
if [ "$1" = "--recrawl" ]; then python agent/research.py --force; else python agent/research.py; fi
python agent/verify.py data/pass1_llm.psv --label pass1
python agent/apply_corrections.py data/pass1_llm.psv data/pass2_verified.psv
python agent/verify.py data/pass2_verified.psv --label pass2
python agent/build_site.py
echo "Done. Open site/index.html"