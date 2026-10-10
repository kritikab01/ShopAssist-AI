"""Create all 5 ShopAssist workflows in your n8n with one command (n8n public API).

Run this ON YOUR OWN COMPUTER (where n8n runs), from the repo folder:

    export N8N_URL=http://localhost:5679
    export N8N_API_KEY=...          # n8n -> Settings -> n8n API -> Create an API key
    python3 scripts/import_to_n8n.py

What it does:
  1. creates workflow 04 (escalation) first and remembers its new ID;
  2. puts that ID into the `escalate_to_human` tool of workflow 03 (no manual linking);
  3. creates workflows 03, 01, 02 and 05.
Nothing is activated. Credentials are left empty: open each node with a warning and
select your credential (n8n picks it automatically if you have only one of that type).
Only Python 3 standard library is used - no pip install needed.
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


def create(workflow: dict) -> dict:
    # The API accepts only these four fields on create.
    body = {k: workflow[k] for k in ("name", "nodes", "connections", "settings")}
    for node in body["nodes"]:
        node.pop("credentials", None)  # placeholders would point at credentials that do not exist
    req = urllib.request.Request(
        f"{base}/api/v1/workflows", data=json.dumps(body).encode(), method="POST",
        headers={"X-N8N-API-KEY": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"n8n refused '{body['name']}': HTTP {e.code} {e.read().decode()[:500]}")
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach n8n at {base}: {e.reason}. Is n8n running? Is N8N_URL right?")


escalation_id = None
for filename in ORDER:
    wf = json.loads((WF_DIR / filename).read_text(encoding="utf-8"))
    if filename.startswith("03") and escalation_id:
        for node in wf["nodes"]:
            if node["name"] == "escalate_to_human":
                node["parameters"]["workflowId"] = {
                    "__rl": True, "value": escalation_id, "mode": "list",
                    "cachedResultName": "04 Escalation Sub-workflow (Ticket + Slack + SMS + Email)"}
    created = create(wf)
    if filename.startswith("04"):
        escalation_id = created["id"]
    print(f"created  {created['id']}  {created['name']}")

print(f"\nDone. Open {base}/home/workflows - all 5 workflows are there (inactive).")
