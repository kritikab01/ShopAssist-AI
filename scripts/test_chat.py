"""Test ShopAssist from the Terminal - no browser chat window needed. Run in the repo folder:

    python3 scripts/test_chat.py                       # all tests with default questions
    python3 scripts/test_chat.py "What is your return policy?"   # ask workflow 03 your own question

Steps (each prints what happened and how long it took):
  1. Ollama alone      – the model answers a question directly (is the AI itself working? how fast?)
  2. Workflow 03 chat  – sends your question to the ShopAssist chat (needs 03 and 04 PUBLISHED)
  3. Workflow 05       – sends an order update to the webhook (needs 05 PUBLISHED); safe test on UT1007
If a workflow fails, it prints the failing node and n8n's exact error.
Reads N8N_URL / N8N_API_KEY / OLLAMA_URL from .env. Never prints secrets.
"""
import json
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_gai = socket.getaddrinfo  # prefer IPv4
socket.getaddrinfo = lambda *a, **k: sorted(_gai(*a, **k), key=lambda r: r[0] != socket.AF_INET)

ENV = {}
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.split(" #")[0].strip().strip('"').strip("'")
N8N = (ENV.get("N8N_URL") or "http://localhost:5679").rstrip("/")
OLL = (ENV.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
H = {"X-N8N-API-KEY": ENV.get("N8N_API_KEY", ""), "Accept": "application/json"}
QUESTION = " ".join(sys.argv[1:]) or "Where is my order UT1002?"


def http(method, url, body=None, headers=None, timeout=300):
    req = urllib.request.Request(url, method=method, headers={"Content-Type": "application/json", **(headers or {})},
                                 data=json.dumps(body).encode() if body is not None else None)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, st = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read().decode(), e.code
    except Exception as e:
        return 0, str(e), time.time() - t
    try:
        return st, json.loads(raw) if raw else {}, time.time() - t
    except json.JSONDecodeError:
        return st, raw[:500], time.time() - t


def last_error(workflow_id):
    st, ex, _ = http("GET", f"{N8N}/api/v1/executions?workflowId={workflow_id}&limit=1&includeData=true", headers=H)
    if st != 200 or not ex.get("data"):
        return
    e = ex["data"][0]
    rd = (e.get("data") or {}).get("resultData") or {}
    err = rd.get("error")
    print(f"     last run: {e.get('status')}" + (f" - node '{rd.get('lastNodeExecuted')}': {err.get('message')}"
                                                  f"{' | ' + str(err.get('description'))[:300] if err.get('description') else ''}"
                                                  if err else ""))


# ------------------------------------------------------------------ 1. Ollama directly
print(f"\n1) Ollama alone (qwen2.5:3b at {OLL}) - asking: 'In one sentence, what is a return policy?'")
print("   (first answer can take up to a minute while the model loads into memory)")
st, r, sec = http("POST", f"{OLL}/api/chat", {"model": "qwen2.5:3b", "stream": False, "think": False,
                                              "options": {"num_ctx": 8192},
                                              "messages": [{"role": "user", "content": "In one sentence, what is a return policy?"}]})
if st == 200 and isinstance(r, dict) and r.get("message"):
    print(f"   OK in {sec:.0f} s: {r['message'].get('content', '').strip()[:200]}")
else:
    print(f"   FAILED ({sec:.0f} s): HTTP {st} {str(r)[:300]}")
    print("   -> open the Ollama app, run `ollama pull qwen2.5:3b`, then try again.")

# ------------------------------------------------------------------ find the workflows in n8n
st, wfs, _ = http("GET", f"{N8N}/api/v1/workflows?limit=100", headers=H, timeout=20)
if st != 200:
    sys.exit(f"\nCannot use the n8n API at {N8N} (HTTP {st}). Check N8N_URL / N8N_API_KEY in .env (doctor.py helps).")
by_prefix = {}
for w in wfs.get("data", []):
    old = by_prefix.get(w["name"][:2])  # "03", "04", "05"; prefer the published copy if there are two
    if not old or (w.get("active") and not old.get("active")):
        by_prefix[w["name"][:2]] = w


def published(prefix):
    w = by_prefix.get(prefix)
    return w and w.get("active")


# ------------------------------------------------------------------ 2. workflow 03 chat
print(f"\n2) Workflow 03 chat - asking: {QUESTION!r}")
w3 = by_prefix.get("03")
if not w3:
    print("   workflow 03 not found in n8n -> run: python3 scripts/import_to_n8n.py")
else:
    hook = next((n.get("webhookId") for n in w3["nodes"] if n["type"].endswith("chatTrigger")), None)
    if not published("03") or not published("04"):
        print(f"   NOT TESTED: publish workflow 04 and then 03 in n8n first "
              f"(03 published: {bool(published('03'))}, 04 published: {bool(published('04'))})")
    else:
        print("   waiting for the agent (the local model can take 20-90 s)...")
        st, r, sec = http("POST", f"{N8N}/webhook/{hook}/chat",
                          {"action": "sendMessage", "sessionId": f"terminal-{uuid.uuid4().hex[:8]}", "chatInput": QUESTION})
        if st == 200 and isinstance(r, dict) and "output" in r:
            print(f"   OK in {sec:.0f} s. ShopAssist says:\n   " + str(r["output"]).strip().replace("\n", "\n   "))
        else:
            print(f"   FAILED ({sec:.0f} s): HTTP {st} {str(r)[:300]}")
            last_error(w3["id"])

# ------------------------------------------------------------------ 3. workflow 05 webhook
print("\n3) Workflow 05 webhook - order UT1007 -> status 'shipped' (no SMS for this status)")
if not published("05"):
    print("   NOT TESTED: publish workflow 05 in n8n first")
else:
    st, r, sec = http("POST", f"{N8N}/webhook/order-update", {"order_id": "UT1007", "status": "shipped"}, timeout=60)
    if st == 200 and isinstance(r, dict) and r.get("ok"):
        print(f"   OK in {sec:.1f} s: {r}")
    else:
        print(f"   FAILED ({sec:.1f} s): HTTP {st} {str(r)[:300]}")
        last_error(by_prefix["05"]["id"])
print()
