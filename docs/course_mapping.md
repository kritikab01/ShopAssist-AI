# Course mapping – "Agentic AI for Business Automation"

Where each course session is used in ShopAssist-AI.
Sessions 7–9, 10–13, 14–15, 16–17, 18 and 19–20 follow the course outline. Topics for sessions
**1–6 and 21–24 are my best reading of the outline – adjust the "Topic" column to your syllabus**;
the "Where used" column stays correct.

| Session | Topic | Where used in ShopAssist-AI |
|---------|-------|-----------------------------|
| 1 | Introduction to agentic AI & business automation | Business case (README, report §1–2): repetitive support questions → AI agent + human escalation |
| 2 | n8n basics: workflows, nodes, credentials | All 5 workflows; credentials placeholders; `.env.example` |
| 3 | Triggers (manual, webhook) & data flow / items | Manual triggers (01, 02), Webhook (05), item-per-URL loop (02) |
| 4 | Expressions, Code node, IF / routing | `Split URLs into Items` Code node (02), `Is Delayed?` IF node (05), expressions in all messages |
| 5 | LLMs & prompt engineering | Local LLM with Ollama (`qwen2.5:3b`); `prompts/agent_system_prompt.md`, summarization prompt (02), ticket prompt (04) |
| 6 | LLM chains in n8n | Basic LLM Chain `Summarize Page` (02), `Build Ticket` (04) |
| 7 | Embeddings & vector databases | Ollama `nomic-embed-text` (768 dims), Pinecone index `shopassist` (cosine) |
| 8 | Document loading & chunking | Default Data Loader (PDF, JSON) + Recursive Character Text Splitter 1000/200 (01, 02) |
| 9 | RAG with Pinecone | Pinecone insert (01, 02) and `retrieve-as-tool` (03) |
| 10 | Structured output | Structured Output Parser with `prompts/ticket_schema.json` (04) |
| 11 | JSON schemas / output parsers | Enum fields (`issue_type`, `sentiment`, `priority`) that map to `tickets` columns |
| 12 | AI Agents & tools | Tools Agent with 4 tools (03) |
| 13 | Sub-workflows / multi-agent building blocks | `escalate_to_human` = Call n8n Workflow tool → workflow 04 (Execute Workflow Trigger) |
| 14 | Agentic RAG | Agent chooses which knowledge base to search, or both, per question |
| 15 | Multiple knowledge bases | `faq_knowledge` (PDF) vs `website_knowledge` (scraped pages) in one index |
| 16 | E-mail automation (SMTP) | `Email Support Team (SMTP)` – Gmail SMTP (04) |
| 17 | Public chat interfaces | Chat Trigger in **public hosted chat** mode (03) |
| 18 | Metadata & filtering | `source=faq` / `source=website`, `url`, `title` metadata; metadata filter on each tool |
| 19 | AI agent + SQL database | `order_lookup` Postgres tool, parameterised query, `$fromAI()` (03) |
| 20 | Persistent memory in Postgres | Postgres Chat Memory, table `n8n_chat_histories`, `tickets` table (03, 04) |
| 21 | Slack API & human-in-the-loop | Slack alert to `#support-escalations` (04) |
| 22 | Twilio SMS | SMS to customer on escalation (04) and on delayed orders (05) |
| 23 | Web scraping & summarization | HTTP Request → HTML Extract → LLM summary (02) |
| 24 | Capstone: end-to-end agent | Whole project, testing (`docs/test_questions.md`), report (`docs/report.md`) |

## Capstone line coverage

> "RAG with Pinecone, Scrapping web-pages and summarization, Send SMS using Twilio, Slack API"

| Capstone item | Workflow / node |
|---------------|-----------------|
| RAG with Pinecone | 01, 02 (insert) and 03 (`faq_knowledge`, `website_knowledge`) |
| Scraping web pages & summarization | 02 (`Fetch Page HTML`, `Extract Text from HTML`, `Summarize Page (LLM)`) |
| Send SMS using Twilio | 04 (`SMS Customer`), 05 (`SMS Delay Notice`) |
| Slack API | 04 (`Alert Slack #support-escalations`) |
