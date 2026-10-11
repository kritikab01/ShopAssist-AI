# ShopAssist-AI: An Agentic RAG Customer-Support Assistant for an Online Clothing Store

**Course:** Agentic AI for Business Automation – Individual Capstone
**Student:** _<your name>_ · **Roll no.:** _<roll no.>_ · **Date:** _<submission date>_
**Repository:** https://github.com/kritikab01/ShopAssist-AI

> All company, customer and order data in this project is fictional.

---

## 1. Business problem

UrbanThread is a small Indian online clothing brand (prices in Rs) with two support staff. Most incoming
messages are repetitive: order status, return window, refund timelines, size advice, delivery charges and
COD rules. This causes:

- slow first responses during sales (e.g. Diwali), when message volume is highest;
- angry or high-value cases waiting in the same queue as simple questions;
- no structured record of escalated issues, and no automatic alert to the team;
- customers not being told proactively when an order is delayed.

## 2. Objectives

1. Answer common questions instantly, 24×7, **only** from the store's own policies and web pages (no hallucinated policies).
2. Let customers check order status with an order ID or phone number.
3. Detect cases that need a human (anger, refund > Rs 5,000, unknown answer) and hand them over with a structured ticket and instant alerts (Slack, SMS, e-mail).
4. Notify customers by SMS automatically when an order is delayed.
5. Build it in n8n in 4–5 hours, using every topic of the course, with **zero budget**: all services are free tiers and no credit card is needed.

## 3. Architecture

_(Paste the Mermaid diagram from the README here, or a screenshot of it rendered on GitHub.)_

| Layer | Technology |
|-------|-----------|
| Orchestration / agent | n8n Cloud – AI Agent (Tools Agent) |
| LLM | Ollama `qwen2.5:3b`, running locally (free, no API key, supports tool calling) |
| Embeddings | Ollama `nomic-embed-text` (768 dims, local) |
| Vector DB | Pinecone index `shopassist` (768 dims, cosine), metadata `source`, `url`, `title` |
| Database + memory | Supabase Postgres (`orders`, `tickets`, `n8n_chat_histories`) |
| Notifications | Slack API, Twilio SMS, Gmail SMTP |
| Interface | n8n public hosted chat; webhook for the order system |

## 4. Workflow-by-workflow explanation

### 4.1 Workflow 01 – Ingest FAQ PDF
Manual trigger → HTTP Request downloads `store_faq.pdf` → **Default Data Loader** (PDF) with metadata
`source=faq` → **Recursive Character Text Splitter** (chunk 1000, overlap 200) → **Ollama embeddings** →
**Pinecone insert**. Overlap keeps sentences that cross chunk borders searchable.
_Screenshot: workflow canvas + Pinecone record count._

### 4.2 Workflow 02 – Scrape and summarize web pages
Manual trigger → read `urls.txt` → **Code** node creates one item per URL → **HTTP Request** fetches each
page → **HTML Extract** keeps body text without nav/footer → **Basic LLM Chain** (Ollama `qwen2.5:3b`,
temperature 0) summarizes each page into factual bullets → **Set** adds `url` and `title` → Pinecone insert
with metadata `source=website`, `url`, `title`. Summaries are shorter and cleaner than raw HTML, which
improves retrieval and lets the agent cite the page URL.
_Screenshot: summary output of one page._

### 4.3 Workflow 03 – ShopAssist support agent (public chat)
**Chat Trigger** (public hosted chat) → **AI Agent (Tools Agent)** with:
- **Postgres Chat Memory** – last 10 messages per session, so follow-ups like "and when will it arrive?" work;
- **faq_knowledge** – Pinecone retrieve-as-tool with metadata filter `source=faq`;
- **website_knowledge** – same index, filter `source=website`;
- **order_lookup** – Postgres tool; the LLM fills one parameter via `$fromAI()` and the query is
  parameterised (`$1`), which prevents SQL injection;
- **escalate_to_human** – Call n8n Workflow tool → workflow 04.

The system prompt (`prompts/agent_system_prompt.md`) forces the agent to answer only from tools, cite the
source, ask for an order ID when needed, refuse out-of-scope questions and escalate when the customer is
angry, the refund is above Rs 5,000, or no answer is found. Choosing *which* knowledge base to query per
question is the agentic-RAG part of the project.
_Screenshot: chat conversation + agent execution log showing tool calls._

### 4.4 Workflow 04 – Escalation sub-workflow
**Execute Workflow Trigger** receives `customer_name, phone, order_id, reason, conversation_summary` →
**LLM chain + Structured Output Parser** produces a ticket matching `prompts/ticket_schema.json`
(`issue_type`, `sentiment`, `priority` are enums; the Ollama model runs in JSON mode) → **Normalize Ticket**
(a Code node that fills any field the small model missed from the agent's inputs, so a ticket is always
created) → **Postgres insert** into `tickets` (returns
`TKT-000N`) → **Slack** message to `#support-escalations` → **Twilio SMS** to the customer →
**SMTP e-mail** to support → **Set** node returns the ticket ID to the agent. Notification nodes continue
on error so a missing phone number never breaks the chat.
_Screenshots: Slack alert, SMS on phone, e-mail, `tickets` row._

### 4.5 Workflow 05 – Order-update webhook
**Webhook** `POST /webhook/order-update` with `order_id`, `status` (and optional
`new_expected_delivery`) → **Postgres UPDATE** → **IF** status = `delayed` → **Twilio SMS** to the customer
→ **Respond to Webhook** with JSON (`ok: false` for unknown orders).
_Screenshot: curl/Postman request and response + SMS._

### 4.6 Workflow 06 – Inventory Agent (second domain-expert agent)
The support agent (03) does not handle stock itself: it calls the **Inventory Agent** through the
`inventory_expert` tool (an agent used as a tool = multi-agent system). The Inventory Agent has its own
system prompt (`prompts/inventory_agent_prompt.md`) and two tools: **stock_lookup** (Postgres `products`,
search by name / SKU / size or "low") and **create_purchase_order** (inserts a `purchase_orders` row with
status *pending_approval*, cost = units × unit cost). A Slack message then asks a manager to approve it.
Customers only hear "in stock / out of stock"; managers get stock levels and purchase orders – the same
agent serves two business processes (customer service and procurement).
_Screenshots: workflow 06 canvas, chat asking "low stock", new PO row in Supabase._

### 4.7 Interfaces: web app, Terminal chat, one-word messages
- **Web app** (`app/server.py`, http://localhost:8501): chat with one-tap buttons and a **live dashboard**
  (orders by status, tickets, low stock, purchase orders) read from Postgres every 10 seconds.
- **Terminal chat** (`scripts/chat_cli.py`): ask anything interactively.
- **One-word messages**: the system prompt maps `UT1002` → order lookup, `returns` → FAQ, `diwali` → offers,
  `stock` / product names → Inventory Agent, `human` → escalation.

## 5. Course mapping

See `docs/course_mapping.md` for the full session-by-session table. Summary of the capstone line:

| Capstone requirement | Implemented in |
|----------------------|----------------|
| RAG with Pinecone | Workflows 01, 02, 03 |
| Scraping web pages and summarization | Workflow 02 |
| Send SMS using Twilio | Workflows 04, 05 |
| Slack API | Workflow 04 |

## 6. Results

Test plan: `docs/test_questions.md` (14 chat tests + 2 webhook tests). The 14 chat tests are run and scored
automatically by `python3 scripts/evaluate.py`; paste the table from `docs/evaluation_results.md` here.

**Automatic evaluation score:** _x / 14 passed, average answer time _y_ s (local qwen2.5:3b)._

| # | Test | Expected | Actual | Pass |
|---|------|----------|--------|------|
| 1 | FAQ – return policy | 15-day policy, cites FAQ | | |
| 2 | Website – Diwali code | DIWALI25, cites page URL | | |
| 3 | Order lookup UT1002 | shipped, Delhivery, tracking | | |
| 4 | Combined UT1005 return + refund | order + FAQ, both cited | | |
| 5 | Missing order ID | asks for ID/phone | | |
| 6 | Angry customer UT1003 | ticket + Slack + SMS + e-mail | | |
| 7 | Out of scope | polite refusal, no ticket | | |
| 8 | Refund > Rs 5,000 (UT1004) | escalation, priority high | | |
| 9–11 | One-word messages (UT1003, returns, diwali) | right tool, short answer | | |
| 12–14 | Inventory Agent (availability, low stock, purchase order) | stock answer, PO-000N | | |
| W1 | Webhook delayed UT1002 | DB updated + SMS | | |
| W2 | Webhook unknown order | `ok: false` | | |

**Screenshots** (add to `docs/screenshots/` and link here):

- [ ] Fig 1 – Workflow 01 canvas · [ ] Fig 2 – Workflow 02 canvas and a summary
- [ ] Fig 3 – Workflow 03 canvas · [ ] Fig 4 – Public chat conversation (tests 1–4)
- [ ] Fig 5 – Escalation: chat reply with ticket ID · [ ] Fig 6 – Slack alert
- [ ] Fig 7 – SMS received · [ ] Fig 8 – Escalation e-mail · [ ] Fig 9 – `tickets` table in Supabase
- [ ] Fig 10 – Webhook test response · [ ] Fig 11 – Pinecone index with metadata

**Observations:** _(e.g. average response time, number of tool calls per question, any wrong answers and why)._

### Business KPIs

Generated by `python3 scripts/kpi_report.py` (paste `docs/kpi_report.md` here): conversations handled by the AI,
tickets escalated to humans (by type and priority), share of conversations resolved without a human,
products below reorder level and purchase orders drafted by the Inventory Agent.

## 7. Limitations

- Fictional data and small knowledge base (1 PDF, 4 pages); real stores need regular re-ingestion.
- Re-running ingestion creates duplicate vectors (no upsert by document ID).
- Public chat has no login: anyone who knows an order ID can see its status (production needs OTP verification).
- Sentiment / anger detection depends on the LLM and may miss sarcasm or Hinglish.
- Twilio trial sends only to verified numbers and adds a trial prefix to messages.
- The automatic evaluation checks for expected facts (keywords), not full answer quality.
- A small local model (3B parameters) is slower and makes more mistakes than large cloud models; answers depend on the laptop's speed.
- The chat works only while the computer, n8n and Ollama are running (self-hosted).
- English only.

## 8. Future scope

1. **Approval loop for purchase orders:** a Slack button that approves the PO, updates its status and texts
   the supplier via Twilio (today the Inventory Agent drafts the PO and asks for approval in Slack).
2. **Flowise version:** rebuild the same agent in Flowise to compare low-code agent builders.
3. **Bigger or cloud models:** compare the local `qwen2.5:3b` with `qwen2.5:7b` or a hosted model (Gemini, GPT) for answer quality and speed.
4. WhatsApp channel via Twilio WhatsApp API; Hindi and Hinglish support.
5. OTP verification before showing order details; automatic re-scraping on a schedule.
6. Dashboard of ticket volume, sentiment and resolution time.

## 9. Conclusion

ShopAssist shows how two domain-expert n8n AI agents (customer support and inventory) can combine two
RAG knowledge bases, a SQL database and a human-in-the-loop escalation path to automate routine customer support while making sure urgent and
high-value cases reach a person quickly through Slack, SMS and e-mail.
