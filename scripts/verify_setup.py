"""Read-only health check for ShopAssist-AI. Run it on your own Mac, in the repo folder:

    python3 scripts/verify_setup.py

It reads the keys from .env (git-ignored) and checks:
  1. .env      – which keys are filled in (names only, values are NEVER printed)
  2. n8n       – the API key works, lists your credentials, runs n8n's own "test" on each,
                 and shows which workflow nodes still have no credential
  3. Gemini    – chat model and batch embeddings (the call n8n uses), embedding size
  4. Pinecone  – index "shopassist" exists, dimension 3072, metric cosine, vector count
  5. Supabase  – connects and counts rows in orders / tickets / n8n_chat_histories

It changes NOTHING: no credentials are created or edited, no workflow is run, published or activated.
Supabase check needs a small pure-Python driver once:  pip3 install pg8000
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import socket

# Some Wi-Fi networks advertise IPv6 but never answer on it; Python then waits for a timeout before
# trying IPv4. Try IPv4 addresses first so every check stays fast on such networks.
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: sorted(_getaddrinfo(*a, **k), key=lambda r: r[0] != socket.AF_INET)

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
PINECONE_DIM = 3072
CHAT_MODEL = "models/gemini-flash-latest"
EMBED_MODEL = "models/gemini-embedding-001"
results = []  # (section, ok, message)


def report(section, ok, message):
    results.append((section, ok, message))
    print(f"  [{'OK' if ok else 'FAIL'}] {message}")


def load_env():
    env = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #")[0].split("\t#")[0].strip().strip('"').strip("'")
        env[k.strip()] = v
    return env


ENV = load_env()
SECRETS = [v for k, v in ENV.items() if len(v) >= 6 and any(w in k for w in ("KEY", "PASSWORD", "TOKEN", "SECRET", "SID"))]


def clean(text):
    """Remove any secret value from text before printing it."""
    text = str(text)
    for s in SECRETS:
        text = text.replace(s, "***")
    return text[:300]


def is_set(key):
    v = ENV.get(key, "")
    return bool(v) and "REPLACE_ME" not in v and not v.startswith("your.") and "XXXX" not in v


def http(method, url, headers=None, body=None, timeout=30):
    """Return (status, parsed-json-or-text). Never raises for HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode(), e.code
    except Exception as e:  # network problems
        return 0, clean(e)
    try:
        return status, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return status, raw


def can_connect(host, port=443):
    """Quick TCP test per IP version (5 s each), to spot networks that block or hang."""
    import socket
    out = {}
    for fam, name in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")):
        try:
            addr = socket.getaddrinfo(host, port, fam, socket.SOCK_STREAM)[0][4]
        except OSError:
            out[name] = "no address"
            continue
        sock = socket.socket(fam, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect(addr)
            out[name] = "ok"
        except OSError as e:
            out[name] = f"FAILED ({e.__class__.__name__})"
        finally:
            sock.close()
    return out


def api_error(payload):
    if isinstance(payload, dict):
        err = payload.get("error", payload)
        if isinstance(err, dict):
            return clean(err.get("message", err))
        return clean(payload.get("message", err))
    return clean(payload)


# ------------------------------------------------------------------ 1. .env
print("\n1) .env file")
if not ENV_FILE.exists():
    report(".env", False, f"{ENV_FILE.name} not found. Run: cp .env.example .env  then fill it in.")
else:
    report(".env", True, ".env found (values are not shown)")
    for key in ["N8N_URL", "N8N_API_KEY", "GOOGLE_GEMINI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX",
                "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]:
        print(f"       {key:24} {'set' if is_set(key) else 'MISSING / placeholder'}")

# ------------------------------------------------------------------ 2. n8n
print("\n2) n8n")
n8n = ENV.get("N8N_URL", "http://localhost:5679").rstrip("/")
if "5688" in n8n:
    sys.exit("N8N_URL points at localhost:5688, which is NOT the ShopAssist n8n. Use http://localhost:5679.")
if not is_set("N8N_API_KEY"):
    report("n8n", False, "N8N_API_KEY missing in .env (n8n -> Settings -> n8n API -> Create an API key)")
else:
    H = {"X-N8N-API-KEY": ENV["N8N_API_KEY"], "Accept": "application/json"}
    st, wfs = http("GET", f"{n8n}/api/v1/workflows?limit=100", H)
    if st != 200:
        hint = (" -> the key is wrong, expired, or from another n8n. In localhost:5679 go to Settings -> n8n API, "
                "delete the old key, Create an API key (no expiry), copy ALL of it into N8N_API_KEY in .env")
        report("n8n", False, f"cannot use n8n API at {n8n}: HTTP {st} {api_error(wfs)}" + (hint if st == 401 else ""))
    else:
        mine = [w for w in wfs.get("data", []) if w["name"][:3] in ("01 ", "02 ", "03 ", "04 ", "05 ")]
        report("n8n", True, f"API key works; {len(mine)} ShopAssist workflows found")
        for w in sorted(mine, key=lambda w: w["name"]):
            missing = [n["name"] for n in w["nodes"]
                       if not n.get("credentials") and n["type"].split(".")[-1] in
                       ("vectorStorePinecone", "embeddingsGoogleGemini", "lmChatGoogleGemini", "postgres",
                        "postgresTool", "memoryPostgresChat", "slack", "twilio", "emailSend")]
            state = "ACTIVE/published" if w.get("active") else "not active"
            print(f"       {w['name'][:45]:45} {state:17} "
                  f"{'no missing credentials' if not missing else 'needs credential: ' + ', '.join(missing)}")
        st, creds = http("GET", f"{n8n}/api/v1/credentials?limit=100", H)
        if st != 200:
            report("n8n", False, f"could not list credentials (HTTP {st}); check them in the n8n UI. "
                                 f"If the API key has limited scopes, add credential:list and credential:read.")
        else:
            for c in creds.get("data", []):
                st2, t = http("POST", f"{n8n}/api/v1/credentials/{c['id']}/test", H, {}, timeout=60)
                if st2 == 200 and isinstance(t, dict):
                    report("n8n", t.get("status") == "OK",
                           f"credential '{c['name']}' ({c['type']}): {clean(t.get('message', t.get('status')))}")
                else:
                    print(f"       credential '{c['name']}' ({c['type']}): exists (n8n cannot self-test it here)")
            names = [c["type"] for c in creds.get("data", [])]
            if names.count("googlePalmApi") > 1:
                report("n8n", False, "more than one Gemini credential exists - keep only the working one")

# ------------------------------------------------------------------ 3. Gemini
print("\n3) Google Gemini")
if not is_set("GOOGLE_GEMINI_API_KEY"):
    report("Gemini", False, "GOOGLE_GEMINI_API_KEY missing in .env")
else:
    gk = ENV["GOOGLE_GEMINI_API_KEY"]
    if not gk.startswith("AIza"):
        print("       note: key starts with something other than 'AIza' (AI Studio keys starting 'AQ.' are fine). "
              "Make sure it comes from a PERSONAL Gmail, not the School account. Testing it now (up to 1 min)...")
    G = "https://generativelanguage.googleapis.com/v1beta"
    net = can_connect("generativelanguage.googleapis.com")
    print(f"       network to Google: IPv4 {net['IPv4']}, IPv6 {net['IPv6']}")
    if net["IPv4"] == "ok" and net["IPv6"] != "ok":
        print("       IPv6 is broken on this network (IPv4 works). This script now uses IPv4. If n8n's Gemini calls")
        print("       are slow or time out: System Settings -> Wi-Fi -> Details -> TCP/IP -> Configure IPv6: Link-local only")
    if net["IPv4"] != "ok" and net["IPv6"] != "ok":
        report("Gemini", False, "this Mac cannot reach generativelanguage.googleapis.com - switch Wi-Fi / phone "
                                "hotspot, turn off VPN or firewall, then try again")
    st, r = http("POST", f"{G}/{CHAT_MODEL}:generateContent?key={gk}", body={
        "contents": [{"parts": [{"text": "Reply with the single word OK"}]}]}, timeout=20)
    if st == 200 and r.get("candidates"):
        report("Gemini", True, f"chat {CHAT_MODEL} answers: "
                               f"{clean(r['candidates'][0]['content']['parts'][0].get('text', '')).strip()[:20]}")
    else:
        report("Gemini", False, f"chat {CHAT_MODEL}: HTTP {st} {api_error(r)}")
    st, r = http("POST", f"{G}/{EMBED_MODEL}:batchEmbedContents?key={gk}", body={"requests": [
        {"model": EMBED_MODEL, "content": {"parts": [{"text": "return policy"}]}}]}, timeout=20)
    if st == 200 and r.get("embeddings"):
        dims = len(r["embeddings"][0].get("values", []))
        report("Gemini", dims == PINECONE_DIM, f"batch embeddings {EMBED_MODEL}: {dims} dimensions "
                                                f"(Pinecone index must be {PINECONE_DIM})")
    else:
        report("Gemini", False, f"batch embeddings {EMBED_MODEL}: HTTP {st} {api_error(r)} "
                                f"<- this is what makes Pinecone say 'Vector dimension 0'")

# ------------------------------------------------------------------ 4. Pinecone
print("\n4) Pinecone")
if not is_set("PINECONE_API_KEY"):
    report("Pinecone", False, "PINECONE_API_KEY missing in .env")
else:
    index = ENV.get("PINECONE_INDEX") or "shopassist"
    PH = {"Api-Key": ENV["PINECONE_API_KEY"], "X-Pinecone-API-Version": "2025-01"}
    st, r = http("GET", f"https://api.pinecone.io/indexes/{index}", PH)
    if st != 200:
        report("Pinecone", False, f"index '{index}': HTTP {st} {api_error(r)}")
    else:
        dim, metric = r.get("dimension"), r.get("metric")
        report("Pinecone", dim == PINECONE_DIM, f"index '{index}' dimension {dim} (need {PINECONE_DIM})")
        report("Pinecone", metric == "cosine", f"metric {metric} (need cosine)")
        report("Pinecone", (r.get("status") or {}).get("ready", False), f"status {(r.get('status') or {}).get('state')}")
        st, s = http("POST", f"https://{r['host']}/describe_index_stats", PH, {})
        if st == 200:
            print(f"       vectors stored: {s.get('totalVectorCount', s.get('total_vector_count', '?'))} "
                  f"(0 = run workflows 01 and 02; ~6-10 after 01, ~10-14 after 02)")

# ------------------------------------------------------------------ 5. Supabase
print("\n5) Supabase Postgres")
need = ["POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD"]
if not all(is_set(k) for k in need):
    report("Supabase", False, "POSTGRES_HOST / POSTGRES_USER / POSTGRES_PASSWORD missing in .env")
else:
    try:
        import pg8000.native
    except ImportError:
        report("Supabase", False, "driver missing - run: pip3 install pg8000   then run this script again")
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # encrypted; Supabase pooler cert not in system store
        try:
            con = pg8000.native.Connection(
                user=ENV["POSTGRES_USER"], password=ENV["POSTGRES_PASSWORD"], host=ENV["POSTGRES_HOST"],
                port=int(ENV.get("POSTGRES_PORT") or 5432), database=ENV.get("POSTGRES_DB") or "postgres",
                ssl_context=ctx, timeout=20)
            report("Supabase", True, f"connected to {ENV['POSTGRES_HOST']}")
            for table, expect in [("orders", "10 after seed.sql"), ("tickets", "0+"), ("n8n_chat_histories", "0+")]:
                try:
                    n = con.run(f"SELECT count(*) FROM {table}")[0][0]
                    report("Supabase", True, f"table {table}: {n} rows (expected {expect})")
                except Exception as e:
                    report("Supabase", False, f"table {table}: {clean(e)} -> run database/schema.sql (and seed.sql)")
            con.close()
        except Exception as e:
            report("Supabase", False, f"cannot connect: {clean(e)} "
                                      f"(use the Session pooler host/user from Supabase -> Connect)")

# ------------------------------------------------------------------ summary
fails = [r for r in results if not r[1]]
print("\n" + ("All checks passed. Safe to run workflow 01, then 02." if not fails else
              f"{len(fails)} check(s) failed - fix these before running or publishing any workflow:"))
for section, _, msg in fails:
    print(f"  - {section}: {msg}")
sys.exit(1 if fails else 0)
