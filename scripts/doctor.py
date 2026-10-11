"""Find out WHY ShopAssist is not working. Read-only, never prints secrets. Run in the repo folder:

    python3 scripts/doctor.py

It checks, in order:
  1. code      – is this folder on the latest GitHub version?
  2. .env      – saved? which keys are filled in? (names only)
  3. Ollama    – installed and running? models downloaded? embeddings 768?
  4. n8n       – reachable? are the workflows INSIDE n8n the new Ollama version or still the old Gemini one?
                 can n8n itself reach Ollama?
  5. errors    – the last failed n8n runs: workflow, failing node and the exact error message
Then it prints a short "what to do" list. Paste the whole output into the chat if you need help.
"""
import datetime
import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_gai = socket.getaddrinfo  # prefer IPv4 (some networks hang on IPv6)
socket.getaddrinfo = lambda *a, **k: sorted(_gai(*a, **k), key=lambda r: r[0] != socket.AF_INET)
todo = []


def env_file():
    env, p = {}, ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.split(" #")[0].strip().strip('"').strip("'")
    return env


ENV = env_file()
SECRETS = [v for k, v in ENV.items() if len(v) >= 6 and any(w in k for w in ("KEY", "PASSWORD", "TOKEN", "SECRET", "SID"))]


def clean(t):
    t = str(t)
    for s in SECRETS:
        t = t.replace(s, "***")
    return t[:400]


def http(method, url, headers=None, body=None, timeout=20):
    req = urllib.request.Request(url, method=method, headers={"Content-Type": "application/json", **(headers or {})},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, st = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read().decode(), e.code
    except Exception as e:
        return 0, clean(e)
    try:
        return st, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return st, raw[:300]


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return ""


# ------------------------------------------------------------------ 1. code version
print("\n1) Code version")
git("fetch", "-q", "origin")
REF = "origin/claude/quirky-tesla-gzzg4y"  # latest code (main + newest fixes)
branch = git("rev-parse", "--abbrev-ref", "HEAD")
local, remote = git("rev-parse", "--short", "HEAD"), git("rev-parse", "--short", REF)
print(f"   branch {branch}, this folder at {local}, latest on GitHub {remote or '?'}")
if remote and local != remote:
    todo.append("Get the latest code:  git fetch origin && git reset --hard origin/claude/quirky-tesla-gzzg4y")
gen = (ROOT / "workflows" / "03_support_agent_chat.json").read_text(encoding="utf-8")
print("   workflow files in this folder use:", "Ollama" if "lmChatOllama" in gen else "GEMINI (old)")

# ------------------------------------------------------------------ 2. .env
print("\n2) .env")
p = ROOT / ".env"
if not p.exists():
    print("   .env NOT FOUND in", ROOT)
    todo.append("Create .env:  cp .env.example .env  then fill it in and SAVE (Cmd+S)")
else:
    age = datetime.datetime.now() - datetime.datetime.fromtimestamp(p.stat().st_mtime)
    print(f"   found, last saved {int(age.total_seconds() // 60)} min ago")
    for k in ["N8N_URL", "N8N_API_KEY", "OLLAMA_URL", "PINECONE_API_KEY", "PINECONE_INDEX", "POSTGRES_HOST",
              "POSTGRES_USER", "POSTGRES_PASSWORD"]:
        v = ENV.get(k, "")
        ok = bool(v) and "REPLACE_ME" not in v
        extra = ""
        if k == "PINECONE_API_KEY" and " " in v:
            ok, extra = False, " (contains a space - extra text after the key?)"
        print(f"   {k:20} {'set' if ok else 'MISSING / placeholder'}{extra}")
    for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if "=" in line and not line.strip().startswith("#"):
            val = line.split("=", 1)[1].split(" #")[0].strip()
            key = line.split("=", 1)[0].strip()
            if " " in val and not (val.startswith('"') or val.startswith("'")) and "PASSWORD" not in key:
                print(f"   line {n} ({line.split('=')[0].strip()}): value contains a space - remove extra words after it")
    if "GOOGLE_GEMINI_API_KEY" in ENV:
        print("   (GOOGLE_GEMINI_API_KEY is no longer used - you can delete that line)")

# ------------------------------------------------------------------ 3. Ollama
print("\n3) Ollama on this Mac")
oll = (ENV.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
installed = subprocess.run(["which", "ollama"], capture_output=True, text=True).stdout.strip()
print("   ollama command:", installed or "NOT INSTALLED")
st, tags = http("GET", f"{oll}/api/tags", timeout=5)
if st != 200:
    print(f"   Ollama server at {oll}: NOT RUNNING")
    todo.append("Install Ollama from ollama.com and OPEN the Ollama app (llama icon in the menu bar)" if not installed
                else "Start Ollama: open the Ollama app (or run `ollama serve` in a separate Terminal window)")
else:
    have = {m.get("name", "").split(":latest")[0] for m in tags.get("models", [])}
    print("   running; models:", ", ".join(sorted(have)) or "none")
    for m in ("qwen2.5:3b", "nomic-embed-text"):
        if m not in have:
            todo.append(f"Download the model:  ollama pull {m}")
    if "nomic-embed-text" in have:
        st, r = http("POST", f"{oll}/api/embed", body={"model": "nomic-embed-text", "input": ["test"]}, timeout=120)
        print("   embeddings size:", len((r.get("embeddings") or [[]])[0]) if st == 200 else f"ERROR {clean(r)}")

# ------------------------------------------------------------------ 4. n8n
print("\n4) n8n")
n8n = (ENV.get("N8N_URL") or "http://localhost:5679").rstrip("/")
H = {"X-N8N-API-KEY": ENV.get("N8N_API_KEY", ""), "Accept": "application/json"}
st, wfs = http("GET", f"{n8n}/api/v1/workflows?limit=100", H)
if st == 0:
    print(f"   cannot reach n8n at {n8n}: {wfs}")
    todo.append("Start n8n (it must be open at http://localhost:5679)")
elif st == 401:
    print("   n8n says the API key is wrong (401)")
    todo.append("New n8n API key: localhost:5679 -> Settings -> n8n API -> Create (no expiry) -> paste into .env, SAVE")
elif st == 404 and "Cannot GET" in str(wfs):
    print("   n8n is still starting (its API is not ready yet)")
    todo.append("Wait 30-60 seconds for n8n to finish starting, then run python3 scripts/doctor.py again. "
                "If this stays: the n8n public API is disabled (N8N_PUBLIC_API_DISABLED) in your compose file.")
elif st != 200:
    print(f"   n8n API error HTTP {st}: {clean(wfs)[:200]}")
else:
    names = {}
    for w in wfs.get("data", []):
        if w["name"][:3] not in ("01 ", "02 ", "03 ", "04 ", "05 ", "06 "):
            continue
        names[w["id"]] = w["name"]
        types = {n["type"].split(".")[-1] for n in w["nodes"]}
        ai = "OLLAMA" if types & {"lmChatOllama", "embeddingsOllama"} else (
            "GEMINI (old!)" if types & {"lmChatGoogleGemini", "embeddingsGoogleGemini"} else "-")
        if ai.startswith("GEMINI"):
            todo.append("n8n still has the OLD Gemini workflows. Run:  python3 scripts/import_to_n8n.py")
        missing = [n["name"] for n in w["nodes"] if not n.get("credentials") and n["type"].split(".")[-1] in
                   ("vectorStorePinecone", "embeddingsOllama", "lmChatOllama", "postgres", "postgresTool",
                    "memoryPostgresChat", "slack", "twilio", "emailSend")]
        if not w.get("active") and w["name"][:2] in ("03", "04", "05", "06"):
            todo.append(f"Publish workflow {w['name'][:2]} in n8n (order: 04, 06, then 03, 05)")
        print(f"   {w['name'][:44]:44} AI={ai:13} {'published' if w.get('active') else 'not published':13}"
              f"{' missing credential: ' + ', '.join(missing) if missing else ''}")
    st, creds = http("GET", f"{n8n}/api/v1/credentials?limit=100", H)
    for c in (creds.get("data", []) if st == 200 else []):
        if c["type"] == "ollamaApi":
            st2, t = http("POST", f"{n8n}/api/v1/credentials/{c['id']}/test", H, {}, timeout=30)
            msg = t.get("message", t.get("status")) if isinstance(t, dict) else t
            print(f"   n8n -> Ollama ('{c['name']}'): {clean(msg)}")
            if isinstance(t, dict) and t.get("status") != "OK":
                todo.append("n8n cannot reach Ollama. If n8n runs in Docker: n8n -> Credentials -> Ollama account -> "
                            "Base URL = http://host.docker.internal:11434 -> Save. Otherwise make sure the Ollama app is open.")

    # ---------------------------------------------------------------- 4b. webhook / chat address
    # The editor chat and the public chat send messages to n8n's WEBHOOK address. If n8n runs on a
    # different port than it thinks (e.g. Docker -p 5679:5678 without WEBHOOK_URL), chat messages go
    # to the wrong port: "Error: Failed to receive response" and nothing in the Logs panel.
    port = n8n.rsplit(":", 1)[-1].strip("/") if n8n.count(":") >= 2 else "80"
    found = False
    dps = subprocess.run(["docker", "ps", "--format", "{{.Names}}|{{.Image}}|{{.Ports}}"],
                         capture_output=True, text=True).stdout if subprocess.run(
                             ["which", "docker"], capture_output=True).returncode == 0 else ""
    for row in dps.splitlines():
        name, image, ports = (row.split("|") + ["", ""])[:3]
        if "n8n" not in image.lower() and "n8n" not in name.lower():
            continue
        envs = subprocess.run(["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", name],
                              capture_output=True, text=True).stdout.splitlines()
        hook = next((e.split("=", 1)[1] for e in envs if e.startswith("WEBHOOK_URL=")), "")
        if f":{port}->" not in ports:
            continue
        found = True
        print(f"   n8n runs in Docker container '{name}' ({ports.strip()}); WEBHOOK_URL={hook or '(not set)'}")
        if f":{port}" not in hook:
            todo.append(f"Chat messages go to the wrong port. Fix (keeps all data, makes a backup):  "
                        f"bash scripts/fix_webhook_url.sh {name} {port}")
    if not found:
        ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
        for line in ps.splitlines():
            pid, _, cmd = line.strip().partition(" ")
            if "n8n" in cmd and ("start" in cmd or cmd.rstrip().endswith("n8n")) and "doctor.py" not in cmd:
                env = subprocess.run(["ps", "eww", "-p", pid], capture_output=True, text=True).stdout
                want = {k: (env.split(f" {k}=", 1)[1].split(" ", 1)[0] if f" {k}=" in env else "")
                        for k in ("N8N_PORT", "WEBHOOK_URL")}
                print(f"   n8n process {pid}: N8N_PORT={want['N8N_PORT'] or '(not set)'}, "
                      f"WEBHOOK_URL={want['WEBHOOK_URL'] or '(not set)'}")
                if want["WEBHOOK_URL"] and f":{port}" not in want["WEBHOOK_URL"]:
                    todo.append(f"WEBHOOK_URL points to another port. Start n8n with WEBHOOK_URL=http://localhost:{port}/")
                elif not want["WEBHOOK_URL"] and want["N8N_PORT"] and want["N8N_PORT"] != port:
                    todo.append(f"Start n8n with N8N_PORT={port} (or WEBHOOK_URL=http://localhost:{port}/)")
                break
    print("   check by hand: double-click 'Public Chat (UrbanThread)' in workflow 03 - its Chat URL must start "
          f"with http://localhost:{port}/")

    # ---------------------------------------------------------------- 5. recent errors
    print("\n5) Last failed n8n runs (newest first)")
    st, ex = http("GET", f"{n8n}/api/v1/executions?status=error&limit=5&includeData=true", H, timeout=30)
    if st != 200:
        print(f"   cannot read executions (HTTP {st})")
    elif not ex.get("data"):
        print("   none")
    for e in ex.get("data", []) if st == 200 else []:
        rd = ((e.get("data") or {}).get("resultData") or {})
        err = rd.get("error") or {}
        node = rd.get("lastNodeExecuted") or (err.get("node") or {}).get("name", "?")
        print(f"   - {str(e.get('startedAt', ''))[:16]}  {names.get(e.get('workflowId'), e.get('workflowId'))}")
        print(f"     node: {node}")
        print(f"     error: {clean(err.get('message', '?'))}")
        if err.get("description"):
            print(f"     detail: {clean(err['description'])[:250]}")
        m = str(err.get("message", "")) + str(err.get("description", ""))
        if "dimension" in m.lower():
            todo.append("Pinecone index has the wrong size:  python3 scripts/setup_pinecone.py  (makes it 768)")
        if "ECONNREFUSED" in m or "fetch failed" in m:
            todo.append("n8n could not connect to a service (see error above) - usually Ollama not running / Docker URL")
        if "not found" in m.lower() and "model" in m.lower():
            todo.append("Model missing in Ollama:  ollama pull qwen2.5:3b  and  ollama pull nomic-embed-text")

print("\nWHAT TO DO" + (":" if todo else ": nothing obvious found - run workflow 01 in n8n and paste the error."))
seen = set()
for i, t in enumerate([t for t in todo if not (t in seen or seen.add(t))], 1):
    print(f"   {i}. {t}")
