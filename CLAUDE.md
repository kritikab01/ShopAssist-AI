# ShopAssist-AI – notes for Claude Code

Capstone project: n8n customer-support agent for a fictional store (UrbanThread). Read README.md first.

## Where things stand
- n8n runs locally on the user's Mac at http://localhost:5679 (n8n 2.x). Another n8n at
  localhost:5688 belongs to someone else – never touch it.
- AI runs locally with **Ollama**: chat `qwen2.5:3b` (tool calling), embeddings `nomic-embed-text`
  (768 dims). Google Gemini was dropped: Google returned "403 project denied" for the user's keys.
- Pinecone index `shopassist` must be **768** dims, cosine (`scripts/setup_pinecone.py`).
- Workflow JSON is GENERATED: edit `scripts/build_workflows.py` (and `prompts/`), then run
  `python3 scripts/build_workflows.py`. Never hand-edit `workflows/*.json`.
- `scripts/import_to_n8n.py` creates/updates the 5 workflows via the n8n API (by name), keeps chosen
  credentials, auto-assigns the only credential of each type, creates the Ollama credential (tests
  localhost then host.docker.internal) and placeholder Slack/Twilio/SMTP credentials (n8n 2.x will not
  publish a workflow with a node lacking a credential), and links 03 -> 04.
- Multi-agent: workflow 03 (support agent) calls workflow 06 (Inventory Agent: stock_lookup,
  create_purchase_order on Postgres `products` / `purchase_orders`) through the `inventory_expert` tool.
- 03 guardrails: Detect Intent code node (notes + `intent` flags) before the agent; after it, Order Details
  (Postgres) -> Needs a Ticket? -> IF -> Create Ticket (executeWorkflow 1.2 -> 04, linked by import LINKS)
  -> output + TKT id. Verified in sandbox: angry/refund>5000 get one ticket, no duplicates, UT1005 refund none.
- Runbook for the user: `docs/RUNBOOK.md`. Tools: setup_database.py, import_to_n8n.py, doctor.py,
  test_chat.py, chat_cli.py (interactive), evaluate.py (14 scored tests), kpi_report.py, app/server.py
  (web app :8501, chat + live dashboard; posts to N8N_URL so n8n's WEBHOOK_URL port problem does not matter).
- Known user issue: n8n in Docker `-p 5679:5678` without WEBHOOK_URL -> n8n's own chat window posts to 5678
  ("Failed to receive response", empty Logs). Fix: WEBHOOK_URL=http://localhost:5679/ (RUNBOOK step 9).
- `scripts/verify_setup.py` is read-only: .env, n8n credentials (self-test), Ollama, Pinecone 768, Supabase.
- Secrets live only in `.env` (git-ignored; template `.env.example`). Never commit keys, never print
  full keys in output.

## Verified (real n8n 2.42 + Postgres 16 + an Ollama API stand-in; Pinecone swapped for in-memory store)
- schema/seed and every SQL query; 01 PDF -> MIME fix -> 6 chunks embedded (768) and stored;
  02 4 pages scraped, summarized, embedded, stored; 04 ticket saved both when the model returns proper
  {"output": {...}} JSON and when it does not (Normalize Ticket fallback); 03 public chat URL: faq tool,
  order_lookup (Postgres), escalate_to_human -> published 04 -> TKT id; chat memory rows saved; 05 webhook.
- Ollama options that matter: numCtx 8192 (default 2048 truncates the agent prompt), think false.
- Not verifiable in the cloud sandbox: real model answer quality, real Pinecone calls.

## Next steps for the user
Follow docs/RUNBOOK.md (setup_database -> import -> doctor -> run 01, 02 -> publish 04, 06, 03, 05 ->
test_chat / chat_cli / app -> evaluate + kpi_report -> Part B real Slack/Twilio/SMTP).
