# ShopAssist-AI – notes for Claude Code

Capstone project: n8n customer-support agent for a fictional store (UrbanThread). Read README.md first.

## Where things stand
- n8n runs locally on the user's Mac at http://localhost:5679 (n8n 2.x). Another n8n at
  localhost:5688 belongs to someone else – never touch it.
- All 5 workflows are imported. `scripts/import_to_n8n.py` creates/updates them through the n8n API
  (updates in place by name, keeps already-selected credentials, links 03 -> 04).
- Workflow JSON is GENERATED: edit `scripts/build_workflows.py` (and `prompts/`), then run
  `python3 scripts/build_workflows.py`. Never hand-edit `workflows/*.json`.
- Secrets live only in `.env` (git-ignored; template `.env.example`). Never commit keys, never print
  full keys in output.

## Verified earlier (real n8n 2.42 + Postgres 16)
- database/schema.sql + seed.sql and every SQL query in the workflows work.
- 01: PDF download + "Set MIME Type to PDF" fix (GitHub serves application/octet-stream).
- 02: urls.txt -> 4 pages fetched -> HTML text extracted.
- 04: ticket insert returns TKT-000N; Slack/Twilio/SMTP failures do not stop the flow.
- 05: webhook delayed / unknown / normal cases all correct.

## Open problem: Google Gemini
- The user's SCHOOL Google account key returned "403 Your project has been denied access" for every
  model. A key from a PERSONAL Gmail account (AI Studio -> Create API key in new project) is needed.
- `models/gemini-2.5-flash` is no longer offered to new users; workflows use `models/gemini-flash-latest`.
- Embeddings: `models/gemini-embedding-001` (3072 dims). n8n's Gemini Embeddings node calls
  `batchEmbedContents` and silently returns EMPTY vectors on any API error, which Pinecone reports as
  "Vector dimension 0 does not match the dimension of the index 3072". Test the key with curl first:
    curl -s "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=$GOOGLE_GEMINI_API_KEY" -H 'Content-Type: application/json' -d '{"contents":[{"parts":[{"text":"Say OK"}]}]}'
    curl -s "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents?key=$GOOGLE_GEMINI_API_KEY" -H 'Content-Type: application/json' -d '{"requests":[{"model":"models/gemini-embedding-001","content":{"parts":[{"text":"hello"}]}}]}'
- If Gemini cannot work, fallback plan: Ollama on the Mac (lmChatOllama + embeddingsOllama
  nomic-embed-text, 768 dims, recreate the Pinecone index at 768). Ask the user before switching.

## Next steps
1. Run `python3 scripts/verify_setup.py` (read-only: .env, n8n credentials, Gemini, Pinecone 3072, Supabase).
   Fix model names in build_workflows.py if needed.
2. Update the n8n credential "Google Gemini(PaLM) Api" (n8n API: PATCH/POST /api/v1/credentials) or ask
   the user to paste the key in the n8n UI; make sure every Gemini node uses that one credential.
3. Run import_to_n8n.py, then run workflow 01 then 02 once each (re-running duplicates Pinecone vectors).
4. Publish 04, then 03 and 05 (n8n 2.x: the chat calls the PUBLISHED version of 04).
5. Test with docs/test_questions.md. Part B: Slack, Twilio, Gmail SMTP credentials.
