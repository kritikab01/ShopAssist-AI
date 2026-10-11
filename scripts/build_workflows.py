"""Generate the five n8n workflow JSON files in workflows/.

Why a generator? It keeps the agent system prompt (prompts/agent_system_prompt.md) and the
ticket JSON schema (prompts/ticket_schema.json) in ONE place, and guarantees every workflow
file is valid JSON with correct node connections.

Usage:  python scripts/build_workflows.py
You do NOT need to run this to use the project - the generated files are committed.
"""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "workflows"

# Change this if your GitHub user / repo / branch is different (repo must be public).
RAW_BASE = "https://raw.githubusercontent.com/kritikab01/ShopAssist-AI/main"

PINECONE_INDEX = "shopassist"
# Local, free AI with Ollama (https://ollama.com) - no API key, runs on your own computer.
#   ollama pull qwen2.5:3b        (chat + tool calling, ~2 GB; with 16 GB RAM you can use qwen2.5:7b)
#   ollama pull nomic-embed-text  (embeddings, 768 dimensions)
CHAT_MODEL = "qwen2.5:3b"
EMBED_MODEL = "nomic-embed-text"  # 768-dim vectors -> Pinecone index must be dimension 768
NUM_CTX = 8192  # Ollama's default context (2048 tokens) is too small for the agent prompt + search results

# Placeholder credentials: after import, open each node and pick your own credential.
CRED = {
    "ollamaApi": {"id": "REPLACE_ME_ollama", "name": "Ollama account"},
    "pineconeApi": {"id": "REPLACE_ME_pinecone", "name": "Pinecone account"},
    "postgres": {"id": "REPLACE_ME_postgres", "name": "Supabase Postgres"},
    "slackApi": {"id": "REPLACE_ME_slack", "name": "Slack account"},
    "twilioApi": {"id": "REPLACE_ME_twilio", "name": "Twilio account"},
    "smtp": {"id": "REPLACE_ME_smtp", "name": "Gmail SMTP"},
}
TWILIO_FROM = "+10000000000"  # placeholder: replace with your Twilio phone number in n8n
SUPPORT_EMAIL = "support@urbanthread.example"  # placeholder: replace with your own inbox
SENDER_EMAIL = "your.gmail@gmail.com"  # placeholder: the Gmail account used in SMTP credential


# ---------------------------------------------------------------- helpers
class WF:
    """Tiny builder for an n8n workflow (nodes + connections)."""

    def __init__(self, name, timeout=None):
        # timeout (seconds): n8n stops a run that takes longer, so a stuck agent can never keep
        # the local model busy and block every other question.
        self.name, self.nodes, self.connections, self.timeout = name, [], {}, timeout

    def node(self, name, type_, version, pos, params=None, creds=None, **extra):
        n = {
            "parameters": params or {},
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.name}/{name}")),
            "name": name,
            "type": type_,
            "typeVersion": version,
            "position": list(pos),
        }
        if creds:
            n["credentials"] = {c: CRED[c] for c in creds}
        n.update(extra)
        self.nodes.append(n)
        return name

    def sticky(self, title, content, pos, w=360, h=260, color=None):
        p = {"content": f"## {title}\n{content}", "width": w, "height": h}
        if color:
            p["color"] = color
        return self.node(title, "n8n-nodes-base.stickyNote", 1, pos, p)

    def link(self, src, dst, kind="main", out_index=0):
        outs = self.connections.setdefault(src, {}).setdefault(kind, [])
        while len(outs) <= out_index:
            outs.append([])
        outs[out_index].append({"node": dst, "type": kind, "index": 0})

    def save(self, filename):
        data = {
            "name": self.name,
            "nodes": self.nodes,
            "connections": self.connections,
            "pinData": {},
            "settings": {"executionOrder": "v1", **({"executionTimeout": self.timeout} if self.timeout else {})},
            "active": False,
            "tags": [],
        }
        path = OUT_DIR / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.relative_to(ROOT))


def rl(value, mode="list"):
    """n8n 'resource locator' value (used for models, Pinecone index, Slack channel...)."""
    return {"__rl": True, "value": value, "mode": mode}


def ollama_chat(wf, name, pos, temperature=0.2, json_mode=False):
    options = {"temperature": temperature, "numCtx": NUM_CTX,
               "think": False}  # qwen2.5 is not a "thinking" model; n8n's default (true) can be rejected
    if json_mode:
        options["format"] = "json"  # forces valid JSON output (used for the structured ticket)
    return wf.node(name, "@n8n/n8n-nodes-langchain.lmChatOllama", 1, pos,
                   {"model": CHAT_MODEL, "options": options}, ["ollamaApi"])


def ollama_embeddings(wf, name, pos):
    return wf.node(name, "@n8n/n8n-nodes-langchain.embeddingsOllama", 1, pos,
                   {"model": EMBED_MODEL}, ["ollamaApi"])


def text_splitter(wf, name, pos):
    return wf.node(name, "@n8n/n8n-nodes-langchain.textSplitterRecursiveCharacterTextSplitter",
                   1, pos, {"chunkSize": 1000, "chunkOverlap": 200, "options": {}})


def pinecone_insert(wf, name, pos):
    return wf.node(name, "@n8n/n8n-nodes-langchain.vectorStorePinecone", 1.3, pos,
                   {"mode": "insert", "pineconeIndex": rl(PINECONE_INDEX), "options": {}},
                   ["pineconeApi"])


def workflow_tool(wf, name, pos, description, placeholder_id, fields):
    """An AI-agent tool that runs another n8n workflow (sub-workflow / sub-agent)."""
    return wf.node(name, "@n8n/n8n-nodes-langchain.toolWorkflow", 2, pos, {
        "name": name,  # required tool name in v2 (letters, numbers, underscores)
        "description": description,
        "workflowId": rl(placeholder_id, "id"),  # scripts/import_to_n8n.py fills in the real ID
        "workflowInputs": {
            "mappingMode": "defineBelow",
            "value": {k: f"={{{{ $fromAI('{k}', '{v}', 'string') }}}}" for k, v in fields.items()},
            "matchingColumns": [],
            "schema": [
                {"id": k, "displayName": k, "required": False, "defaultMatch": False,
                 "display": True, "canBeUsedToMatch": True, "type": "string", "removed": False}
                for k in fields
            ],
            "attemptToConvertTypes": False,
            "convertFieldsToString": False,
        },
    })


def metadata(*pairs):
    return {"metadataValues": [{"name": k, "value": v} for k, v in pairs]}


# ---------------------------------------------------------------- 01 ingest FAQ PDF
def wf01():
    wf = WF("01 Ingest FAQ PDF into Pinecone", timeout=900)
    wf.sticky("Overview – Workflow 01",
              "**Goal:** load the store FAQ/policy PDF into the Pinecone index `shopassist` "
              "so the agent can search it (RAG).\n\n"
              "Flow: Manual trigger → download PDF → split into 1000-char chunks (200 overlap) → "
              "embed with Ollama `nomic-embed-text` (768 dims) → insert with metadata `source = faq`.\n\n"
              "**Run once** (running again adds duplicates – clear the index first).\n\n"
              "Course: Sessions 7–9 (RAG with Pinecone), 18 (metadata).",
              (-80, -360), w=520, h=300, color=4)
    t = wf.node("Start Ingestion", "n8n-nodes-base.manualTrigger", 1, (0, 0))
    dl = wf.node("Download FAQ PDF", "n8n-nodes-base.httpRequest", 4.2, (220, 0), {
        "url": f"{RAW_BASE}/data/store_faq.pdf",
        "options": {"response": {"response": {"responseFormat": "file"}}},
    })
    # GitHub serves every raw file as "application/octet-stream", but the PDF loader only
    # accepts "application/pdf" ("Mime type doesn't match selected loader"). Fix the label.
    mime = wf.node("Set MIME Type to PDF", "n8n-nodes-base.code", 2, (440, 0), {
        "jsCode": (
            "// raw.githubusercontent.com sends the PDF as application/octet-stream.\n"
            "// The Default Data Loader (PDF) needs application/pdf, so we relabel it.\n"
            "for (const item of $input.all()) {\n"
            "  item.binary.data.mimeType = 'application/pdf';\n"
            "  item.binary.data.fileExtension = 'pdf';\n"
            "}\n"
            "return $input.all();\n"
        ),
    })
    pc = pinecone_insert(wf, "Insert into Pinecone (source=faq)", (680, 0))
    emb = ollama_embeddings(wf, "Ollama Embeddings", (600, 240))
    loader = wf.node("Default Data Loader (PDF)", "@n8n/n8n-nodes-langchain.documentDefaultDataLoader",
                     1.1, (800, 240), {
                         "dataType": "binary",
                         "loader": "pdfLoader",
                         "textSplittingMode": "custom",
                         "options": {"metadata": metadata(("source", "faq"),
                                                          ("file", "store_faq.pdf"))},
                     })
    split = text_splitter(wf, "Recursive Text Splitter 1000/200", (880, 440))
    wf.sticky("Step notes",
              "- **Download FAQ PDF**: raw GitHub URL of `data/store_faq.pdf` (repo must be public). "
              "Alternative: replace with a *Google Drive → Download file* node.\n"
              "- **Set MIME Type to PDF**: GitHub labels the file `application/octet-stream`; the PDF "
              "loader needs `application/pdf`.\n"
              "- **Default Data Loader** reads the binary PDF and adds metadata `source=faq` – "
              "the agent's `faq_knowledge` tool filters on it.\n"
              "- **Recursive Text Splitter**: chunk size 1000, overlap 200.\n"
              "- **Ollama Embeddings**: `nomic-embed-text`, 768-dim vectors; index must use the same dimension and cosine.",
              (1080, -40), w=420, h=360)
    wf.link(t, dl)
    wf.link(dl, mime)
    wf.link(mime, pc)
    wf.link(emb, pc, "ai_embedding")
    wf.link(loader, pc, "ai_document")
    wf.link(split, loader, "ai_textSplitter")
    wf.save("01_ingest_faq_pdf.json")


# ---------------------------------------------------------------- 02 scrape + summarize
def wf02():
    wf = WF("02 Scrape Web Pages, Summarize and Store", timeout=1200)
    wf.sticky("Overview – Workflow 02",
              "**Goal:** scrape store web pages, summarize each with the LLM, and store the summaries "
              "in Pinecone with metadata `source = website` and `url`.\n\n"
              "Flow: read `data/urls.txt` → one item per URL → HTTP GET page → extract text from HTML → "
              "LLM summary → embed → Pinecone insert.\n\n"
              "Course: Capstone (web scraping + summarization), Sessions 5–6 (LLM chains), "
              "7–9 & 18 (Pinecone + metadata), 14–15 (second knowledge base).",
              (-80, -380), w=560, h=320, color=4)
    t = wf.node("Start Scraping", "n8n-nodes-base.manualTrigger", 1, (0, 0))
    urls = wf.node("Read urls.txt", "n8n-nodes-base.httpRequest", 4.2, (200, 0), {
        "url": f"{RAW_BASE}/data/urls.txt",
        "options": {"response": {"response": {"responseFormat": "text", "outputPropertyName": "data"}}},
    })
    split = wf.node("Split URLs into Items", "n8n-nodes-base.code", 2, (400, 0), {
        "jsCode": (
            "// urls.txt has one URL per line. Turn it into one n8n item per URL.\n"
            "const text = $input.first().json.data || '';\n"
            "return text\n"
            "  .split('\\n')\n"
            "  .map(line => line.trim())\n"
            "  .filter(line => line.startsWith('http'))\n"
            "  .map(url => ({ json: { url } }));\n"
        ),
    })
    fetch = wf.node("Fetch Page HTML", "n8n-nodes-base.httpRequest", 4.2, (600, 0), {
        "url": "={{ $json.url }}",
        "options": {"response": {"response": {"responseFormat": "text", "outputPropertyName": "data"}}},
    })
    extract = wf.node("Extract Text from HTML", "n8n-nodes-base.html", 1.2, (800, 0), {
        "operation": "extractHtmlContent",
        "dataPropertyName": "data",
        "extractionValues": {"values": [
            {"key": "title", "cssSelector": "title"},
            {"key": "content", "cssSelector": "body",
             "skipSelectors": "nav,header,footer,script,style"},
        ]},
        "options": {"trimValues": True, "cleanUpText": False},  # True glues lines together ("yourPIN")
    })
    summ = wf.node("Summarize Page (LLM)", "@n8n/n8n-nodes-langchain.chainLlm", 1.5, (1000, 0), {
        "promptType": "define",
        "text": (
            "=Summarize this web page of the online clothing store UrbanThread for a customer-support "
            "knowledge base. Keep ALL concrete facts: numbers, prices in Rs, dates, coupon codes, "
            "time limits and conditions. Use short bullet points, max 200 words. "
            "Do not add anything that is not in the page.\n\n"
            "Page title: {{ $json.title }}\n\nPage text:\n{{ $json.content }}"
        ),
    })
    llm = ollama_chat(wf, "Ollama Chat Model", (1000, 220), temperature=0)
    prep = wf.node("Prepare Document", "n8n-nodes-base.set", 3.4, (1240, 0), {
        "assignments": {"assignments": [
            {"id": "a1", "name": "url", "type": "string",
             "value": "={{ $('Split URLs into Items').item.json.url }}"},
            {"id": "a2", "name": "title", "type": "string",
             "value": "={{ $('Extract Text from HTML').item.json.title }}"},
            {"id": "a3", "name": "summary", "type": "string", "value": "={{ $json.text }}"},
        ]},
        "options": {},
    })
    pc = pinecone_insert(wf, "Insert into Pinecone (source=website)", (1480, 0))
    emb = ollama_embeddings(wf, "Ollama Embeddings", (1400, 240))
    loader = wf.node("Default Data Loader (summary)", "@n8n/n8n-nodes-langchain.documentDefaultDataLoader",
                     1.1, (1600, 240), {
                         "dataType": "json",
                         "jsonMode": "expressionData",
                         "jsonData": "=Page: {{ $json.title }}\nURL: {{ $json.url }}\n\n{{ $json.summary }}",
                         "textSplittingMode": "custom",
                         "options": {"metadata": metadata(("source", "website"),
                                                          ("url", "={{ $json.url }}"),
                                                          ("title", "={{ $json.title }}"))},
                     })
    tsplit = text_splitter(wf, "Recursive Text Splitter 1000/200", (1680, 440))
    wf.sticky("Step notes",
              "- **Read urls.txt** downloads the URL list from GitHub (one URL per line).\n"
              "- **Fetch Page HTML** runs once per URL (n8n loops over items automatically).\n"
              "- **Extract Text from HTML** keeps `<body>` text and skips nav/header/footer.\n"
              "- **Summarize Page** = Basic LLM Chain + Ollama `qwen2.5:3b` (temperature 0).\n"
              "- **Default Data Loader** stores the summary with metadata `source=website`, `url`, "
              "`title` so the agent can cite the page.",
              (1880, -40), w=440, h=320)
    for a, b in [(t, urls), (urls, split), (split, fetch), (fetch, extract),
                 (extract, summ), (summ, prep), (prep, pc)]:
        wf.link(a, b)
    wf.link(llm, summ, "ai_languageModel")
    wf.link(emb, pc, "ai_embedding")
    wf.link(loader, pc, "ai_document")
    wf.link(tsplit, loader, "ai_textSplitter")
    wf.save("02_scrape_and_summarize.json")


# ---------------------------------------------------------------- 03 support agent
def wf03():
    wf = WF("03 ShopAssist Support Agent (Chat)", timeout=240)
    system_prompt = (ROOT / "prompts" / "agent_system_prompt.md").read_text(encoding="utf-8").strip()

    wf.sticky("Overview – Workflow 03",
              "**Goal:** the customer-facing AI agent on a **public chat URL**.\n\n"
              "The Tools Agent decides which tool to call:\n"
              "- `faq_knowledge` – Pinecone, filter `source=faq`\n"
              "- `website_knowledge` – Pinecone, filter `source=website`\n"
              "- `order_lookup` – Postgres query by order ID or phone\n"
              "- `escalate_to_human` – calls workflow 04 (Slack + SMS + e-mail)\n"
              "- `inventory_expert` – asks the **Inventory Agent** (workflow 06) – multi-agent\n\n"
              "Memory: Postgres Chat Memory (table `n8n_chat_histories`, last 10 messages).\n\n"
              "Course: 1–4 (agents, n8n basics), 7–9 & 18 (RAG + metadata filter), 12–13 (sub-workflow tool), "
              "14–15 (agentic RAG, two knowledge bases), 16–17 (public chat), 19–20 (agent + Postgres).",
              (-120, -460), w=600, h=400, color=4)
    chat = wf.node("Public Chat (UrbanThread)", "@n8n/n8n-nodes-langchain.chatTrigger", 1.1, (0, 0), {
        "public": True,
        "mode": "hostedChat",
        "initialMessages": (
            "Hi! I'm ShopAssist from UrbanThread 👕\n"
            "Ask me about orders, returns, sizes, delivery or offers."
        ),
        "options": {
            "title": "UrbanThread ShopAssist",
            "subtitle": "AI support – a human can take over anytime",
            "inputPlaceholder": "e.g. Where is my order UT1003?",
        },
    }, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "shopassist-chat")))
    agent = wf.node("ShopAssist AI Agent", "@n8n/n8n-nodes-langchain.agent", 1.7, (360, 0), {
        "agent": "toolsAgent",
        "promptType": "auto",
        "options": {"systemMessage": "=" + system_prompt, "maxIterations": 8},
    })
    llm = ollama_chat(wf, "Ollama Chat Model", (0, 300))
    mem = wf.node("Postgres Chat Memory", "@n8n/n8n-nodes-langchain.memoryPostgresChat", 1.3, (180, 300), {
        "tableName": "n8n_chat_histories",
        "contextWindowLength": 10,
    }, ["postgres"])

    def kb_tool(name, source, desc, x):
        node = wf.node(name, "@n8n/n8n-nodes-langchain.vectorStorePinecone", 1.3, (x, 300), {
            "mode": "retrieve-as-tool",
            "toolName": name,
            "toolDescription": desc,
            "pineconeIndex": rl(PINECONE_INDEX),
            "topK": 4,
            "includeDocumentMetadata": True,
            "options": {"metadata": metadata(("source", source))},
        }, ["pineconeApi"])
        emb = ollama_embeddings(wf, f"Ollama Embeddings ({source})", (x, 520))
        wf.link(emb, node, "ai_embedding")
        wf.link(node, agent, "ai_tool")

    kb_tool("faq_knowledge", "faq",
            "Search the official UrbanThread store FAQ and policies: returns (15 days), refunds, "
            "exchanges, sizes, delivery times and charges, COD, payments, cancellations.", 360)
    kb_tool("website_knowledge", "website",
            "Search summaries of UrbanThread web pages: courier partners, dispatch times, festive/Diwali "
            "delays, size and fit tips, offers and coupon codes, gift cards, loyalty points, garment care, "
            "sustainability.", 560)

    orders = wf.node("order_lookup", "n8n-nodes-base.postgresTool", 2.5, (760, 300), {
        "descriptionType": "manual",
        "toolDescription": (
            "Look up a customer's order in the database. Input: exactly ONE order ID (like UT1003) "
            "or ONE phone number (like +919000000003 or 9000000003). Returns status, items, amount in Rs, "
            "payment method, expected delivery date, courier and tracking number."
        ),
        "operation": "executeQuery",
        "query": (
            "-- $1 = order ID or phone number provided by the customer\n"
            "SELECT order_id, customer_name, items, amount_inr, payment_method, status, city,\n"
            "       order_date, expected_delivery, courier, tracking_no\n"
            "FROM orders\n"
            "WHERE order_id = UPPER(TRIM($1))\n"
            "   OR RIGHT(phone, 10) = RIGHT(REGEXP_REPLACE($1, '[^0-9]', '', 'g'), 10)\n"
            "LIMIT 5;"
        ),
        "options": {
            "queryReplacement": (
                "={{ $fromAI('order_id_or_phone', 'The order ID (e.g. UT1003) or phone number "
                "given by the customer', 'string') }}"
            ),
        },
    }, ["postgres"])
    wf.link(orders, agent, "ai_tool")

    fields = {
        "customer_name": "Customer name, or Unknown",
        "phone": "Customer phone number, or empty string",
        "order_id": "Order ID like UT1003, or empty string",
        "reason": "Why you are escalating: angry customer, refund over Rs 5,000, no answer found, or human requested",
        "conversation_summary": "Short summary of the conversation and the exact problem of the customer",
    }
    esc = workflow_tool(wf, "escalate_to_human", (960, 300), (
        "Create a support ticket and alert the human support team (Slack, SMS, e-mail). Use when the "
        "customer is angry, wants a refund above Rs 5,000, asks for a human, or the answer is not in "
        "the knowledge bases. Returns the ticket ID to give to the customer."
    ), "REPLACE_WITH_WORKFLOW_04_ID", fields)
    wf.link(esc, agent, "ai_tool")

    # Multi-agent: a second domain expert (workflow 06) is available to this agent as a tool.
    inv = workflow_tool(wf, "inventory_expert", (1160, 300), (
        "Ask the Inventory Agent (domain expert for stock and procurement). Use for product availability, "
        "sizes in stock, low stock, restocking and purchase orders. Send the full question; it returns the answer."
    ), "REPLACE_WITH_WORKFLOW_06_ID", {"question": "The full question about stock, availability, restocking or purchase orders"})
    wf.link(inv, agent, "ai_tool")

    # Small local models follow an explicit note far better than a long system prompt. This step spots clear
    # signals (anger / wants a human, refund, out-of-scope) and adds a short instruction to the message.
    guard = wf.node("Detect Intent (rules)", "n8n-nodes-base.code", 2, (180, 0), {
        "jsCode": (
            "// Rule-based pre-check: adds a NOTE for the agent when the message clearly needs a special action.\n"
            "const msg = String($json.chatInput || '');\n"
            "const m = msg.toLowerCase();\n"
            "const notes = [];\n"
            "if (/manager|human|real person|complain|worst|third time|angry|furious|ridiculous|fed up|cheat|fraud/.test(m))\n"
            "  notes.push('The customer is upset or asks for a human: look up the order if an order ID is given, then you MUST call escalate_to_human and give the ticket ID.');\n"
            "if (/refund/.test(m) && /ut\\d{4}/.test(m))\n"
            "  notes.push('Refund request: call order_lookup; if the order amount is more than Rs 5000 you MUST call escalate_to_human (you cannot approve it) and give the ticket ID.');\n"
            "if (/\\b(stock|in stock|available|availability|restock|reorder|purchase order|inventory|low stock)\\b/.test(m) && !/stock market/.test(m))\n"
            "  notes.push('This is about stock or purchase orders: call inventory_expert with the full question and pass its answer on. Do not guess availability.');\n"
            "if (/python|javascript|java |code|script|program|homework|essay|poem|recipe|weather|cricket|movie|stock market|bitcoin/.test(m)\n"
            "    && !/order|ut\\d{4}|return|refund|size|deliver|kurta|shirt|jeans|hoodie|in stock|restock|low stock/.test(m))\n"
            "  notes.push('This is NOT about UrbanThread. Do not answer it and do not write code: reply that you can only help with UrbanThread orders, returns, sizes, delivery, offers and stock.');\n"
            "return [{ json: { ...$json, chatInput: notes.length ? msg + '\\n\\n[NOTE FOR ASSISTANT: ' + notes.join(' ') + ']' : msg } }];\n"
        ),
    })
    wf.link(chat, guard)
    wf.link(guard, agent)
    wf.link(llm, agent, "ai_languageModel")
    wf.link(mem, agent, "ai_memory")
    wf.sticky("Setup notes",
              "1. Import workflow 04 first, copy its ID from the URL, and select it in **escalate_to_human**.\n"
              "2. Set credentials on every node with a ⚠ warning.\n"
              "3. **Activate** the workflow, open the Chat Trigger and copy the **public chat URL**.\n"
              "4. The system prompt lives in `prompts/agent_system_prompt.md` (rules: answer only from "
              "tools, cite source, ask for order ID, escalate if angry / refund > Rs 5,000 / no answer).",
              (1380, -40), w=420, h=300)
    wf.save("03_support_agent_chat.json")


# ---------------------------------------------------------------- 04 escalation sub-workflow
def wf04():
    wf = WF("04 Escalation Sub-workflow (Ticket + Slack + SMS + Email)", timeout=150)
    schema = (ROOT / "prompts" / "ticket_schema.json").read_text(encoding="utf-8")
    wf.sticky("Overview – Workflow 04",
              "**Called by** the `escalate_to_human` tool in workflow 03.\n\n"
              "Flow: inputs → LLM + **Structured Output Parser** builds a ticket JSON "
              "(schema in `prompts/ticket_schema.json`) → insert into `tickets` → Slack alert to "
              "`#support-escalations` → Twilio SMS to customer → SMTP e-mail to support → "
              "return the ticket ID to the agent.\n\n"
              "Slack/SMS/e-mail nodes are set to *continue on error* so a missing phone number "
              "does not break the chat.\n\n"
              "Course: 10–13 (structured output, sub-workflows), 16–17 (SMTP e-mail), 19–20 (Postgres), "
              "21–22 & capstone (Slack API, Twilio SMS).",
              (-120, -440), w=600, h=380, color=4)
    trig = wf.node("When Called by Agent", "n8n-nodes-base.executeWorkflowTrigger", 1.1, (0, 0), {
        "inputSource": "workflowInputs",
        "workflowInputs": {"values": [{"name": n} for n in
                                      ["customer_name", "phone", "order_id", "reason",
                                       "conversation_summary"]]},
    })
    build = wf.node("Build Ticket (Structured Output)", "@n8n/n8n-nodes-langchain.chainLlm", 1.5,
                    (220, 0), {
                        "promptType": "define",
                        "text": (
                            "=You are a support team lead at UrbanThread (Indian online clothing store). "
                            "Create a support ticket from this escalation. Phone numbers must be in E.164 "
                            "format: if a 10-digit Indian number is given, add +91. Priority is high if the "
                            "customer is angry, the refund is above Rs 5,000, the item is damaged or there is a "
                            "payment problem.\n\n"
                            "Customer name: {{ $json.customer_name }}\n"
                            "Phone: {{ $json.phone }}\n"
                            "Order ID: {{ $json.order_id }}\n"
                            "Reason for escalation: {{ $json.reason }}\n"
                            "Conversation summary: {{ $json.conversation_summary }}\n\n"
                            "Answer with ONLY this JSON shape (fill every field): {\"output\": {\"customer_name\": \"...\", "
                            "\"phone\": \"...\", \"order_id\": \"...\", \"issue_type\": \"refund|return|delivery|damaged_item|payment|size|other\", "
                            "\"sentiment\": \"positive|neutral|negative|angry\", \"priority\": \"low|medium|high\", "
                            "\"summary\": \"...\", \"suggested_action\": \"...\"}}"
                        ),
                        "hasOutputParser": True,
                    }, onError="continueRegularOutput")  # bad JSON -> "Normalize Ticket" still builds a ticket
    llm = ollama_chat(wf, "Ollama Chat Model", (160, 240), temperature=0, json_mode=True)
    parser = wf.node("Ticket JSON Schema", "@n8n/n8n-nodes-langchain.outputParserStructured", 1.2,
                     (360, 240), {"schemaType": "manual", "inputSchema": schema})
    # Small local models sometimes skip a field or the {"output": ...} wrapper. This step fills any gap
    # from the agent's inputs, so a ticket is ALWAYS saved and the customer always gets a ticket ID.
    norm = wf.node("Normalize Ticket (fallback)", "n8n-nodes-base.code", 2, (440, 0), {
        "jsCode": (
            "// Take the AI ticket; fill anything missing from what the agent sent, and make every value\n"
            "// fit the database (allowed words + column lengths), so saving the ticket can never fail.\n"
            "const t = $json.output || {};\n"
            "const inp = $('When Called by Agent').first().json;\n"
            "const text = (String(inp.reason || '') + ' ' + String(inp.conversation_summary || '')).toLowerCase();\n"
            "const pick = (v, allowed, dflt) => { v = String(v || '').toLowerCase().trim();\n"
            "  return allowed.includes(v) ? v : (allowed.find(a => v.includes(a)) || dflt); };\n"
            "let phone = String(t.phone || inp.phone || '').replace(/[^0-9+]/g, '');\n"
            "if (/^[0-9]{10}$/.test(phone)) phone = '+91' + phone;  // Indian 10-digit number -> E.164\n"
            "const oid = (String(t.order_id || '') + ' ' + String(inp.order_id || '') + ' ' + text).toUpperCase().match(/UT\\d{4}/);\n"
            "const issueGuess = text.includes('refund') ? 'refund' : text.includes('late') || text.includes('delay') ? 'delivery' : 'other';\n"
            "const angry = /angry|manager|worst|third time|furious|complain/.test(text);\n"
            "return [{ json: { output: {\n"
            "  customer_name: String(t.customer_name || inp.customer_name || 'Unknown').slice(0, 100),\n"
            "  phone: phone.slice(0, 20),\n"
            "  order_id: oid ? oid[0] : '',\n"
            "  issue_type: pick(t.issue_type, ['refund', 'return', 'delivery', 'damaged_item', 'payment', 'size', 'other'], issueGuess),\n"
            "  sentiment: pick(t.sentiment, ['positive', 'neutral', 'negative', 'angry'], angry ? 'angry' : 'negative'),\n"
            "  priority: pick(t.priority, ['low', 'medium', 'high'], 'high'),\n"
            "  summary: String(t.summary || inp.conversation_summary || inp.reason || '').slice(0, 2000),\n"
            "  suggested_action: String(t.suggested_action || 'Contact the customer and review the chat.').slice(0, 1000),\n"
            "} } }];\n"
        ),
    })
    T = "$('Normalize Ticket (fallback)').item.json.output"
    save = wf.node("Save Ticket in Postgres", "n8n-nodes-base.postgres", 2.5, (660, 0), {
        "operation": "executeQuery",
        "query": (
            "INSERT INTO tickets (customer_name, phone, order_id, issue_type, sentiment, priority,\n"
            "                     summary, suggested_action)\n"
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)\n"
            "RETURNING ticket_id, priority, created_at;"
        ),
        "options": {"queryReplacement": (
            "={{ [ $json.output.customer_name, $json.output.phone, $json.output.order_id, "
            "$json.output.issue_type, $json.output.sentiment, $json.output.priority, "
            "$json.output.summary, $json.output.suggested_action ] }}"
        )},
    }, ["postgres"])
    slack = wf.node("Alert Slack #support-escalations", "n8n-nodes-base.slack", 2.3, (880, 0), {
        "select": "channel",
        "channelId": rl("#support-escalations", "name"),
        "text": (
            "=:rotating_light: *New escalation {{ $json.ticket_id }}* – priority *{{ " + T + ".priority }}*\n"
            "*Customer:* {{ " + T + ".customer_name }} ({{ " + T + ".phone || 'no phone' }})\n"
            "*Order:* {{ " + T + ".order_id || '-' }}  |  *Issue:* {{ " + T + ".issue_type }}  |  "
            "*Sentiment:* {{ " + T + ".sentiment }}\n"
            "*Summary:* {{ " + T + ".summary }}\n"
            "*Suggested action:* {{ " + T + ".suggested_action }}"
        ),
        "otherOptions": {},
    }, ["slackApi"], onError="continueRegularOutput")
    sms = wf.node("SMS Customer (Twilio)", "n8n-nodes-base.twilio", 1, (1100, 0), {
        "from": TWILIO_FROM,
        "to": "={{ " + T + ".phone }}",
        "message": (
            "=Hi {{ " + T + ".customer_name }}, this is UrbanThread support. We have created ticket "
            "{{ $('Save Ticket in Postgres').item.json.ticket_id }} for your issue. A team member will "
            "contact you within 4 business hours."
        ),
        "options": {},
    }, ["twilioApi"], onError="continueRegularOutput")
    mail = wf.node("Email Support Team (SMTP)", "n8n-nodes-base.emailSend", 2.1, (1320, 0), {
        "fromEmail": SENDER_EMAIL,
        "toEmail": SUPPORT_EMAIL,
        "subject": (
            "=[{{ " + T + ".priority }}] Escalation {{ $('Save Ticket in Postgres').item.json.ticket_id }}"
            " – {{ " + T + ".issue_type }}"
        ),
        "emailFormat": "text",
        "text": (
            "=New ShopAssist escalation\n\n"
            "Ticket: {{ $('Save Ticket in Postgres').item.json.ticket_id }}\n"
            "Customer: {{ " + T + ".customer_name }}\n"
            "Phone: {{ " + T + ".phone }}\n"
            "Order ID: {{ " + T + ".order_id }}\n"
            "Issue type: {{ " + T + ".issue_type }}\n"
            "Sentiment: {{ " + T + ".sentiment }}\n"
            "Priority: {{ " + T + ".priority }}\n\n"
            "Summary:\n{{ " + T + ".summary }}\n\n"
            "Suggested action:\n{{ " + T + ".suggested_action }}\n"
        ),
        "options": {},
    }, ["smtp"], onError="continueRegularOutput")
    ret = wf.node("Return Ticket ID to Agent", "n8n-nodes-base.set", 3.4, (1540, 0), {
        "assignments": {"assignments": [
            {"id": "r1", "name": "ticket_id", "type": "string",
             "value": "={{ $('Save Ticket in Postgres').item.json.ticket_id }}"},
            {"id": "r2", "name": "priority", "type": "string", "value": "={{ " + T + ".priority }}"},
            {"id": "r3", "name": "message", "type": "string",
             "value": "=Ticket {{ $('Save Ticket in Postgres').item.json.ticket_id }} created. "
                      "The human support team was alerted and will contact the customer within 4 business hours."},
        ]},
        "options": {},
    })
    wf.sticky("Step notes",
              "- Replace the Twilio **From** number, the e-mail **From/To** addresses and pick your "
              "credentials.\n"
              "- Twilio trial accounts can only SMS **verified** numbers.\n"
              "- Slack: invite the bot to `#support-escalations` (`/invite @your-bot`).\n"
              "- The **last node's output** is what the agent receives as the tool result.",
              (1760, -40), w=400, h=280)
    for a, b in [(trig, build), (build, norm), (norm, save), (save, slack), (slack, sms), (sms, mail), (mail, ret)]:
        wf.link(a, b)
    wf.link(llm, build, "ai_languageModel")
    wf.link(parser, build, "ai_outputParser")
    wf.save("04_escalation_subworkflow.json")


# ---------------------------------------------------------------- 05 order update webhook
def wf05():
    wf = WF("05 Order Status Update Webhook", timeout=60)
    wf.sticky("Overview – Workflow 05",
              "**Goal:** the store/courier system calls this webhook when an order status changes.\n\n"
              "`POST /webhook/order-update` with JSON body:\n"
              "`{\"order_id\": \"UT1003\", \"status\": \"delayed\", \"new_expected_delivery\": \"2026-10-15\"}`\n"
              "(`new_expected_delivery` is optional)\n\n"
              "Flow: update `orders` in Postgres → if status is `delayed`, SMS the customer via Twilio → "
              "reply with JSON.\n\n"
              "Course: 3–4 (webhooks, IF node), 19–20 (Postgres), 21–22 & capstone (Twilio SMS).",
              (-120, -420), w=560, h=360, color=4)
    hook = wf.node("Order Update Webhook", "n8n-nodes-base.webhook", 2, (0, 0), {
        "httpMethod": "POST",
        "path": "order-update",
        "responseMode": "responseNode",
        "options": {},
    }, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "shopassist-order-update")))
    upd = wf.node("Update Order Status", "n8n-nodes-base.postgres", 2.5, (220, 0), {
        "operation": "executeQuery",
        "query": (
            "UPDATE orders\n"
            "SET status = LOWER($2),\n"
            "    expected_delivery = COALESCE(NULLIF($3, '')::date, expected_delivery),\n"
            "    updated_at = now()\n"
            "WHERE order_id = UPPER($1)\n"
            "RETURNING order_id, customer_name, phone, status, expected_delivery;"
        ),
        "options": {"queryReplacement": (
            "={{ [ $json.body.order_id, $json.body.status, $json.body.new_expected_delivery || '' ] }}"
        )},
    }, ["postgres"], alwaysOutputData=True)
    cond = wf.node("Is Delayed?", "n8n-nodes-base.if", 2.2, (440, 0), {
        "conditions": {
            "options": {"caseSensitive": False, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": "c1",
                "leftValue": "={{ $json.status }}",
                "rightValue": "delayed",
                "operator": {"type": "string", "operation": "equals"},
            }],
            "combinator": "and",
        },
        "options": {},
    })
    sms = wf.node("SMS Delay Notice (Twilio)", "n8n-nodes-base.twilio", 1, (680, -120), {
        "from": TWILIO_FROM,
        "to": "={{ $json.phone }}",
        "message": (
            "=Hi {{ $json.customer_name }}, sorry! Your UrbanThread order {{ $json.order_id }} is delayed. "
            "New expected delivery: {{ $json.expected_delivery ? DateTime.fromISO(String($json.expected_delivery)."
            "slice(0, 10)).toFormat('dd LLL yyyy') : 'we will update you soon' }}. Reply or chat with "
            "ShopAssist for help."
        ),
        "options": {},
    }, ["twilioApi"], onError="continueRegularOutput")
    resp = wf.node("Respond to Caller", "n8n-nodes-base.respondToWebhook", 1.1, (920, 0), {
        "respondWith": "json",
        "responseBody": (
            "={{ JSON.stringify({\n"
            "  ok: !!$('Update Order Status').item.json.order_id,\n"
            "  order_id: $('Update Order Status').item.json.order_id || null,\n"
            "  status: $('Update Order Status').item.json.status || null,\n"
            "  sms_sent: $('Update Order Status').item.json.status === 'delayed',\n"
            "  message: $('Update Order Status').item.json.order_id ? 'Order updated' : 'Order not found'\n"
            "}) }}"
        ),
        "options": {},
    })
    wf.sticky("Test with curl",
              "```\ncurl -X POST \\\n  https://YOUR-N8N.app.n8n.cloud/webhook-test/order-update \\\n"
              "  -H 'Content-Type: application/json' \\\n"
              "  -d '{\"order_id\":\"UT1002\",\"status\":\"delayed\",\"new_expected_delivery\":\"2026-10-15\"}'\n```\n"
              "Use `/webhook-test/` while testing in the editor, `/webhook/` after activating.\n"
              "Unknown order IDs return `ok: false` (Postgres node has *Always Output Data* on).",
              (1120, -60), w=480, h=300)
    wf.link(hook, upd)
    wf.link(upd, cond)
    wf.link(cond, sms, out_index=0)   # true branch
    wf.link(cond, resp, out_index=1)  # false branch
    wf.link(sms, resp)
    wf.save("05_order_update_webhook.json")


# ---------------------------------------------------------------- 06 inventory agent
def wf06():
    wf = WF("06 Inventory Agent (Stock + Purchase Orders)", timeout=150)
    prompt = (ROOT / "prompts" / "inventory_agent_prompt.md").read_text(encoding="utf-8").strip()
    wf.sticky("Overview – Workflow 06",
              "**Second domain-expert agent** (multi-agent). Called by the support agent (03) through the "
              "`inventory_expert` tool.\n\n"
              "Tools: `stock_lookup` (Postgres `products`) and `create_purchase_order` (inserts into "
              "`purchase_orders`, status *pending_approval*). After the agent answers, a Slack message asks "
              "a manager to approve any new purchase order.\n\n"
              "Course: 12–13 (multi-agent, sub-workflows), 19–20 (agent + Postgres), Slack API.",
              (-120, -420), w=560, h=340, color=4)
    trig = wf.node("When Called by Support Agent", "n8n-nodes-base.executeWorkflowTrigger", 1.1, (0, 0), {
        "inputSource": "workflowInputs",
        "workflowInputs": {"values": [{"name": "question"}]},
    })
    agent = wf.node("Inventory AI Agent", "@n8n/n8n-nodes-langchain.agent", 1.7, (260, 0), {
        "agent": "toolsAgent",
        "promptType": "define",
        "text": "={{ $json.question }}",
        "options": {"systemMessage": "=" + prompt, "maxIterations": 4},
    })
    llm = ollama_chat(wf, "Ollama Chat Model", (120, 260), temperature=0)
    stock = wf.node("stock_lookup", "n8n-nodes-base.postgresTool", 2.5, (320, 260), {
        "descriptionType": "manual",
        "toolDescription": (
            "Look up products and stock. Input: a product name, SKU, size or category (e.g. kurta, TSH-BAS-L, "
            "hoodie XL), or the word low to list products at or below their reorder level."
        ),
        "operation": "executeQuery",
        "query": (
            "-- $1 = search text from the agent ('low' = everything at or below reorder level)\n"
            "SELECT sku, name, size, category, price_inr, stock, reorder_level, supplier, unit_cost_inr\n"
            "FROM products\n"
            "WHERE (LOWER(TRIM($1)) IN ('low', 'low stock') AND stock <= reorder_level)\n"
            "   OR sku ILIKE '%' || TRIM($1) || '%'\n"
            "   OR (LOWER(TRIM($1)) NOT IN ('low', 'low stock') AND EXISTS (\n"
            "         SELECT 1 FROM regexp_split_to_table(LOWER(TRIM($1)), '[^a-z0-9-]+') AS w\n"
            "         WHERE length(w) > 2 AND w NOT IN ('the', 'size', 'sizes', 'available', 'stock', 'have', 'what', 'you',\n"
            "               'any', 'for', 'and', 'are', 'there', 'much', 'many', 'how', 'can', 'get', 'buy', 'want', 'need')\n"
            "           AND (name || ' ' || category) ILIKE '%' || rtrim(w, 's?') || '%')\n"
            "       AND (COALESCE(size, '') = '' OR NOT EXISTS (SELECT 1 FROM regexp_split_to_table(UPPER(TRIM($1)), '[^A-Z0-9]+') AS s\n"
            "            WHERE s IN ('XS', 'S', 'M', 'L', 'XL', 'XXL', '28', '30', '32', '34', '36')) OR size IN (\n"
            "            SELECT s FROM regexp_split_to_table(UPPER(TRIM($1)), '[^A-Z0-9]+') AS s)))\n"
            "ORDER BY stock - reorder_level\n"
            "LIMIT 12;"
        ),
        "options": {"queryReplacement": (
            "={{ $fromAI('search', 'Product name, SKU, size or category, or the word low', 'string') }}"
        )},
    }, ["postgres"])
    po = wf.node("create_purchase_order", "n8n-nodes-base.postgresTool", 2.5, (520, 260), {
        "descriptionType": "manual",
        "toolDescription": (
            "Create ONE purchase order (status pending_approval) for a SKU that is low on stock. "
            "Inputs: sku (exact SKU from stock_lookup), quantity (whole number), reason (short text)."
        ),
        "operation": "executeQuery",
        "query": (
            "INSERT INTO purchase_orders (sku, quantity, supplier, est_cost_inr, reason)\n"
            "SELECT p.sku, $2::int, p.supplier, p.unit_cost_inr * $2::int, $3\n"
            "FROM products p WHERE p.sku = UPPER(TRIM($1))\n"
            "RETURNING po_id, sku, quantity, supplier, est_cost_inr, status;"
        ),
        "options": {"queryReplacement": (
            "={{ [ $fromAI('sku', 'Exact SKU, e.g. TSH-BAS-L', 'string'), "
            "$fromAI('quantity', 'Whole number of units to order', 'number'), "
            "$fromAI('reason', 'Short reason, e.g. stock 6 below reorder level 20', 'string') ] }}"
        )},
    }, ["postgres"])
    slack = wf.node("Ask Manager to Approve (Slack)", "n8n-nodes-base.slack", 2.3, (560, 0), {
        "select": "channel",
        "channelId": rl("#support-escalations", "name"),
        "text": "=:package: *Inventory Agent*\nRequest: {{ $('When Called by Support Agent').item.json.question }}\n"
                "Answer: {{ $json.output }}\nPlease review any purchase order marked *pending_approval*.",
        "otherOptions": {},
    }, ["slackApi"], onError="continueRegularOutput")
    ret = wf.node("Return Answer to Support Agent", "n8n-nodes-base.set", 3.4, (780, 0), {
        "assignments": {"assignments": [
            {"id": "a1", "name": "answer", "type": "string", "value": "={{ $('Inventory AI Agent').item.json.output }}"},
        ]},
        "options": {},
    })
    wf.link(trig, agent)
    wf.link(agent, slack)
    wf.link(slack, ret)
    wf.link(llm, agent, "ai_languageModel")
    wf.link(stock, agent, "ai_tool")
    wf.link(po, agent, "ai_tool")
    wf.save("06_inventory_agent.json")


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    for build in (wf01, wf02, wf03, wf04, wf05, wf06):
        build()
