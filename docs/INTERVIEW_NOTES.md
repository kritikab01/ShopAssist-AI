# Interview notes – how to present ShopAssist

## 30-second pitch

> "UrbanThread is a fictional Indian clothing store with two support staff who drown in repetitive questions.
> I built **ShopAssist** in **n8n**: an AI support agent that answers from the store's own data (an FAQ PDF and
> scraped web pages via RAG on Pinecone, plus orders in Postgres), hands stock questions to a **second AI agent**
> for inventory, and makes sure angry customers or big refunds reach a human: ticket, Slack, SMS and e-mail.
> It runs for zero cost on a local model, has a cloud version, 58 automated tests in CI, and a manager dashboard."

## 2-minute demo script (web app)

1. **Chat → `UT1003`**: "Notice it doesn't show the order. It asks for the phone's last 4 digits: privacy first."
2. **`0003`**: verified: status, courier, timeline. "Five wrong tries lock the order for 15 minutes."
3. **`diwali`**: coupon from the scraped offers page, with source. "It never invents codes. That was a real failure I fixed."
4. **`mera order UT1003 kab aayega? last 4 digits 0003`**: Hinglish reply.
5. **`Wow amazing service 🙄 still not here`**: sarcasm → ticket. "A word-level sentiment model would call this positive."
6. **Ops HQ tab**: % solved by AI, CSAT, escalations with sentiment and language, low stock, live order feed.
7. **Approve a purchase order**: "The Inventory Agent drafted it; a human decides; the supplier gets an SMS."

## The story interviewers like most: "what went wrong and how you fixed it"

- **First evaluation: 9 / 14.** The small model *said* "I've escalated" without calling the tool, invented a
  coupon code, and timed out on stock questions.
- Prompt tweaks didn't fix it. **Moving business rules out of the prompt into deterministic workflow steps did**:
  a *Detect Intent* rule step before the agent, a *guaranteed escalation* step after it, a ticket normaliser,
  default tool inputs and time limits. **Result: 14 / 14.**
- **Lesson:** *LLMs decide how to say things; code decides what must happen.* Refund limits, escalation and
  privacy are never left to the model.

## Design decisions (and the trade-off behind each)

| Decision | Why | Trade-off |
|---|---|---|
| n8n instead of Python/LangChain | visual, business users can read it, built-in Slack/Twilio/Postgres nodes | workflow JSON is hard to diff → I **generate** it from Python (`build_workflows.py`) and test it |
| Local Ollama model (qwen2.5 3B) | free, private, no API blocks (Google refused my Gemini keys) | slower, weaker → guardrails; cloud profile with Groq Llama 3.3 70B |
| Two knowledge bases (FAQ vs website) | policies are authoritative, web pages are marketing; the agent chooses (agentic RAG) and cites the source | two retrieval calls for mixed questions |
| Summarise scraped pages before embedding | raw HTML is noisy; summaries keep facts (codes, dates, ₹) and retrieve better | an LLM call per page at ingestion |
| Namespace per knowledge base, cleared on each run | re-ingestion replaces instead of duplicating | a run briefly empties that knowledge base |
| Second agent for inventory (agent-as-a-tool) | separate prompt and tools, customers never see supplier/cost data | an extra model call for stock questions |
| Identity check = last 4 phone digits + lockout | stops "type any order ID and see someone's address" | weaker than an SMS OTP (next step) |
| Approval link = read-only page + POST button | link previews and mail scanners can't approve by accident; token per PO | one extra click |

## Likely questions

**How do you stop hallucinations?** Answers must come from tools (prompt rule), and every answer cites its
source. Coupon questions get a rule note: "only codes from website_knowledge". The evaluation has an AI judge that
flags invented facts, plus a database fact check for order answers.

**How do you know it works?** Three levels. (1) 58 pytest tests in GitHub Actions: workflow structure, the
guardrail code run with Node, every SQL query on a real Postgres. (2) `evaluate.py`: 17 conversations scored by
keywords, live database facts and an AI judge. (3) Business KPIs: % solved without a human (~80–90% in testing),
CSAT from 👍/👎.

**What about security?** Parameterised SQL (a test fails the build otherwise), identity check with lockout,
secret per-PO tokens, an admin key and rate limit on the public app, secrets only in `.env`, and a secret scan in CI.

**How would you scale it?** n8n queue mode with workers, Postgres connection pooling (Supabase pooler), a
hosted model (Groq/OpenAI) instead of a laptop, a scheduled re-scrape, WhatsApp via Twilio, and an SMS OTP.

**What would you do differently?** Start with the evaluation set on day 1; I only learned how often the small
model fakes tool calls once I measured it.

**Where is it deployed?** Three options: `scripts/up.sh` runs everything in Docker on a laptop;
`scripts/share_demo.sh` gives a temporary public https link for a live demo; `render.yaml` + Groq + Cohere +
Supabase is the always-on cloud version (free tiers, sleeps when idle).

## Numbers to remember

7 workflows · 2 agents · 5 tools on the main agent · 2 knowledge bases · 9 database tables · 17 evaluation
conversations (v1: 9/14 → 14/14 after guardrails) · ~10 s average answer on a laptop · 58 automated tests ·
₹0 running cost.
