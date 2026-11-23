# Deploying ShopAssist – three ways

| | A. Docker on your laptop | B. Public demo link (tunnel) | C. Cloud (Render + Groq) |
|---|---|---|---|
| What runs where | everything on your computer | your computer + a temporary public link | n8n + web app on Render, AI on Groq/Cohere, data on Supabase/Pinecone |
| Cost | free | free, no account | free plans |
| AI model | Ollama `qwen2.5:3b` (local) | same | Groq `llama-3.3-70b-versatile` + Cohere multilingual embeddings |
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

## C. Cloud version (Render + Groq + Cohere + Supabase + Pinecone)

1. **Keys** (all free): Groq → console.groq.com → API Keys. Cohere → dashboard.cohere.com → API keys (trial).
   Put both in `.env` (`GROQ_API_KEY`, `COHERE_API_KEY`), plus your Supabase `POSTGRES_*` and `PINECONE_API_KEY`.
2. **Database**: `python3 scripts/setup_database.py`. This also creates the `n8n` schema where cloud n8n keeps its data.
3. **Pinecone**: `python3 scripts/setup_pinecone.py --cloud` (index `shopassist-cloud`, 1024 dimensions; Cohere
   vectors are a different size from Ollama's 768).
4. **Render**: render.com → New → **Blueprint** → pick this GitHub repo (`render.yaml`). Enter the values it asks
   for: Supabase *Session pooler* host/user/password for both services. For `WEBHOOK_URL` use
   `https://shopassist-n8n.onrender.com/`; for `N8N_URL` use `https://shopassist-n8n.onrender.com`. The service
   names may get a suffix, so copy the real URL from the dashboard.
5. Open the n8n URL, create the owner account, then Settings → n8n API → create a key. In `.env` set
   `N8N_URL` and `N8N_PUBLIC_URL` to the Render n8n URL and `N8N_API_KEY` to the key, then:
   ```bash
   python3 scripts/import_to_n8n.py --cloud --publish
   ```
6. In n8n run workflow 01, then 02. Open the **shopassist-app** URL. The dashboard key is in Render → shopassist-app →
   Environment → `ADMIN_KEY`.

Limits of the free plans: Render free instances sleep after 15 minutes without traffic and have 512 MB RAM;
the Groq free tier allows a limited number of tokens per day (plenty for demos). For real traffic, use a paid
instance or n8n Cloud.

---

## D. Vercel (the live link)

**Live URL: https://shopassistai.vercel.app** (Vercel project `shop.assist.ai`). Vercel is connected to this
GitHub repo: every merge into `main` is deployed to production automatically, and every other branch gets
its own preview URL. There is nothing to "update" by hand. Merge the pull request, wait about a minute, and the
link shows the new version. Check under Vercel → project → **Deployments**: the top *Production* entry should show
the latest `main` commit.

Vercel hosts only the **web app** (`app/server.py`; its database driver `pg8000` is declared in `pyproject.toml`, which Vercel installs from). n8n and the
AI do not run on Vercel, so the app needs these **Environment Variables** (Vercel → project → Settings →
Environment Variables → Production), followed by a **Redeploy**:

| Name | Value |
|---|---|
| `N8N_URL` | a public address of your n8n, e.g. the Render n8n (`https://shopassist-n8n.onrender.com`, section C) or a tunnel to your Mac (`cloudflared tunnel --url http://localhost:5679`) |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | your Supabase *Session pooler* values (same as in `.env`) |
| `POSTGRES_SSL` | `require` |
| `ADMIN_KEY` | a long random string: it locks the Ops HQ dashboard, which is otherwise public |

Without them the page loads, but the chat shows an error and Ops HQ shows "database not available". Check after a
redeploy: `https://shopassistai.vercel.app/api/status` should show `"n8n": true, "db": true`.

