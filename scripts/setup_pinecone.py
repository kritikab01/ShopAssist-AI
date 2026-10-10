"""Create the Pinecone index "shopassist" with the size Ollama's embeddings need (768, cosine).

Run on your own computer, in the repo folder (reads PINECONE_API_KEY from .env):

    python3 scripts/setup_pinecone.py

- index missing            -> it is created (free Starter plan: serverless, AWS us-east-1)
- index exists, size 768   -> nothing to do
- index exists, other size -> asks "type DELETE" before deleting and recreating it
  (an index's dimension can never be changed; the old vectors are useless anyway)
Never prints your API key.
"""
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DIMENSION, METRIC = 768, "cosine"
ROOT = Path(__file__).resolve().parent.parent

# Prefer IPv4 (some Wi-Fi networks hang on IPv6).
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: sorted(_gai(*a, **k), key=lambda r: r[0] != socket.AF_INET)

env = {}
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.split(" #")[0].strip().strip('"').strip("'")
key = env.get("PINECONE_API_KEY", "")
name = env.get("PINECONE_INDEX") or "shopassist"
if not key or "REPLACE_ME" in key:
    sys.exit("PINECONE_API_KEY missing in .env (app.pinecone.io -> API Keys).")
H = {"Api-Key": key, "X-Pinecone-API-Version": "2025-01", "Content-Type": "application/json"}


def call(method, path, body=None):
    req = urllib.request.Request(f"https://api.pinecone.io{path}", method=method, headers=H,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"message": raw[:200]}
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach Pinecone ({e.reason}). Check your internet connection / VPN and try again.")


def message(r):
    err = r.get("error", r) if isinstance(r, dict) else r
    return (err.get("message") if isinstance(err, dict) else str(err)) or str(r)


st, idx = call("GET", f"/indexes/{name}")
if st == 401:
    sys.exit("Pinecone says the API key is invalid. Copy it again from app.pinecone.io -> API Keys into .env.")
if st == 200:
    if idx.get("dimension") == DIMENSION and idx.get("metric") == METRIC:
        print(f"OK: index '{name}' already has dimension {DIMENSION} and metric {METRIC}. Nothing to do.")
        sys.exit(0)
    print(f"Index '{name}' has dimension {idx.get('dimension')} / metric {idx.get('metric')}, "
          f"but Ollama's nomic-embed-text needs {DIMENSION} / {METRIC}.")
    if input("Type DELETE to delete it and create it again with the right size: ").strip() != "DELETE":
        sys.exit("Nothing changed.")
    st, r = call("DELETE", f"/indexes/{name}")
    if st not in (200, 202, 204):
        sys.exit(f"Could not delete the index: HTTP {st} {message(r)} "
                 f"(if 'deletion protection' is on, turn it off in the Pinecone console first)")
    for _ in range(30):  # wait until it is gone
        time.sleep(2)
        if call("GET", f"/indexes/{name}")[0] == 404:
            break
    print(f"Deleted '{name}'.")
elif st != 404:
    sys.exit(f"Pinecone error: HTTP {st} {message(idx)}")

st, r = call("POST", "/indexes", {"name": name, "dimension": DIMENSION, "metric": METRIC,
                                  "spec": {"serverless": {"cloud": "aws", "region": "us-east-1"}},
                                  "deletion_protection": "disabled"})
if st not in (200, 201, 202):
    sys.exit(f"Could not create the index: HTTP {st} {message(r)}")
print(f"Creating '{name}' ({DIMENSION} dims, {METRIC}) ...")
for _ in range(60):
    st, idx = call("GET", f"/indexes/{name}")
    if st == 200 and (idx.get("status") or {}).get("ready"):
        print(f"OK: index '{name}' is ready. Now run workflow 01, then 02, in n8n (once each).")
        sys.exit(0)
    time.sleep(2)
print("The index was created but is not ready yet - wait a minute, then run workflow 01.")
