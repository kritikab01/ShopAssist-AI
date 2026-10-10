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
5. Build it in n8n in 4–5 hours, using every topic of the course.

## 3. Architecture

_(Paste the Mermaid diagram from the README here, or a screenshot of it rendered on GitHub.)_

| Layer | Technology |
|-------|-----------|
| Orchestration / agent | n8n Cloud – AI Agent (Tools Agent) |
| LLM | OpenAI gpt-4o-mini |
| Embeddings | OpenAI text-embedding-3-small (1536 dims) |
| Vector DB | Pinecone index `shopassist` (cosine), metadata `source`, `url`, `title` |
| Database + memory | Supabase Postgres (`orders`, `tickets`, `n8n_chat_histories`) |
| Notifications | Slack API, Twilio SMS, Gmail SMTP |
| Interface | n8n public hosted chat; webhook for the order system |

## 4. Workflow-by-workflow explanation

### 4.1 Workflow 01 – Ingest FAQ PDF
Manual trigger → HTTP Request downloads `store_faq.pdf` → **Default Data Loader** (PDF) with metadata
`source=faq` → **Recursive Character Text Splitter** (chunk 1000, overlap 200) → **OpenAI embeddings** →
**Pinecone insert**. Overlap keeps sentences that cross chunk borders searchable.
_Screenshot: workflow canvas + Pinecone record count._

### 4.2 Workflow 02 – Scrape and summarize web pages
Manual trigger → read `urls.txt` → **Code** node creates one item per URL → **HTTP Request** fetches each
page → **HTML Extract** keeps body text without nav/footer → **Basic LLM Chain** (gpt-4o-mini,
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
(`issue_type`, `sentiment`, `priority` are enums) → **Postgres insert** into `tickets` (returns
`TKT-000N`) → **Slack** message to `#support-escalations` → **Twilio SMS** to the customer →
**SMTP e-mail** to support → **Set** node returns the ticket ID to the agent. Notification nodes continue
on error so a missing phone number never breaks the chat.
_Screenshots: Slack alert, SMS on phone, e-mail, `tickets` row._

### 4.5 Workflow 05 – Order-update webhook
**Webhook** `POST /webhook/order-update` with `order_id`, `status` (and optional
`new_expected_delivery`) → **Postgres UPDATE** → **IF** status = `delayed` → **Twilio SMS** to the customer
→ **Respond to Webhook** with JSON (`ok: false` for unknown orders).
_Screenshot: curl/Postman request and response + SMS._

## 5. Course mapping

See `docs/course_mapping.md` for the full session-by-session table. Summary of the capstone line:

| Capstone requirement | Implemented in |
|----------------------|----------------|
| RAG with Pinecone | Workflows 01, 02, 03 |
| Scraping web pages and summarization | Workflow 02 |
| Send SMS using Twilio | Workflows 04, 05 |
| Slack API | Workflow 04 |

## 6. Results

Test plan: `docs/test_questions.md` (8 chat tests + 2 webhook tests).

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
| W1 | Webhook delayed UT1002 | DB updated + SMS | | |
| W2 | Webhook unknown order | `ok: false` | | |

**Screenshots** (add to `docs/screenshots/` and link here):

- [ ] Fig 1 – Workflow 01 canvas · [ ] Fig 2 – Workflow 02 canvas and a summary
- [ ] Fig 3 – Workflow 03 canvas · [ ] Fig 4 – Public chat conversation (tests 1–4)
- [ ] Fig 5 – Escalation: chat reply with ticket ID · [ ] Fig 6 – Slack alert
- [ ] Fig 7 – SMS received · [ ] Fig 8 – Escalation e-mail · [ ] Fig 9 – `tickets` table in Supabase
- [ ] Fig 10 – Webhook test response · [ ] Fig 11 – Pinecone index with metadata

**Observations:** _(e.g. average response time, number of tool calls per question, any wrong answers and why)._

## 7. Limitations

- Fictional data and small knowledge base (1 PDF, 4 pages); real stores need regular re-ingestion.
- Re-running ingestion creates duplicate vectors (no upsert by document ID).
- Public chat has no login: anyone who knows an order ID can see its status (production needs OTP verification).
- Sentiment / anger detection depends on the LLM and may miss sarcasm or Hinglish.
- Twilio trial sends only to verified numbers and adds a trial prefix to messages.
- No evaluation dataset or automated accuracy measurement; testing is manual.
- English only.

## 8. Future scope

1. **Inventory agent + supervisor (multi-agent):** a supervisor agent routes each message to the support
   agent or a new inventory agent that checks stock in Postgres, drafts a purchase order (structured
   output), asks for approval in Slack, then texts the supplier via Twilio.
2. **Flowise version:** rebuild the same agent in Flowise to compare low-code agent builders.
3. **Local model with Ollama:** run Llama/Qwen locally for privacy and zero API cost; compare quality and latency against gpt-4o-mini.
4. WhatsApp channel via Twilio WhatsApp API; Hindi and Hinglish support.
5. OTP verification before showing order details; automatic re-scraping on a schedule.
6. Dashboard of ticket volume, sentiment and resolution time.

## 9. Conclusion

ShopAssist shows how an n8n AI agent can combine two RAG knowledge bases, a SQL database and a
human-in-the-loop escalation path to automate routine customer support while making sure urgent and
high-value cases reach a person quickly through Slack, SMS and e-mail.
