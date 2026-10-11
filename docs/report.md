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
5. Build it in n8n using every topic of the course, with **zero budget**: local AI (Ollama) and free tiers, no credit card needed.

## 3. Architecture

![Architecture](screenshots/architecture.png)

| Layer | Technology |
|-------|-----------|
| Orchestration / agent | n8n 2.x self-hosted in Docker – AI Agent (Tools Agent) |
| LLM | Ollama `qwen2.5:3b`, running locally (free, no API key, supports tool calling) |
| Embeddings | Ollama `nomic-embed-text` (768 dims, local) |
| Vector DB | Pinecone index `shopassist` (768 dims, cosine), metadata `source`, `url`, `title` |
| Database + memory | Supabase Postgres (`orders`, `tickets`, `n8n_chat_histories`) |
| Notifications | Slack API, Twilio SMS, Gmail SMTP |
| Interface | n8n public hosted chat, web app with live dashboard (port 8501), Terminal chat; webhook for the order system |

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

**Guardrails around the agent (deterministic, no AI).** A small local model does not always follow the
prompt, so two rule-based steps wrap it. *Detect Intent* (before the agent) adds a short note to the message
for anger or a request for a human, refunds, stock questions, offers and coupon codes ("search the website,
never invent a code") and off-topic requests. *Guaranteed escalation* (after the agent) works like this: if the
customer is upset or asks for a human, or asks for a refund on an order above Rs 5,000 (amount read from
Postgres), and the reply has no `TKT-` ticket ID, the workflow calls workflow 04 itself and adds the ticket ID
to the reply. This is a human-in-the-loop safety net. Escalation never depends on the model alone.
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

**Automatic evaluation score: 14 / 14 passed, average answer time 10 s** (local qwen2.5:3b through Ollama on a
MacBook Air, run on 11 Oct 2026). Before the guardrails were added the score was 9 / 14.

| # | Test | Expected | Actual (shortened) | Time | Pass |
|---|------|----------|--------------------|------|------|
| 1 | FAQ – return policy | 15-day policy | "return items within 15 days from the date of delivery..." | 23 s | ✅ |
| 2 | Website – Diwali code | DIWALI25 | "DIWALI25 – 25% off orders over Rs 2,499 from 20 October..." | 10 s | ✅ |
| 3 | Order lookup UT1002 | shipped, Delhivery | "Your order UT1002 is in the Shipped status. 1 Linen Kurta (S)..." | 5 s | ✅ |
| 4 | Combined UT1005 return + refund | order + 15-day policy + refund | mentions 15 days and refund, but also an unrelated "out of stock" remark | 14 s | ✅* |
| 5 | Missing order ID | asks for ID/phone | "Could you please provide your order ID or phone number?" | 3 s | ✅ |
| 6 | Angry customer UT1003 | ticket ID | order UT1003 delayed (Ekart) + ticket TKT-0007 (Rohan Gupta, delivery, high) | 13 s | ✅ |
| 7 | Out of scope (Python script) | polite refusal, no code | "...only help with UrbanThread orders, returns, sizes, delivery, offers and stock." | 2 s | ✅ |
| 8 | Refund > Rs 5,000 (UT1004) | escalation | "refund amount exceeds Rs 5000, I need to escalate..." – ticket TKT-0008 (Sneha Iyer, refund, high) | 12 s | ✅ |
| 9 | One word: `UT1003` | order status | "Your order UT1003 is delayed..." (Ekart) | 7 s | ✅ |
| 10 | One word: `returns` | 15-day policy | "Returns and exchanges are processed within 15 days..." | 16 s | ✅ |
| 11 | One word: `diwali` | DIWALI25 | "Diwali offers ... 20 October to 5 November 2026 – DIWALI25: 25% off..." | 14 s | ✅ |
| 12 | Inventory: kurta size M | in stock | "The linen kurta is in stock and available in size M." | 5 s | ✅ |
| 13 | Inventory: low stock | low-stock SKUs | "products at or below their reorder level: Basics Cotton T-shirt (L): Stock 6..." | 12 s | ✅ |
| 14 | Inventory: purchase order | PO-000N | "A purchase order (PO-0002) has been created for Rs 1,800" | 7 s | ✅* |
| W1 | Webhook delayed UT1002 | DB updated + SMS | tested in setup (`scripts/test_chat.py`) | – | ✅ |
| W2 | Webhook unknown order | `ok: false` | tested in setup | – | ✅ |

\* passed the automatic check, but a human reading found a wrong detail (see observations).

**Screenshots** (add to `docs/screenshots/` and link here):

- [ ] Fig 1 – Workflow 01 canvas · [ ] Fig 2 – Workflow 02 canvas and a summary
- [ ] Fig 3 – Workflow 03 canvas · [ ] Fig 4 – Public chat conversation (tests 1–4)
- [ ] Fig 5 – Escalation: chat reply with ticket ID · [ ] Fig 6 – Slack alert
- [ ] Fig 7 – SMS received · [ ] Fig 8 – Escalation e-mail · [ ] Fig 9 – `tickets` table in Supabase
- [ ] Fig 10 – Webhook test response · [ ] Fig 11 – Pinecone index with metadata

**Observations:**

- **Speed:** 2–23 s per answer on a laptop, 10 s on average. Knowledge-base answers (1, 10) are slowest because they
  need an embedding call, a Pinecone search and a longer answer. Database answers (3, 5, 12) take 3–5 s.
- **Guardrails made the difference.** The first run scored 9 / 14. Two failures (6, 8) came from the small model
  *saying* it had escalated without calling the tool, one (2) from an invented coupon code, and two (13, 14) from
  time-outs. Model instructions alone did not fix these. Deterministic rules did: the *Detect Intent* pre-check,
  the *guaranteed escalation* step after the agent, the ticket *Normalize* step, time limits on every workflow,
  and default values for tool inputs. **Business rules that matter (escalation, refund limit) are enforced in the
  workflow, not left to the model.**
- **Wrong details found by reading the answers.** Keyword scoring misses these:
  - Test 4 added an unrelated "out of stock" sentence. Fix: a pre-check note that sends return questions to
    `order_lookup` + `faq_knowledge` only.
  - Test 6 gave the delivery date one day early (time-zone shift of a DATE column). Fix: dates are returned as text.
  - Test 14 ordered 10 units and said "restocked". Fix: the SQL now never orders fewer units than the rule
    (2 × reorder level − stock, rounded up to 5 → 35 units), and the agent must call it a *draft awaiting approval*.
- **Multi-agent works:** the support agent passed stock questions to the Inventory Agent (12–14), which queried
  the `products` table and drafted a purchase order in `purchase_orders`.

### Business KPIs

From `python3 scripts/kpi_report.py` on the live Supabase database (11 Oct 2026, testing period):

| KPI | Value |
|---|---|
| Conversations handled by the AI | **44** (48 customer messages) |
| Escalated to a human (tickets) | **8** – all high priority, all open |
| Conversations resolved without a human (approx.) | **82 %** |
| Products at or below reorder level | **5** of 12 |
| Purchase orders drafted by the Inventory Agent | **2** (pending approval) |

| Tickets by type | Count |
|---|---|
| refund (high) | 6 |
| delivery (high) | 2 |

| Low-stock SKU | Product | Stock / reorder level |
|---|---|---|
| TSH-BAS-L | Basics Cotton T-shirt (L) | 6 / 20 |
| JNS-RLX-28 | Relaxed Jeans (28) | 0 / 10 |
| KUR-LIN-S | Linen Kurta (S) | 3 / 8 |
| PLZ-COT-S | Cotton Palazzo (S) | 4 / 8 |
| HOD-OVR-XL | Oversized Hoodie (XL) | 9 / 10 |

Orders: 10 worth Rs 30,285 (3 shipped, 2 delivered, 1 delayed, 1 out for delivery, 1 placed, 1 returned,
1 cancelled). The numbers come from repeated testing, not real customers. In live use, the "resolved without a
human" share is the main KPI: about 4 in 5 conversations needed no staff time.

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
