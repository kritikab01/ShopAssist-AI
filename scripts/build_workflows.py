"""Generate the seven n8n workflow JSON files in workflows/.

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

# Cloud profile (python3 scripts/build_workflows.py --cloud -> workflows/cloud/*.json), for hosting without a
# laptop: Groq (free API, fast Llama models with tool calling) for chat and Cohere multilingual embeddings
# (free trial key, 1024 dims, also understands Hindi) -> its own Pinecone index "shopassist-cloud" (1024 dims).
CLOUD = {"chat_model": "openai/gpt-oss-120b", "embed_model": "embed-multilingual-v3.0",
         "index": "shopassist-cloud", "dimension": 1024}
PROFILE = "local"  # set by main(): "local" (Ollama) or "cloud" (Groq + Cohere)

# Placeholder credentials: after import, open each node and pick your own credential.
CRED = {
    "ollamaApi": {"id": "REPLACE_ME_ollama", "name": "Ollama account"},
    "pineconeApi": {"id": "REPLACE_ME_pinecone", "name": "Pinecone account"},
    "postgres": {"id": "REPLACE_ME_postgres", "name": "Supabase Postgres"},
    "slackApi": {"id": "REPLACE_ME_slack", "name": "Slack account"},
    "twilioApi": {"id": "REPLACE_ME_twilio", "name": "Twilio account"},
    "smtp": {"id": "REPLACE_ME_smtp", "name": "Gmail SMTP"},
    "groqApi": {"id": "REPLACE_ME_groq", "name": "Groq account"},
    "cohereApi": {"id": "REPLACE_ME_cohere", "name": "Cohere account"},
}
TWILIO_FROM = "+10000000000"  # placeholder: replace with your Twilio phone number in n8n
SUPPORT_EMAIL = "support@urbanthread.example"  # placeholder: replace with your own inbox
SENDER_EMAIL = "your.gmail@gmail.com"  # placeholder: the Gmail account used in SMTP credential
# Address of n8n as the manager's browser sees it (approval links). scripts/import_to_n8n.py replaces this
# placeholder with N8N_PUBLIC_URL (or N8N_URL) from .env, e.g. http://localhost:5679 or your tunnel / cloud URL.
PUBLIC_N8N = "__N8N_PUBLIC_URL__"

# One-click PO decision (workflow 07): only changes a PO that is still pending AND whose secret token matches.
PO_DECISION_SQL = (
    "-- $1 = PO ID, $2 = approve / reject, $3 = secret token from the link, $4 = who decided\n"
    "UPDATE purchase_orders po\n"
    "SET status = CASE WHEN LOWER($2) = 'approve' THEN 'approved' ELSE 'rejected' END,\n"
    "    decided_at = now(), decided_by = COALESCE(NULLIF(TRIM($4), ''), 'manager')\n"
    "FROM products p\n"
    "WHERE p.sku = po.sku AND po.po_id = UPPER(TRIM($1)) AND po.approval_token = $3\n"
    "  AND po.status = 'pending_approval' AND LOWER($2) IN ('approve', 'reject')\n"
    "RETURNING po.po_id, po.sku, po.quantity, po.supplier, po.est_cost_inr, po.status, po.decided_by,\n"
    "          p.name || COALESCE(' (' || p.size || ')', '') AS product, p.supplier_phone;"
)

# Identity check for order_lookup: an order is only shown when the customer gives the order ID AND the last 4 digits
# of the phone number on that order. Every check is logged in verification_attempts; 5 wrong tries in 15 minutes
# lock the order for the chat (4 digits = 10,000 combinations, so guessing is stopped long before it can work).
# The result always has a 'verification' and an 'instruction' column, which tells the model exactly what to do.
# (Tested in tests/test_sql.py against a real Postgres.)
ORDER_LOOKUP_SQL = (
    "-- $1 = order ID, $2 = last 4 digits of the phone number on the order\n"
    "WITH input AS (\n"
    "  SELECT UPPER(TRIM(COALESCE($1, ''))) AS oid,\n"
    "         RIGHT(REGEXP_REPLACE(COALESCE($2, ''), '[^0-9]', '', 'g'), 4) AS last4\n"
    "), o AS (\n"
    "  SELECT orders.* FROM orders, input WHERE orders.order_id = input.oid\n"
    "), fails AS (\n"
    "  SELECT count(*) AS n FROM verification_attempts v, input\n"
    "  WHERE v.order_id = input.oid AND NOT v.success AND v.created_at > now() - interval '15 minutes'\n"
    "), chk AS (\n"
    "  SELECT CASE\n"
    "    WHEN NOT EXISTS (SELECT 1 FROM o) THEN 'not_found'\n"
    "    WHEN (SELECT n FROM fails) >= 5 THEN 'locked'\n"
    "    WHEN length((SELECT last4 FROM input)) < 4 THEN 'need_phone'\n"
    "    WHEN (SELECT RIGHT(phone, 4) FROM o) = (SELECT last4 FROM input) THEN 'verified'\n"
    "    ELSE 'wrong_phone' END AS result\n"
    "), log AS (\n"
    "  INSERT INTO verification_attempts (order_id, success)\n"
    "  SELECT (SELECT oid FROM input), result = 'verified' FROM chk WHERE result IN ('verified', 'wrong_phone')\n"
    ")\n"
    "SELECT chk.result AS verification,\n"
    "  CASE chk.result\n"
    "    WHEN 'verified' THEN 'Identity verified. Share these order details with the customer.'\n"
    "    WHEN 'need_phone' THEN 'Do NOT share any order details. Ask the customer for the last 4 digits of the phone number used for this order.'\n"
    "    WHEN 'wrong_phone' THEN 'The digits do not match this order. Do NOT share any order details. Ask the customer to check the number, or offer a human agent.'\n"
    "    WHEN 'locked' THEN 'Too many wrong attempts for this order. Do NOT share any details. Offer to connect the customer with a human (escalate_to_human).'\n"
    "    ELSE 'No order with this ID. Ask the customer to check the order ID (format UT followed by 4 digits).' END AS instruction,\n"
    "  o.order_id, o.customer_name, o.items, o.amount_inr, o.payment_method, o.status, o.city,\n"
    "  o.order_date::text AS order_date, o.expected_delivery::text AS expected_delivery, o.courier, o.tracking_no,\n"
    "  (SELECT string_agg(e.status || ' (' || to_char(e.created_at, 'DD Mon') || ')', ' -> ' ORDER BY e.created_at)\n"
    "     FROM order_events e WHERE e.order_id = o.order_id) AS history\n"
    "FROM chk LEFT JOIN o ON chk.result = 'verified';"
)


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
        print("wrote", path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def index_name():
    return CLOUD["index"] if PROFILE == "cloud" else PINECONE_INDEX


def rl(value, mode="list"):
    """n8n 'resource locator' value (used for models, Pinecone index, Slack channel...)."""
    return {"__rl": True, "value": value, "mode": mode}


def ollama_chat(wf, name, pos, temperature=0.2, json_mode=False):
    if PROFILE == "cloud":
        return wf.node(name.replace("Ollama", "Groq"), "@n8n/n8n-nodes-langchain.lmChatGroq", 1, pos,
                       {"model": CLOUD["chat_model"], "options": {"temperature": temperature}}, ["groqApi"])
    options = {"temperature": temperature, "numCtx": NUM_CTX,
               "think": False,  # qwen2.5 is not a "thinking" model; n8n's default (true) can be rejected
               # Cap each reply: a 3B model sometimes loops (e.g. Hinglish, combined questions) until the
               # 240 s workflow timeout kills the chat. 700 tokens is far more than any answer or tool call.
               "numPredict": 700, "repeatPenalty": 1.1}
    if json_mode:
        options["format"] = "json"  # forces valid JSON output (used for the structured ticket)
    return wf.node(name, "@n8n/n8n-nodes-langchain.lmChatOllama", 1, pos,
                   {"model": CHAT_MODEL, "options": options}, ["ollamaApi"])


def ollama_embeddings(wf, name, pos):
    if PROFILE == "cloud":
        return wf.node(name.replace("Ollama", "Cohere"), "@n8n/n8n-nodes-langchain.embeddingsCohere", 1, pos,
                       {"modelName": CLOUD["embed_model"]}, ["cohereApi"])
    return wf.node(name, "@n8n/n8n-nodes-langchain.embeddingsOllama", 1, pos,
                   {"model": EMBED_MODEL}, ["ollamaApi"])


def text_splitter(wf, name, pos):
    return wf.node(name, "@n8n/n8n-nodes-langchain.textSplitterRecursiveCharacterTextSplitter",
                   1, pos, {"chunkSize": 1000, "chunkOverlap": 200, "options": {}})


def pinecone_insert(wf, name, pos, namespace):
    """Insert into ONE namespace per knowledge base, emptied first: re-running ingestion replaces the
    knowledge base instead of adding duplicate vectors (safe to run every day, e.g. after a policy change).
    n8n (node 1.3) collects all documents first and inserts them in batches of embeddingBatchSize; the namespace
    is cleared before each batch, so the batch size is set far above our document count -> cleared exactly once."""
    return wf.node(name, "@n8n/n8n-nodes-langchain.vectorStorePinecone", 1.3, pos,
                   {"mode": "insert", "pineconeIndex": rl(index_name()), "embeddingBatchSize": 5000,
                    "options": {"clearNamespace": True, "pineconeNamespace": namespace}},
                   ["pineconeApi"])


def workflow_tool(wf, name, pos, description, placeholder_id, fields):
    """An AI-agent tool that runs another n8n workflow (sub-workflow / sub-agent)."""
    return wf.node(name, "@n8n/n8n-nodes-langchain.toolWorkflow", 2, pos, {
        "name": name,  # required tool name in v2 (letters, numbers, underscores)
        "description": description,
        "workflowId": rl(placeholder_id, "id"),  # scripts/import_to_n8n.py fills in the real ID
        "workflowInputs": {
            "mappingMode": "defineBelow",
            # Every input has a default, so a small model that forgets one field cannot break the tool
            # ("Received tool input did not match expected schema ... Required").
            "value": {k: f"={{{{ $fromAI('{k}', '{v[0]}', 'string', '{v[1]}') }}}}" for k, v in fields.items()},
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
              "embed with Ollama `nomic-embed-text` (768 dims) → replace namespace `faq` (metadata `source = faq`).\n\n"
              "**Safe to re-run:** namespace `faq` is emptied and refilled (no duplicate vectors).\n\n"
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
    pc = pinecone_insert(wf, "Replace FAQ in Pinecone (namespace faq)", (680, 0), "faq")
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
              "in Pinecone namespace `website` (metadata `source = website`, `url`), replacing the old ones.\n\n"
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
    pc = pinecone_insert(wf, "Replace Website KB in Pinecone (namespace website)", (1480, 0), "website")
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
              "- `faq_knowledge` – Pinecone namespace `faq`\n"
              "- `website_knowledge` – Pinecone namespace `website`\n"
              "- `order_lookup` – Postgres, order ID + last 4 phone digits (identity check, lockout after 5 tries)\n"
              "- `escalate_to_human` – calls workflow 04 (Slack + SMS + e-mail)\n"
              "- `inventory_expert` – asks the **Inventory Agent** (workflow 06) – multi-agent\n\n"
              "**Guardrails:** *Detect Intent* (rules) before the agent; after it, if a human is needed and the "
              "reply has no ticket ID, *Create Ticket (workflow 04)* runs anyway (guaranteed escalation).\n\n"
              "Memory: Postgres Chat Memory (table `n8n_chat_histories`, last 10 messages).\n\n"
              "Course: 1–4 (agents, n8n basics), 7–9 & 18 (RAG + metadata filter), 12–13 (sub-workflow tool), "
              "14–15 (agentic RAG, two knowledge bases), 16–17 (public chat), 19–20 (agent + Postgres).",
              (-120, -520), w=600, h=460, color=4)
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
        "options": {"systemMessage": "=" + system_prompt, "maxIterations": 8,
                    "returnIntermediateSteps": True},  # lets 'Needs a Ticket?' see if escalate_to_human ran
    }, onError="continueRegularOutput")  # if the model fails, the steps after it still send a useful reply
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
            "pineconeIndex": rl(index_name()),
            "topK": 4,
            "includeDocumentMetadata": True,
            "options": {"pineconeNamespace": source, "metadata": metadata(("source", source))},
        }, ["pineconeApi"])
        emb = ollama_embeddings(wf, f"Ollama Embeddings ({source})", (x, 520))
        wf.link(emb, node, "ai_embedding")
        wf.link(node, agent, "ai_tool")

    kb_tool("faq_knowledge", "faq",
            "Search the official UrbanThread store FAQ and policies: returns (15 days), refunds, "
            "exchanges, sizes, delivery times and charges, COD, payments, cancellations.", 340)
    kb_tool("website_knowledge", "website",
            "Search summaries of UrbanThread web pages: courier partners, dispatch times, festive/Diwali "
            "delays, size and fit tips, offers and coupon codes, gift cards, loyalty points, garment care, "
            "sustainability.", 600)

    orders = wf.node("order_lookup", "n8n-nodes-base.postgresTool", 2.5, (860, 300), {
        "descriptionType": "manual",
        "toolDescription": (
            "Look up a customer's order. Inputs: order_id (like UT1003) and phone_last4 (the last 4 digits of "
            "the phone number on the order, or empty if the customer has not given them). Order details are "
            "only returned when the digits match; otherwise follow the 'instruction' field of the result."
        ),
        "operation": "executeQuery",
        "query": ORDER_LOOKUP_SQL,
        "options": {
            "queryReplacement": (
                "={{ [ $fromAI('order_id', 'The order ID given by the customer, e.g. UT1003', 'string', ''), "
                "$fromAI('phone_last4', 'Last 4 digits of the phone number on the order, or empty string', 'string', '') ] }}"
            ),
        },
    }, ["postgres"])
    wf.link(orders, agent, "ai_tool")

    fields = {  # name: (description for the model, default if the model leaves it out)
        "customer_name": ("Customer name, or Unknown", "Unknown"),
        "phone": ("Customer phone number, or empty string", ""),
        "order_id": ("Order ID like UT1003, or empty string", ""),
        "reason": ("Why you are escalating: angry customer, refund over Rs 5000, no answer found, or human requested",
                   "Customer needs help from a human"),
        "conversation_summary": ("Short summary of the conversation and the exact problem of the customer",
                                 "See the chat history"),
    }
    esc = workflow_tool(wf, "escalate_to_human", (1060, 300), (
        "Create a support ticket and alert the human support team (Slack, SMS, e-mail). Use when the "
        "customer is angry, wants a refund above Rs 5,000, asks for a human, or the answer is not in "
        "the knowledge bases. Returns the ticket ID to give to the customer."
    ), "REPLACE_WITH_WORKFLOW_04_ID", fields)
    wf.link(esc, agent, "ai_tool")

    # Multi-agent: a second domain expert (workflow 06) is available to this agent as a tool.
    inv = workflow_tool(wf, "inventory_expert", (1260, 300), (
        "Ask the Inventory Agent (domain expert for stock and procurement). Use for product availability, "
        "sizes in stock, low stock, restocking and purchase orders. Send the full question; it returns the answer."
    ), "REPLACE_WITH_WORKFLOW_06_ID", {"question": ("The full question about stock, availability, restocking or purchase orders", "Which products are low on stock?")})
    wf.link(inv, agent, "ai_tool")

    # Small local models follow an explicit note far better than a long system prompt. This step spots clear
    # signals (anger / wants a human, refund, out-of-scope) and adds a short instruction to the message.
    # Rules live in prompts/detect_intent.js (anger, sarcasm, Hindi/Hinglish, refunds, stock, identity check);
    # tests/test_guardrails.py runs that exact file with Node.
    guard = wf.node("Detect Intent (rules)", "n8n-nodes-base.code", 2, (180, 0), {
        "jsCode": (ROOT / "prompts" / "detect_intent.js").read_text(encoding="utf-8"),
    })
    wf.link(chat, guard)
    wf.link(guard, agent)

    # Guaranteed escalation: a small model sometimes says "I have escalated" without calling the tool.
    # If the rules say a human is needed (angry / asks for a manager / refund over Rs 5,000) and the reply
    # has no ticket ID, the workflow creates the ticket itself (workflow 04) and adds the ID to the reply.
    INTENT = "$('Detect Intent (rules)').item.json.intent"
    amount = wf.node("Order Details (for escalation check)", "n8n-nodes-base.postgres", 2.5, (720, -220), {
        "operation": "executeQuery",
        "query": (
            "-- internal check only (amount for the refund rule); details are shown only if verified = true\n"
            "SELECT order_id, customer_name, phone, amount_inr, items, status, expected_delivery::text AS expected_delivery, courier, tracking_no,\n"
            "       (length($2) = 4 AND RIGHT(phone, 4) = $2) AS verified\n"
            "FROM orders\n"
            "WHERE order_id = UPPER(TRIM($1)) LIMIT 1;"
        ),
        "options": {"queryReplacement": "={{ [ " + INTENT + ".order_id || 'none', " + INTENT + ".last4 || '' ] }}"},
    }, ["postgres"], alwaysOutputData=True, onError="continueRegularOutput")
    decide = wf.node("Needs a Ticket? (rules)", "n8n-nodes-base.code", 2, (940, -220), {
        "jsCode": (
            "// Decide if a human ticket is required but the agent did not create one.\n"
            "const intent = $('Detect Intent (rules)').first().json.intent || {};\n"
            "const order = $json.order_id ? $json : {};\n"
            "let reply = String($('ShopAssist AI Agent').first().json.output || '').trim();\n"
            "if (!reply) {  // the AI step failed (e.g. bad tool call): answer from the database / rules instead\n"
            "  const r = order.order_id && order.verified ? order : null;  // never show details without the phone check\n"
            "  reply = r ? `Your order ${r.order_id} (${r.items}) is ${String(r.status).replace(/_/g, ' ')}. Expected delivery: ${String(r.expected_delivery).slice(0, 10)}, courier ${r.courier}, tracking ${r.tracking_no}.`\n"
            "    : (order.order_id && intent.last4) ? `The phone digits you gave do not match order ${order.order_id}, so I cannot show it. Please check the last 4 digits of the phone number used for the order.`\n"
            "    : (order.order_id && !intent.escalate && !intent.refund) ? `To keep your order private, please share the last 4 digits of the phone number used for order ${order.order_id}.`\n"
            "    : (intent.escalate || intent.refund) ? 'I am sorry for the trouble. Let me connect you with our support team.'\n"
            "    : 'Sorry, I could not process that just now. Please share your order ID (like UT1003) or ask about returns, sizes, delivery, offers or stock.';\n"
            "}\n"
            "const bigRefund = intent.refund && Number(order.amount_inr || 0) > 5000;\n"
            "// Did the agent already escalate in this run? Its reply may say so without the ticket ID, so look at\n"
            "// the escalate_to_human tool itself - otherwise one message would create two tickets.\n"
            "const steps = $('ShopAssist AI Agent').first().json.intermediateSteps || [];\n"
            "const esc = steps.filter(s => ((s.action || {}).tool || '') === 'escalate_to_human');\n"
            "const toolTicket = esc.length ? ((JSON.stringify(esc.map(s => s.observation)).match(/TKT-\\d+/) || ['escalated'])[0]) : '';\n"
            "if (/^TKT-/.test(toolTicket) && !/TKT-\\d+/.test(reply)) reply += `\\n\\nYour ticket ID is ${toolTicket}.`;\n"
            "const needs = (intent.escalate || bigRefund) && !toolTicket && !/TKT-\\d+/.test(reply);\n"
            "const reason = intent.escalate ? 'Customer is upset or asked for a human' : 'Refund above Rs 5,000 needs human approval';\n"
            "return [{ json: { needs_ticket: needs, reply, language: intent.language || 'en',\n"
            "  customer_name: intent.name || order.customer_name || 'Unknown',\n"
            "  phone: intent.phone || order.phone || '',\n"
            "  order_id: intent.order_id || '',\n"
            "  reason,\n"
            "  conversation_summary: (reason + '. Customer wrote: ' + String(intent.original || '')).slice(0, 1500) } }];\n"
        ),
    })
    check = wf.node("Ticket Missing?", "n8n-nodes-base.if", 2.2, (1160, -220), {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": "c1", "leftValue": "={{ $json.needs_ticket }}", "rightValue": "",
                            "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
            "combinator": "and",
        },
        "options": {},
    })
    in_fields = ["customer_name", "phone", "order_id", "reason", "conversation_summary"]
    create = wf.node("Create Ticket (workflow 04)", "n8n-nodes-base.executeWorkflow", 1.2, (1380, -320), {
        "source": "database",
        "workflowId": rl("REPLACE_WITH_WORKFLOW_04_ID", "id"),  # scripts/import_to_n8n.py fills in the real ID
        "workflowInputs": {
            "mappingMode": "defineBelow",
            "value": {k: "={{ $json." + k + " }}" for k in in_fields},
            "matchingColumns": [],
            "schema": [{"id": k, "displayName": k, "required": False, "defaultMatch": False, "display": True,
                        "canBeUsedToMatch": True, "type": "string", "removed": False} for k in in_fields],
            "attemptToConvertTypes": False,
            "convertFieldsToString": True,
        },
        "mode": "once",
        "options": {"waitForSubWorkflow": True},
    })
    with_ticket = wf.node("Reply + Ticket ID", "n8n-nodes-base.set", 3.4, (1600, -320), {
        "assignments": {"assignments": [{"id": "o1", "name": "output", "type": "string", "value": (
            "={{ $('Needs a Ticket? (rules)').item.json.reply }}\n\n{{ {"
            "hinglish: 'Maine aapki problem hamari support team ko bhej di hai. Aapka ticket ID ' + $json.ticket_id + ' hai - 4 business hours mein team aapse contact karegi.', "
            "hi: 'मैंने आपकी समस्या हमारी सपोर्ट टीम को भेज दी है। आपका टिकट ID ' + $json.ticket_id + ' है - 4 कार्य घंटों में टीम आपसे संपर्क करेगी।'"
            "}[$('Needs a Ticket? (rules)').item.json.language] || 'I have passed this to our human support team. Your ticket ID is ' + "
            "$json.ticket_id + ' - a team member will contact you within 4 business hours.' }}"
        )}]},
        "options": {},
    })
    plain = wf.node("Reply", "n8n-nodes-base.set", 3.4, (1380, -120), {
        "assignments": {"assignments": [{"id": "o2", "name": "output", "type": "string",
                                         "value": "={{ $json.reply }}"}]},
        "options": {},
    })
    wf.link(agent, amount)
    wf.link(amount, decide)
    wf.link(decide, check)
    wf.link(check, create, out_index=0)
    wf.link(check, plain, out_index=1)
    wf.link(create, with_ticket)
    wf.link(llm, agent, "ai_languageModel")
    wf.link(mem, agent, "ai_memory")
    wf.sticky("Setup notes",
              "1. Import workflow 04 first, copy its ID from the URL, and select it in **escalate_to_human**.\n"
              "2. Set credentials on every node with a ⚠ warning.\n"
              "3. **Activate** the workflow, open the Chat Trigger and copy the **public chat URL**.\n"
              "4. The system prompt lives in `prompts/agent_system_prompt.md` (rules: answer only from "
              "tools, cite source, ask for order ID, escalate if angry / refund > Rs 5,000 / no answer).",
              (1480, 120), w=420, h=300)
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
                    (200, 0), {
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
    norm = wf.node("Normalize Ticket (fallback)", "n8n-nodes-base.code", 2, (470, 0), {
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
            "const issueGuess = /refund|paise? wapas|money back/.test(text) ? 'refund' : /late|delay|kab aayega|not (here|delivered|arrived)|where is|deliver/.test(text) ? 'delivery' : 'other';\n"
            "const angry = /angry|manager|worst|third time|furious|complain|sarcas|upset|bakwas|ghatiya/.test(text);\n"
            "const raw = String(inp.reason || '') + ' ' + String(inp.conversation_summary || '');\n"
            "const language = /[\\u0900-\\u097F]/.test(raw) ? 'hi' : /\\b(kya|hai|mera|kab|nahi|aayega|chahiye|wapas|karo|bhai)\\b/i.test(raw) ? 'hinglish' : 'en';\n"
            "return [{ json: { output: {\n"
            "  customer_name: String(t.customer_name || inp.customer_name || 'Unknown').slice(0, 100),\n"
            "  phone: phone.slice(0, 20),\n"
            "  order_id: oid ? oid[0] : '',\n"
            "  issue_type: pick(t.issue_type, ['refund', 'return', 'delivery', 'damaged_item', 'payment', 'size', 'other'], issueGuess),\n"
            "  sentiment: pick(t.sentiment, ['positive', 'neutral', 'negative', 'angry'], angry ? 'angry' : 'negative'),\n"
            "  priority: pick(t.priority, ['low', 'medium', 'high'], 'high'),\n"
            "  summary: String(t.summary || inp.conversation_summary || inp.reason || '').slice(0, 2000),\n"
            "  suggested_action: String(t.suggested_action || 'Contact the customer and review the chat.').slice(0, 1000),\n"
            "  language,\n"
            "} } }];\n"
        ),
    })
    T = "$('Normalize Ticket (fallback)').item.json.output"
    save = wf.node("Save Ticket in Postgres", "n8n-nodes-base.postgres", 2.5, (660, 0), {
        "operation": "executeQuery",
        "query": (
            "INSERT INTO tickets (customer_name, phone, order_id, issue_type, sentiment, priority,\n"
            "                     summary, suggested_action, language)\n"
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)\n"
            "RETURNING ticket_id, priority, created_at;"
        ),
        "options": {"queryReplacement": (
            "={{ [ $json.output.customer_name, $json.output.phone, $json.output.order_id, "
            "$json.output.issue_type, $json.output.sentiment, $json.output.priority, "
            "$json.output.summary, $json.output.suggested_action, $json.output.language ] }}"
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
            "WITH u AS (\n"
            "  UPDATE orders\n"
            "  SET status = LOWER($2),\n"
            "      expected_delivery = COALESCE(NULLIF($3, '')::date, expected_delivery),\n"
            "      updated_at = now()\n"
            "  WHERE order_id = UPPER($1)\n"
            "  RETURNING order_id, customer_name, phone, status, expected_delivery\n"
            "), e AS (  -- status history for the timeline / dashboard\n"
            "  INSERT INTO order_events (order_id, status, note)\n"
            "  SELECT order_id, status, COALESCE(NULLIF($4, ''), 'Status update from the store system') FROM u\n"
            ")\n"
            "SELECT * FROM u;"
        ),
        "options": {"queryReplacement": (
            "={{ [ $json.body.order_id, $json.body.status, $json.body.new_expected_delivery || '', $json.body.note || '' ] }}"
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
    # Plain words, no shell command: Render's web firewall blocks API uploads that contain a curl command line.
    wf.sticky("How to test",
              "POST JSON to `https://YOUR-N8N/webhook-test/order-update`, body:\n"
              "`{\"order_id\":\"UT1002\",\"status\":\"delayed\",\"new_expected_delivery\":\"2026-10-15\"}`\n"
              "(Full command: docs/test_questions.md.)\n"
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
              "`purchase_orders`, status *pending_approval*). After the agent answers, a Slack message gives "
              "the manager a **Review and approve / reject** link per new purchase order (workflow 07).\n\n"
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
            "SELECT p.sku, q.qty, p.supplier, p.unit_cost_inr * q.qty, $3\n"
            "FROM products p\n"
            "-- never less than the reorder rule: (2 x reorder_level - stock), rounded up to a multiple of 5\n"
            "CROSS JOIN LATERAL (SELECT GREATEST(COALESCE($2::int, 0),\n"
            "                   (CEIL(GREATEST(2 * p.reorder_level - p.stock, 5) / 5.0) * 5)::int) AS qty) q\n"
            "WHERE p.sku = UPPER(TRIM($1))\n"
            "RETURNING po_id, sku, quantity, supplier, est_cost_inr, status;"
        ),
        "options": {"queryReplacement": (
            "={{ [ $fromAI('sku', 'Exact SKU, e.g. TSH-BAS-L', 'string'), "
            "$fromAI('quantity', 'Whole number of units to order', 'number'), "
            "$fromAI('reason', 'Short reason, e.g. stock 6 below reorder level 20', 'string') ] }}"
        )},
    }, ["postgres"])
    # Purchase orders this run created, with their secret approval token (only goes into the manager's message).
    new_pos = wf.node("New Purchase Orders", "n8n-nodes-base.postgres", 2.5, (600, 0), {
        "operation": "executeQuery",
        "query": (
            "SELECT po.po_id, po.sku, p.name || COALESCE(' (' || p.size || ')', '') AS product, po.quantity,\n"
            "       po.supplier, po.est_cost_inr, po.approval_token\n"
            "FROM purchase_orders po JOIN products p ON p.sku = po.sku\n"
            "WHERE po.status = 'pending_approval' AND po.created_at > now() - interval '3 minutes'\n"
            "ORDER BY po.id;"
        ),
        "options": {},
    }, ["postgres"], alwaysOutputData=True, executeOnce=True, onError="continueRegularOutput")
    slack = wf.node("Ask Manager to Approve (Slack)", "n8n-nodes-base.slack", 2.3, (820, 0), {
        "select": "channel",
        "channelId": rl("#support-escalations", "name"),
        "text": (
            "=:package: *Inventory Agent*\nRequest: {{ $('When Called by Support Agent').item.json.question }}\n"
            "Answer: {{ $('Inventory AI Agent').item.json.output }}\n"
            "{{ $('New Purchase Orders').all().filter(i => i.json.po_id).map(i => ':memo: *' + i.json.po_id + '* ' + "
            "i.json.quantity + ' x ' + i.json.product + ' from ' + i.json.supplier + ', approx. Rs ' + i.json.est_cost_inr + "
            "' -> <" + PUBLIC_N8N + "/webhook/po-review?po=' + i.json.po_id + '&token=' + i.json.approval_token + "
            "'|Review and approve / reject>').join('\\n') || '' }}"
        ),
        "otherOptions": {"unfurl_links": False, "unfurl_media": False},
    }, ["slackApi"], onError="continueRegularOutput", executeOnce=True)
    ret = wf.node("Return Answer to Support Agent", "n8n-nodes-base.set", 3.4, (1040, 0), {
        "assignments": {"assignments": [
            {"id": "a1", "name": "answer", "type": "string", "value": "={{ $('Inventory AI Agent').item.json.output }}"},
        ]},
        "options": {},
    }, executeOnce=True)
    wf.link(trig, agent)
    wf.link(agent, new_pos)
    wf.link(new_pos, slack)
    wf.link(slack, ret)
    wf.link(llm, agent, "ai_languageModel")
    wf.link(stock, agent, "ai_tool")
    wf.link(po, agent, "ai_tool")
    wf.save("06_inventory_agent.json")


# ---------------------------------------------------------------- 07 purchase-order approval
PAGE_STYLE = ("<meta name='viewport' content='width=device-width,initial-scale=1'><style>"
              "*{box-sizing:border-box}body{font-family:system-ui,sans-serif;background:#0f0e17;color:#fffffe;display:grid;place-items:center;"
              "min-height:100vh;margin:0;padding:16px}.c{background:#1b1a27;border-radius:20px;padding:24px;max-width:420px;"
              "width:100%;box-shadow:0 0 0 2px #c6ff3d33}h1{margin:0 0 8px;font-size:22px}p{color:#b8b5c9}"
              "b{color:#c6ff3d}button{font:600 16px system-ui;border:0;border-radius:999px;padding:12px 20px;margin:6px 6px 0 0;"
              "cursor:pointer}.ok{background:#c6ff3d;color:#0f0e17}.no{background:#2b2a3a;color:#fffffe}</style>")


def wf07():
    wf = WF("07 Purchase Order Approval (Manager)", timeout=60)
    wf.sticky("Overview – Workflow 07",
              "**Human-in-the-loop approval** for purchase orders drafted by the Inventory Agent (06).\n\n"
              "1. Slack message (06) / dashboard → `GET /webhook/po-review?po=PO-0001&token=…` shows a review page "
              "(changes nothing – link previews and e-mail scanners can open it safely).\n"
              "2. Manager presses **Approve** or **Reject** → `POST /webhook/po-decision` → PO updated only if the "
              "secret token matches and it is still *pending_approval* → Slack confirmation → if approved, SMS to the "
              "supplier (Twilio).\n\nCourse: webhooks, IF, Postgres, Slack, Twilio, human-in-the-loop.",
              (-120, -460), w=620, h=380, color=4)
    # --- review page (read only)
    rv = wf.node("Review Link (GET)", "n8n-nodes-base.webhook", 2, (0, 0), {
        "httpMethod": "GET", "path": "po-review", "responseMode": "responseNode", "options": {},
    }, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "shopassist-po-review")))
    find = wf.node("Find Purchase Order", "n8n-nodes-base.postgres", 2.5, (220, 0), {
        "operation": "executeQuery",
        "query": (
            "SELECT po.po_id, po.quantity, po.supplier, po.est_cost_inr, po.status, po.reason, po.approval_token,\n"
            "       p.name || COALESCE(' (' || p.size || ')', '') AS product, p.stock, p.reorder_level\n"
            "FROM purchase_orders po JOIN products p ON p.sku = po.sku\n"
            "WHERE po.po_id = UPPER(TRIM($1)) AND po.approval_token = $2;"
        ),
        "options": {"queryReplacement": "={{ [ $json.query.po || '', $json.query.token || '' ] }}"},
    }, ["postgres"], alwaysOutputData=True)
    page = wf.node("Show Review Page", "n8n-nodes-base.respondToWebhook", 1.1, (440, 0), {
        "respondWith": "text",
        "responseBody": (
            "={{ \"<!doctype html><title>Purchase order</title>" + PAGE_STYLE + "<div class='c'>\" + ($json.po_id ? "
            "('<h1>📦 ' + $json.po_id + '</h1><p><b>' + $json.quantity + ' x ' + $json.product + '</b><br>Supplier: ' + "
            "$json.supplier + '<br>Estimated cost: Rs ' + $json.est_cost_inr + '<br>Stock now: ' + $json.stock + "
            "' (reorder level ' + $json.reorder_level + ')<br>Reason: ' + ($json.reason || '-') + '</p>' + "
            "($json.status === 'pending_approval' ? ('<form method=post action=po-decision>"
            "<input type=hidden name=po value=' + $json.po_id + '><input type=hidden name=token value=' + "
            "$json.approval_token + '><button class=ok name=action value=approve>✅ Approve</button>"
            "<button class=no name=action value=reject>❌ Reject</button></form>') : "
            "('<p>Already <b>' + $json.status + '</b>.</p>'))) : '<h1>🔒 Link not valid</h1><p>Check the link "
            "in Slack.</p>') + '</div>' }}"
        ),
        "options": {"responseHeaders": {"entries": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}]}},
    })
    # --- decision (changes data)
    dec = wf.node("Decision (POST)", "n8n-nodes-base.webhook", 2, (0, 320), {
        "httpMethod": "POST", "path": "po-decision", "responseMode": "responseNode", "options": {},
    }, webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "shopassist-po-decision")))
    apply_ = wf.node("Apply Decision (token check)", "n8n-nodes-base.postgres", 2.5, (220, 320), {
        "operation": "executeQuery",
        "query": PO_DECISION_SQL,
        "options": {"queryReplacement": (
            "={{ [ $json.body.po || '', $json.body.action || '', $json.body.token || '', $json.body.by || '' ] }}"
        )},
    }, ["postgres"], alwaysOutputData=True)
    valid = wf.node("Valid Decision?", "n8n-nodes-base.if", 2.2, (440, 320), {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": "v1", "leftValue": "={{ $json.po_id }}", "rightValue": "",
                            "operator": {"type": "string", "operation": "notEmpty", "singleValue": True}}],
            "combinator": "and",
        },
        "options": {},
    })
    slack = wf.node("Tell Team in Slack", "n8n-nodes-base.slack", 2.3, (660, 220), {
        "select": "channel",
        "channelId": rl("#support-escalations", "name"),
        "text": ("={{ $json.status === 'approved' ? ':white_check_mark:' : ':x:' }} *{{ $json.po_id }}* "
                 "{{ $json.status }} by {{ $json.decided_by }}: {{ $json.quantity }} x {{ $json.product }} "
                 "from {{ $json.supplier }} (approx. Rs {{ $json.est_cost_inr }})"),
        "otherOptions": {},
    }, ["slackApi"], onError="continueRegularOutput")
    approved = wf.node("Approved?", "n8n-nodes-base.if", 2.2, (880, 220), {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": "a1", "leftValue": "={{ $('Apply Decision (token check)').item.json.status }}",
                            "rightValue": "approved", "operator": {"type": "string", "operation": "equals"}}],
            "combinator": "and",
        },
        "options": {},
    })
    A = "$('Apply Decision (token check)').item.json"
    sms = wf.node("SMS Supplier (Twilio)", "n8n-nodes-base.twilio", 1, (1100, 120), {
        "from": TWILIO_FROM,
        "to": "={{ " + A + ".supplier_phone }}",
        "message": ("=UrbanThread purchase order {{ " + A + ".po_id }}: please supply {{ " + A + ".quantity }} x "
                    "{{ " + A + ".product }} (SKU {{ " + A + ".sku }}). Reply to confirm the delivery date."),
        "options": {},
    }, ["twilioApi"], onError="continueRegularOutput")
    RESULT = ("{ ok: !!" + A + ".po_id, po_id: " + A + ".po_id || null, status: " + A + ".status || null, "
              "message: " + A + ".po_id ? ('Purchase order ' + " + A + ".status) : 'Link not valid or already decided' }")
    done = wf.node("Show Result", "n8n-nodes-base.respondToWebhook", 1.1, (1320, 320), {
        "respondWith": "text",
        "responseBody": (
            "={{ $('Decision (POST)').item.json.body.format === 'json' ? JSON.stringify(" + RESULT + ") : "
            "\"<!doctype html><title>Purchase order</title>" + PAGE_STYLE + "<div class='c'>\" + (" + A + ".po_id ? "
            "('<h1>' + (" + A + ".status === 'approved' ? '✅ ' : '❌ ') + " + A + ".po_id + ' ' + " + A + ".status + "
            "'</h1><p>The team was told in Slack' + (" + A + ".status === 'approved' ? ' and the supplier got an SMS' : '') + "
            "'.</p>') : '<h1>🔒 Not changed</h1><p>The link is not valid or this order was already decided.</p>') + "
            "'</div>' }}"
        ),
        "options": {"responseHeaders": {"entries": [{"name": "Content-Type", "value":
            "={{ $('Decision (POST)').item.json.body.format === 'json' ? 'application/json' : 'text/html; charset=utf-8' }}"}]}},
    })
    wf.link(rv, find)
    wf.link(find, page)
    wf.link(dec, apply_)
    wf.link(apply_, valid)
    wf.link(valid, slack, out_index=0)
    wf.link(valid, done, out_index=1)
    wf.link(slack, approved)
    wf.link(approved, sms, out_index=0)
    wf.link(approved, done, out_index=1)
    wf.link(sms, done)
    wf.save("07_po_approval.json")


BUILDERS = (wf01, wf02, wf03, wf04, wf05, wf06, wf07)


def build_all(out_dir=None, profile="local"):
    """Write all workflows for one profile. Local -> workflows/, cloud -> workflows/cloud/."""
    global OUT_DIR, PROFILE
    PROFILE = profile
    OUT_DIR = Path(out_dir) if out_dir else (ROOT / "workflows" / ("cloud" if profile == "cloud" else ""))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for build in BUILDERS:
        build()


if __name__ == "__main__":
    build_all(profile="local")
    build_all(profile="cloud")
