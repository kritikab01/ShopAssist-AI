"""Create or update all 7 ShopAssist workflows in your n8n with one command (n8n public API).

Run this ON YOUR OWN COMPUTER (where n8n runs), from the repo folder:

    git pull                        # get the latest workflow files first
    python3 scripts/import_to_n8n.py     # reads N8N_URL / N8N_API_KEY / OLLAMA_URL from .env

What it does:
  1. workflow 04 (escalation) and 06 (inventory agent) first, then 03, 01, 02, 05, 07;
  2. if a workflow with the same name already exists it is UPDATED in place (same ID, same URL)
     and every node keeps the credential you already selected (matched by node name);
     otherwise it is created;
  3. creates the Ollama credential (and placeholder Slack/Twilio/SMTP credentials so 04/05 can be
     published) if they do not exist; nodes with no credential get your credential of the right
     type if you have exactly one of it;
  4. points the tools of workflow 03 at the real IDs: escalate_to_human -> 04, inventory_expert -> 06.
Nodes that never had a credential show a warning: open them and select your credential.
Only the Python 3 standard library is used - no pip install needed.

Options:
    --publish   also publish (activate) 04, 06, 07, 03, 05 in that order (sub-workflows before the agent)
    --cloud     import workflows/cloud/ (Groq chat + Cohere embeddings) and create the Groq / Cohere
                credentials from GROQ_API_KEY / COHERE_API_KEY in .env - for a hosted n8n without Ollama
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CLOUD = "--cloud" in sys.argv
PUBLISH = "--publish" in sys.argv
WF_DIR = Path(__file__).resolve().parent.parent / "workflows" / ("cloud" if CLOUD else "")
ORDER = ["04_escalation_subworkflow.json", "06_inventory_agent.json", "03_support_agent_chat.json",
         "01_ingest_faq_pdf.json", "02_scrape_and_summarize.json", "05_order_update_webhook.json",
         "07_po_approval.json"]
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
# Address of n8n for people's browsers (approval links in Slack): a tunnel or cloud URL if you have one.
public = (os.environ.get("N8N_PUBLIC_URL") or base).rstrip("/")
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
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            # A cloud n8n that is still starting (or catching up with a slow database) answers 503
            # "Database is not ready!" before it handles the request, so it is safe to send it again.
            if e.code == 503 and attempt < 7:
                print("       n8n is not ready yet (503), retrying in 10 s ...", flush=True)
                time.sleep(10)
                continue
            if e.code == 403 and "<title>Blocked</title>" in text:
                raise ApiError("HTTP 403 blocked by the hosting provider's web firewall (not by n8n)")
            raise ApiError(f"HTTP {e.code} {text[:400]}")
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
NEEDS = {"lmChatGroq": "groqApi", "embeddingsCohere": "cohereApi", "vectorStorePinecone": "pineconeApi", "embeddingsOllama": "ollamaApi", "lmChatOllama": "ollamaApi",
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
for ctype, var in (("groqApi", "GROQ_API_KEY"), ("cohereApi", "COHERE_API_KEY"), ("pineconeApi", "PINECONE_API_KEY")):
    if ctype not in by_type and "REPLACE_ME" not in os.environ.get(var, "REPLACE_ME") and (CLOUD or ctype == "pineconeApi"):
        try:
            create_credential(f"{ctype[:-3].title()} account", ctype, {"apiKey": os.environ[var]})
            print(f"created  {ctype} credential from {var} in .env")
        except ApiError as e:
            print(f"note: could not create the {ctype} credential ({e})")

if "ollamaApi" not in by_type and not CLOUD:
    try:
        for url in [u for u in (os.environ.get("OLLAMA_URL_FOR_N8N"), os.environ.get("OLLAMA_URL", "http://localhost:11434"),
                                "http://host.docker.internal:11434", "http://ollama:11434") if u]:
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

# Postgres credential from .env (POSTGRES_*), so you do not have to type it into n8n. POSTGRES_HOST_FOR_N8N
# overrides the host as n8n sees it (e.g. "postgres" when both run in docker compose).
if "postgres" not in by_type and "REPLACE_ME" not in os.environ.get("POSTGRES_HOST", "REPLACE_ME") + \
        os.environ.get("POSTGRES_PASSWORD", "REPLACE_ME"):
    ssl = (os.environ.get("POSTGRES_SSL") or "require").lower()
    ssl = "disable" if ssl in ("disable", "false", "0") else "require"
    try:
        create_credential("Supabase Postgres", "postgres", {
            "host": os.environ.get("POSTGRES_HOST_FOR_N8N") or os.environ["POSTGRES_HOST"],
            "port": int(os.environ.get("POSTGRES_PORT_FOR_N8N") or os.environ.get("POSTGRES_PORT") or 5432),
            "database": os.environ.get("POSTGRES_DB") or "postgres",
            "user": os.environ.get("POSTGRES_USER") or "postgres",
            "password": os.environ["POSTGRES_PASSWORD"],
            "ssl": ssl, "allowUnauthorizedCerts": ssl == "require", "maxConnections": 10,
        })
        print("created  Postgres credential from .env (POSTGRES_*)")
    except ApiError as e:
        print(f"note: could not create the Postgres credential ({e}); create it in n8n: Credentials -> Postgres.")

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


# Part B: real Slack / Twilio / SMTP from .env. A channel switches on only when ALL its values are real
# (not the .env.example placeholders). Its placeholder credential is then replaced by a real one, and the
# nodes get the real sender / recipient below. Values are never printed.
def real(var):
    v = os.environ.get(var, "")
    bad = ("REPLACE", "XXXX", "placeholder", "example", "your.", "+10000000000")
    return v if v and not any(b.lower() in v.lower() for b in bad) else ""


PART_B = {
    "slackApi": ("Slack (from .env)", ["SLACK_BOT_TOKEN"],
                 lambda: {"accessToken": real("SLACK_BOT_TOKEN")}),
    "twilioApi": ("Twilio (from .env)", ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
                                                 "TWILIO_TEST_TO_NUMBER"],
                  lambda: {"authType": "authToken", "accountSid": real("TWILIO_ACCOUNT_SID"),
                           "authToken": real("TWILIO_AUTH_TOKEN")}),
    "smtp": ("SMTP (from .env)", ["SMTP_USER", "SMTP_APP_PASSWORD", "SUPPORT_EMAIL"],
             lambda: {"user": real("SMTP_USER"), "password": real("SMTP_APP_PASSWORD"),
                      "host": os.environ.get("SMTP_HOST") or "smtp.gmail.com",
                      "port": int(os.environ.get("SMTP_PORT") or 465),
                      "secure": (os.environ.get("SMTP_SSL") or "true").lower() not in ("false", "0", "no")}),
}
swap = {}  # placeholder credential id -> real credential (nodes that used the placeholder move over)
part_b_on = set()
for ctype, (cname, needs, data) in PART_B.items():
    missing = [v for v in needs if not real(v)]
    if missing:
        print(f"Part B   {ctype}: off - set real {', '.join(missing)} in .env")
        continue
    part_b_on.add(ctype)
    mine = [c for c in by_type.get(ctype, []) if c["name"] == cname]
    try:
        if mine:  # refresh it from .env (delete + create: the public API cannot edit secrets in place)
            api("DELETE", f"/credentials/{mine[0]['id']}")
            by_type[ctype].remove(mine[0])
        old_ids = [c["id"] for c in by_type.get(ctype, []) if "placeholder" in c["name"]] + [c["id"] for c in mine]
        new = {"id": create_credential(cname, ctype, data()), "name": cname}
        for c in list(by_type[ctype]):
            if "placeholder" in c["name"]:
                api("DELETE", f"/credentials/{c['id']}")
                by_type[ctype].remove(c)
        for oid in old_ids:
            swap[oid] = new
        ok = credential_ok(new["id"])
        print(f"Part B   {ctype}: real credential '{cname}' from .env" +
              {True: " - tested OK", False: " - n8n test FAILED, check the values", None: ""}[ok])
    except ApiError as e:
        print(f"Part B   {ctype}: could not create the real credential ({e})")
        part_b_on.discard(ctype)


def apply_part_b(node):
    """Real sender / recipient on notification nodes (only for channels switched on above)."""
    t, p = node["type"].split(".")[-1], node["parameters"]
    if t == "slack" and "slackApi" in part_b_on and real("SLACK_CHANNEL") and isinstance(p.get("channelId"), dict):
        p["channelId"]["value"] = real("SLACK_CHANNEL")
    if t == "twilio" and "twilioApi" in part_b_on:
        p["from"] = real("TWILIO_FROM_NUMBER")
        p["to"] = real("TWILIO_TEST_TO_NUMBER")  # demo safety: every SMS goes to YOUR verified phone, not seed customers
    if t == "emailSend" and "smtp" in part_b_on:
        p["fromEmail"], p["toEmail"] = real("SMTP_USER"), real("SUPPORT_EMAIL")
auto = {t: cs[0] for t, cs in by_type.items() if len(cs) == 1}
for t, cs in by_type.items():
    if len(cs) > 1:
        print(f"note: {len(cs)} credentials of type {t} exist - not auto-assigning; keep only one or pick in the UI.")

ids = {}  # workflow file -> id in n8n
for filename in ORDER:
    wf = json.loads((WF_DIR / filename).read_text(encoding="utf-8").replace("__N8N_PUBLIC_URL__", public))
    old = existing.get(wf["name"])
    old_creds = {n["name"]: n["credentials"] for n in (old or {}).get("nodes", []) if n.get("credentials")}
    for node in wf["nodes"]:
        node.pop("credentials", None)  # file placeholders point at credentials that do not exist
        apply_part_b(node)
        if node["name"] in old_creds:
            node["credentials"] = {t: swap.get(c.get("id"), c)
                                   for t, c in old_creds[node["name"]].items()}  # keep yours (placeholder -> real)
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

if PUBLISH:
    # Sub-workflows first: n8n checks that a called workflow is published when the caller is published.
    for filename in ["04_escalation_subworkflow.json", "06_inventory_agent.json", "07_po_approval.json",
                     "03_support_agent_chat.json", "05_order_update_webhook.json"]:
        if filename not in ids:
            continue
        try:
            api("POST", f"/workflows/{ids[filename]}/activate")
            print(f"published {filename[:2]}")
        except ApiError as e:
            print(f"NOT published {filename[:2]}: {e}")

print(f"\nDone. Open {base}/home/workflows. Check credentials on nodes with a warning" +
      ("." if PUBLISH else ", then Publish 04, 06, 07, 03, 05 (or run again with --publish)."))
