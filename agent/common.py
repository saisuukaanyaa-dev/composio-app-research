"""Shared schema, IO and evidence-signal patterns."""
import csv, re
from pathlib import Path

FIELDS = ["id", "name", "category", "hint", "one_liner", "auth", "access", "access_note", "api", "breadth",
          "mcp", "verdict", "blocker", "docs_url", "auth_url"]


def load_records(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def save_records(rows, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, delimiter="|", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# Phrases that, when present on a fetched docs page, support a claim.
SIGNALS = {
    "auth:oauth2": r"oauth ?2|oauth 2\.0|authorization[_ ]code|client[_ ]credentials|oauth flow|oauth app|\boauth\b",
    "auth:oauth1": r"oauth ?1|oauth 1\.0|consumer[_ ]key|consumer[_ ]secret",
    "auth:api_key": r"api[ _-]?keys?\b|x-api-key|api[ _-]token|apikey|access[ _-]key|secret key|security[ _-]key",
    "auth:basic": r"basic auth|http basic|authorization: basic|basic authentication|username and password|base64",
    "auth:bearer_token": r"bearer|access[ _-]token|personal access token|auth[ _-]?token|api[ _-]token|bot token|integration token",
    "auth:jwt": r"\bjwt\b|json web token|key[- ]pair",
    "auth:hmac": r"hmac|signature|sha256",
    "api:REST": r"\brest\b|restful|\b(get|post|put|patch|delete) /|https://api\.|endpoint",
    "api:GraphQL": r"graphql",
    "api:SOAP": r"\bsoap\b",
    "api:gRPC": r"\bgrpc\b",
    "api:CLI": r"command[- ]line|\bcli\b|npm install|pip install|npx ",
    "api:MCP": r"model context protocol|\bmcp\b",
    "mcp": r"model context protocol|\bmcp\b",
    "access:self_serve": r"free plan|free tier|free forever|sign up free|get started for free|free account|developer account|sandbox|test mode|open[- ]source|free developer|no credit card|hobby",
    "access:trial": r"free trial|trial|\d+[- ]day|credits",
    "access:paid": r"paid plan|upgrade|pricing|subscription|plan or higher|available on .* plans?|enterprise plan|add-on",
    "access:approval": r"app review|review process|apply for|application|approval|approved|verification|access level|standard access|advanced access",
    "access:partner": r"contact sales|talk to sales|book a demo|request a demo|partner program|partnership|enterprise customers|request access|contact us",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in SIGNALS.items()}


def signal_hits(text):
    return {k: len(p.findall(text)) for k, p in _COMPILED.items() if p.search(text)}
