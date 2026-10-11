"""Create or update all 5 ShopAssist workflows in your n8n with one command (n8n public API).

Run this ON YOUR OWN COMPUTER (where n8n runs), from the repo folder:

    git pull                        # get the latest workflow files first
    python3 scripts/import_to_n8n.py     # reads N8N_URL / N8N_API_KEY / OLLAMA_URL from .env

What it does:
  1. workflow 04 (escalation) and 06 (inventory agent) first, then 03, 01, 02, 05;
  2. if a workflow with the same name already exists it is UPDATED in place (same ID, same URL)
     and every node keeps the credential you already selected (matched by node name);
     otherwise it is created;
  3. creates the Ollama credential (and placeholder Slack/Twilio/SMTP credentials so 04/05 can be
     published) if they do not exist; nodes with no credential get your credential of the right
     type if you have exactly one of it;
  4. points the tools of workflow 03 at the real IDs: escalate_to_human -> 04, inventory_expert -> 06.
Nothing is published/activated. Nodes that never had a credential show a warning: open them and
select your credential. Only the Python 3 standard library is used - no pip install needed.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

WF_DIR = Path(__file__).resolve().parent.parent / "workflows"
ORDER = ["04_escalation_subworkflow.json", "06_inventory_agent.json", "03_support_agent_chat.json",
         "01_ingest_faq_pdf.json", "02_scrape_and_summarize.json", "05_order_update_webhook.json"]
# Agent tools in 03 that call another workflow: tool node name -> workflow file it must point to.
LINKS = {"escalate_to_human": "04_escalation_subworkflow.json", "Create Ticket (workflow 04)": "04_escalation_subworkflow.json", "inventory_expert": "06_inventory_agent.json"}

# Read .env from the repo folder (no `source .env` needed; values with spaces are fine).
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.split(" #")[0].strip().strip('"').strip("'"))

base = os.environ.get("N8N_URL", "http://localhost:5679").rstrip("/")
key = os.environ.get("N8N_API_KEY")
if not key:
    sys.exit("Set N8N_API_KEY first (n8n -> Settings -> n8n API -> Create an API key).")


class ApiError(Exception):
    pass


def api(method, path, body=None):
    req = urllib.request.Request(
        f"{base}/api/v1{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-N8N-API-KEY": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise ApiError(f"HTTP {e.code} {e.read().decode()[:400]}")
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach n8n at {base}: {e.reason}. Is n8n running? Is N8N_URL right?")


# Existing workflows by name (to update instead of creating duplicates).
existing, cursor = {}, None
while True:
    try:
        page = api("GET", "/workflows?limit=100" + (f"&cursor={cursor}" if cursor else ""))
    except ApiError as e:
        sys.exit(f"n8n refused the API key or request: {e}")
    for w in page.get("data", []):
        existing.setdefault(w["name"], w)
    cursor = page.get("nextCursor")
    if not cursor:
        break

# Credential type each node needs. If you have exactly ONE credential of that type in n8n,
# nodes without a credential get it automatically (no clicking through every node).
NEEDS = {"vectorStorePinecone": "pineconeApi", "embeddingsOllama": "ollamaApi", "lmChatOllama": "ollamaApi",
         "postgres": "postgres", "postgresTool": "postgres",
         "memoryPostgresChat": "postgres", "slack": "slackApi", "twilio": "twilioApi", "emailSend": "smtp"}
by_type = {}
try:
    for c in api("GET", "/credentials?limit=100").get("data", []):
        by_type.setdefault(c["type"], []).append({"id": c["id"], "name": c["name"]})
except ApiError:
    print("note: cannot list credentials with this API key; nodes keep only credentials chosen before.")


def create_credential(name, ctype, data):
    c = api("POST", "/credentials", {"name": name, "type": ctype, "data": data})
    by_type.setdefault(ctype, []).append({"id": c["id"], "name": c["name"]})
    return c["id"]


def credential_ok(cid):
    try:
        return api("POST", f"/credentials/{cid}/test", {}).get("status") == "OK"
    except ApiError:
        return None  # this n8n version cannot test credentials through the API


# Ollama credential: created automatically (no secret needed). n8n installed with npm reaches Ollama at
# localhost; n8n running in Docker reaches it at host.docker.internal - we test and keep the one that works.
if "ollamaApi" not in by_type:
    try:
        for url in [os.environ.get("OLLAMA_URL", "http://localhost:11434"), "http://host.docker.internal:11434"]:
            cid = create_credential("Ollama account", "ollamaApi", {"baseUrl": url})
            ok = credential_ok(cid)
            if ok is not False:
                print(f"created  Ollama credential ({url})" + ("" if ok else " - could not test it, check it in n8n"))
                break
            api("DELETE", f"/credentials/{cid}")
            by_type.pop("ollamaApi", None)
        else:
            print("note: n8n cannot reach Ollama. Is the Ollama app running? (ollama.com) Then run this again.")
    except ApiError as e:
        print(f"note: could not create the Ollama credential ({e}); create it in n8n: Credentials -> Ollama.")

# n8n 2.x refuses to PUBLISH a workflow while any node lacks a credential. Until you set up Slack, Twilio
# and Gmail (Part B), placeholder credentials let you publish 04/05; those three steps just fail softly.
PLACEHOLDERS = {
    "slackApi": {"accessToken": "xoxb-placeholder-replace-in-part-b"},
    "twilioApi": {"authType": "authToken", "accountSid": "ACplaceholder", "authToken": "placeholder"},
    "smtp": {"user": "placeholder@example.com", "password": "placeholder", "host": "smtp.gmail.com",
             "port": 465, "secure": True},
}
for ctype, data in PLACEHOLDERS.items():
    if ctype not in by_type:
        try:
            create_credential(f"{ctype} (placeholder - replace in Part B)", ctype, data)
            print(f"created  placeholder credential for {ctype}")
        except ApiError as e:
            print(f"note: could not create a placeholder {ctype} credential ({e})")
auto = {t: cs[0] for t, cs in by_type.items() if len(cs) == 1}
for t, cs in by_type.items():
    if len(cs) > 1:
        print(f"note: {len(cs)} credentials of type {t} exist - not auto-assigning; keep only one or pick in the UI.")

ids = {}  # workflow file -> id in n8n
for filename in ORDER:
    wf = json.loads((WF_DIR / filename).read_text(encoding="utf-8"))
    old = existing.get(wf["name"])
    old_creds = {n["name"]: n["credentials"] for n in (old or {}).get("nodes", []) if n.get("credentials")}
    for node in wf["nodes"]:
        node.pop("credentials", None)  # file placeholders point at credentials that do not exist
        if node["name"] in old_creds:
            node["credentials"] = old_creds[node["name"]]  # keep what you already selected
        elif NEEDS.get(node["type"].split(".")[-1]) in auto:
            ctype = NEEDS[node["type"].split(".")[-1]]
            node["credentials"] = {ctype: auto[ctype]}  # your only credential of this type
        target = LINKS.get(node["name"])
        if target and target in ids:
            node["parameters"]["workflowId"] = {"__rl": True, "value": ids[target], "mode": "id"}
    body = {k: wf[k] for k in ("name", "nodes", "connections", "settings")}
    try:
        if old:
            result, action = api("PUT", f"/workflows/{old['id']}", body), "updated"
        else:
            result, action = api("POST", "/workflows", body), "created"
    except ApiError as e:
        # e.g. a PUBLISHED workflow whose node still has no credential: n8n refuses to re-publish.
        print(f"SKIPPED  {wf['name']}: {e}\n         -> open it in n8n, select the missing credential, then run this again.")
        if old:
            ids[filename] = old["id"]
        continue
    ids[filename] = result["id"]
    print(f"{action:8} {result['id']}  {result['name']}")

print(f"\nDone. Open {base}/home/workflows. Check credentials on nodes with a warning, then Save/Publish.")
