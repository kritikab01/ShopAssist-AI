# ShopAssist – step-by-step runbook (Mac, local n8n on port 5679)

Do the steps **in order**. Each step says what you should see. If something fails, run
`python3 scripts/doctor.py` and send its output.

All commands run in Terminal inside the project folder:
`cd ~/projects/shopassist-n8n/ShopAssist-AI/ShopAssist-AI`

## 0. Get the latest code
```bash
git fetch origin && git checkout main && git pull   # (or the branch you were given)
pip3 install pg8000
```
(`reset` keeps your `.env`; it is not tracked by Git.)

## 1. Database – add the new tables and data (safe to run again)
```bash
python3 scripts/setup_database.py
```
✅ You see row counts: orders 10, products 12, purchase_orders 0+, tickets 0+ (v2 adds verification_attempts,
order_events, chat_feedback - your existing data stays).

## 2. Load / update all workflows in n8n (01–07)
```bash
python3 scripts/import_to_n8n.py --publish
```
✅ `created`/`updated` for 04, 06, 03, 01, 02, 05, **07 (PO approval)**, then `published 04, 06, 07, 03, 05`.
It also creates the Postgres and Pinecone credentials from `.env` if they are missing.

## 3. Health check
```bash
python3 scripts/doctor.py
```
✅ Every workflow shows `AI=OLLAMA` (05 shows `AI=-`), no missing credentials, `n8n -> Ollama: Connection successful`.
If it says **chat messages go to the wrong port**, see step 9.

## 4. Fill the knowledge base (safe to re-run – each run replaces its own Pinecone namespace)
In n8n: open **01 Ingest FAQ PDF** → **Execute workflow** → all nodes green.
Then **02 Scrape Web Pages** → **Execute workflow** (1–2 minutes).
`python3 scripts/doctor.py` then shows `namespaces: faq=6, website=4`. Upgrading from v1? Run
`python3 scripts/setup_pinecone.py --clean-old` once to delete the old vectors in the default namespace.

## 5. Publish (n8n 2.x)
Done by `--publish` in step 2. By hand: **04** → **06** → **07** → **03** → **05** (button *Publish*).
Sub-workflows (04, 06) must be published before the agent (03) can call them.

## 6. Test from the Terminal (works even if n8n's chat window does not)
```bash
python3 scripts/test_chat.py                 # Ollama alone, workflow 03 chat, workflow 05 webhook
python3 scripts/chat_cli.py                  # interactive chat: type anything, /quit to exit
```
Try one-word messages: `UT1002` (then `0002`, the phone's last 4 digits), `returns`, `diwali`, `sizes`, `stock`, `low stock`, `kurta`, `human`,
and Hinglish: `mera order UT1003 kab aayega? last 4 digits 0003`.

## 7. The web app (chat + live dashboard)
```bash
python3 app/server.py
```
Open **http://localhost:8501** – **💬 Chat** (customer view, 👍/👎 on answers) and **📊 Ops HQ** (manager view: KPIs,
escalations, low stock, live order feed, approve/reject purchase orders). Stop with Ctrl+C.
Public link for a demo: `bash scripts/share_demo.sh` (see `docs/DEPLOY.md`).

## 8. Evaluation and KPIs for the report
```bash
python3 scripts/evaluate.py                  # 17 tests, keywords + database + AI judge -> docs/evaluation_results.md
python3 scripts/kpi_report.py                # business KPIs -> docs/kpi_report.md
```
Copy both tables into `docs/report.md` (sections 6 and 7) and take screenshots of the app.

## 9. Fix n8n's own chat window ("Error: Failed to receive response", Logs empty)
n8n sends chat messages to its **webhook URL**. Your container `shopassist-n8n` maps `5679 -> 5678` without
`WEBHOOK_URL`, so n8n thinks it lives on 5678. One command fixes it (keeps volumes, ports, settings and the
encryption key; the old container is kept as a backup and restored automatically if anything fails):
```bash
bash scripts/fix_webhook_url.sh shopassist-n8n 5679 --dry-run   # look first (changes nothing)
bash scripts/fix_webhook_url.sh shopassist-n8n 5679             # apply
```
Then workflow 03 -> double-click *Public Chat (UrbanThread)*: the Chat URL now starts with `http://localhost:5679/`.
(The terminal tools and the web app in steps 6–7 work without this fix.)

## 10. Part B (optional) – real notifications
Replace the placeholder Slack / Twilio / SMTP credentials in n8n with real ones, set the Twilio *From*
number (04, 05) and e-mail addresses (04), then publish 04, 05, 06 and 07 again. For approval links that work from your phone, set N8N_PUBLIC_URL in .env
and run `python3 scripts/import_to_n8n.py --publish` again.
