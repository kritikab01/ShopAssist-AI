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
1. Install Ollama, `ollama pull qwen2.5:3b`, `ollama pull nomic-embed-text`.
2. `python3 scripts/setup_pinecone.py`, then `set -a; source .env; set +a; python3 scripts/import_to_n8n.py`.
3. `python3 scripts/verify_setup.py` -> all checks pass.
4. Run 01 then 02 once each; publish 04, then 03 and 05; test with docs/test_questions.md.
5. Part B: real Slack, Twilio, Gmail SMTP credentials replace the placeholders; publish 04/05 again.
