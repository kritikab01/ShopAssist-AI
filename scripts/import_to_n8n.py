"""Create or update all 5 ShopAssist workflows in your n8n with one command (n8n public API).

Run this ON YOUR OWN COMPUTER (where n8n runs), from the repo folder:

    git pull                        # get the latest workflow files first
    export N8N_URL=http://localhost:5679
    export N8N_API_KEY=...          # n8n -> Settings -> n8n API -> Create an API key
    python3 scripts/import_to_n8n.py

What it does:
  1. workflow 04 (escalation) first, then 03, 01, 02, 05;
  2. if a workflow with the same name already exists it is UPDATED in place (same ID, same URL)
     and every node keeps the credential you already selected (matched by node name);
     otherwise it is created;
  3. puts workflow 04's ID into the `escalate_to_human` tool of workflow 03.
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
ORDER = ["04_escalation_subworkflow.json", "03_support_agent_chat.json",
         "01_ingest_faq_pdf.json", "02_scrape_and_summarize.json", "05_order_update_webhook.json"]

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

escalation_id = None
for filename in ORDER:
    wf = json.loads((WF_DIR / filename).read_text(encoding="utf-8"))
    old = existing.get(wf["name"])
    old_creds = {n["name"]: n["credentials"] for n in (old or {}).get("nodes", []) if n.get("credentials")}
    for node in wf["nodes"]:
        node.pop("credentials", None)  # file placeholders point at credentials that do not exist
        if node["name"] in old_creds:
            node["credentials"] = old_creds[node["name"]]  # keep what you already selected
        if node["name"] == "escalate_to_human" and escalation_id:
            node["parameters"]["workflowId"] = {
                "__rl": True, "value": escalation_id, "mode": "list",
                "cachedResultName": "04 Escalation Sub-workflow (Ticket + Slack + SMS + Email)"}
    body = {k: wf[k] for k in ("name", "nodes", "connections", "settings")}
    try:
        if old:
            result, action = api("PUT", f"/workflows/{old['id']}", body), "updated"
        else:
            result, action = api("POST", "/workflows", body), "created"
    except ApiError as e:
        # e.g. a PUBLISHED workflow whose node still has no credential: n8n refuses to re-publish.
        print(f"SKIPPED  {wf['name']}: {e}\n         -> open it in n8n, select the missing credential, then run this again.")
        if filename.startswith("04") and old:
            escalation_id = old["id"]
        continue
    if filename.startswith("04"):
        escalation_id = result["id"]
    print(f"{action:8} {result['id']}  {result['name']}")

print(f"\nDone. Open {base}/home/workflows. Check credentials on nodes with a warning, then Save/Publish.")
