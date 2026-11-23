# Deploying ShopAssist – three ways

| | A. Docker on your laptop | B. Public demo link (tunnel) | C. Cloud (Render + Groq) |
|---|---|---|---|
| What runs where | everything on your computer | your computer + a temporary public link | n8n + web app on Render, AI on Groq/Cohere, data on Supabase/Pinecone |
| Cost | free | free, no account | free plans |
| AI model | Ollama `qwen2.5:3b` (local) | same | Groq `openai/gpt-oss-120b` + Cohere multilingual embeddings |
| Works when laptop is off | no | no | **yes** (free instances sleep after 15 min; first request wakes them, ~1 min) |
| Best for | development, offline demo | live demo in an interview | a link on your CV / LinkedIn |

All three use the same workflows. The cloud workflows (`workflows/cloud/`) are generated from the same
code with `python3 scripts/build_workflows.py`. Only the model nodes differ.

---

## A. Docker on your laptop (one command)

Needs Docker Desktop and the Ollama app (for the Apple GPU).

```bash
ollama pull qwen2.5:3b && ollama pull nomic-embed-text
bash scripts/up.sh
```

The first run starts Postgres (schema + fake data loaded automatically), n8n and the web app. It then asks you
to create the n8n owner account and an API key: n8n has no way to script that step. Put the key in `.env`
and run `bash scripts/up.sh` again. That run creates the Pinecone index, imports and publishes all 7
workflows, creates the credentials and runs the health check. Finally, in n8n run workflow **01**, then **02**
(**Execute workflow**) to fill the knowledge base.

- Web app: http://localhost:8501 · n8n: http://localhost:5679 · Postgres: localhost:5433
- Already running the older n8n container on port 5679? Stop it (`docker stop shopassist-n8n`) or use
  `N8N_HOST_PORT=5680 bash scripts/up.sh`.

## B. Public demo link for an interview (2 minutes)

Your setup keeps running on your laptop. Cloudflare's free Quick Tunnel gives the **web app only** a
temporary `https://….trycloudflare.com` address (not n8n, not the database).

```bash
brew install cloudflared          # once
bash scripts/share_demo.sh
```

The script creates an `ADMIN_KEY` (the manager dashboard asks for it), starts the web app if needed and prints
the public link. Ctrl+C ends it. While the link is public:
- orders are shown only with the phone's last 4 digits (5 wrong tries lock the order for 15 minutes);
- each visitor can send 20 messages per 5 minutes, max 500 characters each;
- all data is fictional.

## C. Cloud version, 24/7: Vercel (web app) + Render (n8n) + Groq + Cohere + Supabase + Pinecone

**Live link: https://shopassistai.vercel.app**. Works with your laptop switched off.

| Part | Where | Cost |
|---|---|---|
| Web app (chat + Ops HQ) | Vercel project `shop.assist.ai`, auto-deployed from `main` | free |
| n8n (the 7 workflows) | Render web service `shopassist-n8n` (`render.yaml`); its own data in Supabase schema `n8n` | free |
| Chat AI / embeddings | Groq `openai/gpt-oss-120b` / Cohere `embed-multilingual-v3.0` | free tiers |
| Data | Supabase project `shopassist`, Pinecone index `shopassist-cloud` (1024 dims) | free |

**Easiest way to fill `.env`:** run `bash scripts/set_keys.sh`. It opens each key page, asks you to paste the
key (hidden), writes it on the right line of `.env`, shows the values Render asks for (database password copied
to the clipboard), and ends with an OK/MISSING list. Steps 1–3 below are the same thing by hand.

1. **Keys** (free): Groq → https://console.groq.com/keys. Cohere → https://dashboard.cohere.com/api-keys.
   Put them in `.env` as `GROQ_API_KEY=` and `COHERE_API_KEY=`.
2. **n8n on Render**: https://dashboard.render.com → **New → Blueprint** → connect GitHub → pick this repo → it
   reads `render.yaml` and asks for:
   - `WEBHOOK_URL`: `https://shopassist-n8n.onrender.com/` (if Render gives the service another name, use its URL, with the slash)
   - `DB_POSTGRESDB_HOST`, `DB_POSTGRESDB_USER`, `DB_POSTGRESDB_PASSWORD`: the same Supabase values as
     `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD` in your `.env` (Session pooler)

   Click **Apply**, wait until the service is **Live** (3–5 minutes).
3. **n8n account + API key**: open the Render n8n URL → create the owner account → Settings → **n8n API** →
   **Create an API key**. In `.env` set `CLOUD_N8N_URL=` (the URL, no slash) and `CLOUD_N8N_API_KEY=` (the key).
4. **One command** on your laptop:
   ```bash
   bash scripts/cloud_setup.sh
   ```
   It checks the keys, wakes n8n up, prepares Supabase and Pinecone, and imports + publishes the 7 cloud
   workflows. Each step prints OK or FAIL.
5. In the Render n8n: open workflow **01** → **Execute workflow**, then **02** (fills the knowledge base once).
6. **Vercel** → project `shop.assist.ai` → Settings → Environment Variables → add `N8N_URL` = the Render n8n URL
   (Production) → Deployments → **Redeploy**. The Supabase `POSTGRES_*` and `ADMIN_KEY` variables are already there.
   Check https://shopassistai.vercel.app/api/status: `"n8n": true, "db": true`.

Free-plan limits: the Render instance sleeps after 15 minutes without traffic, so the first chat message after a
pause takes about a minute (the next ones are fast). Groq's free tier has a daily token limit (plenty for demos).
