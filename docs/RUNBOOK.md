# ShopAssist – step-by-step runbook (Mac, local n8n on port 5679)

Do the steps **in order**. Each step says what you should see. If something fails, run
`python3 scripts/doctor.py` and send its output.

All commands run in Terminal inside the project folder:
`cd ~/projects/shopassist-n8n/ShopAssist-AI/ShopAssist-AI`

## 0. Get the latest code
```bash
git fetch origin && git reset --hard origin/claude/quirky-tesla-gzzg4y
pip3 install pg8000
```
(`reset` keeps your `.env`; it is not tracked by Git.)

## 1. Database – add the new tables and data (safe to run again)
```bash
python3 scripts/setup_database.py
```
✅ You see row counts: orders 10, products 12, purchase_orders 0+, tickets 0+.

## 2. Load / update all workflows in n8n (01–06)
```bash
python3 scripts/import_to_n8n.py
```
✅ `created`/`updated` for 04, **06 (new Inventory Agent)**, 03, 01, 02, 05.

## 3. Health check
```bash
python3 scripts/doctor.py
```
✅ Every workflow shows `AI=OLLAMA` (05 shows `AI=-`), no missing credentials, `n8n -> Ollama: Connection successful`.
If it says **chat messages go to the wrong port**, see step 9.

## 4. Fill the knowledge base (only once – re-running duplicates vectors)
In n8n: open **01 Ingest FAQ PDF** → **Execute workflow** → all nodes green.
Then **02 Scrape Web Pages** → **Execute workflow** (1–2 minutes).

## 5. Publish (n8n 2.x) – in this order
**04** → **06** → **03** → **05** (button *Publish*, top right of each workflow).
Sub-workflows (04, 06) must be published before the agent (03) can call them.

## 6. Test from the Terminal (works even if n8n's chat window does not)
```bash
python3 scripts/test_chat.py                 # Ollama alone, workflow 03 chat, workflow 05 webhook
python3 scripts/chat_cli.py                  # interactive chat: type anything, /quit to exit
```
Try one-word messages: `UT1002`, `returns`, `diwali`, `sizes`, `stock`, `low stock`, `kurta`, `human`.

## 7. The web app (chat + live dashboard)
```bash
python3 app/server.py
```
Open **http://localhost:8501** – chat on the left (with one-tap buttons), live numbers from the database
on the right (orders, tickets, low stock, purchase orders), refreshed every 10 s. Stop with Ctrl+C.

## 8. Evaluation and KPIs for the report
```bash
python3 scripts/evaluate.py                  # 14 test questions -> score -> docs/evaluation_results.md
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
number (04, 05) and e-mail addresses (04), then publish 04, 05 and 06 again.
