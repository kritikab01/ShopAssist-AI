"""Shared helpers for the ShopAssist scripts and the web app (reads .env, talks to n8n and Postgres).

Only the Python standard library, plus `pg8000` for database features (pip3 install pg8000).
Never prints secrets.
"""
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Some Wi-Fi networks hang on IPv6: always try IPv4 first.
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: sorted(_gai(*a, **k), key=lambda r: r[0] != socket.AF_INET)


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.split(" #")[0].strip().strip('"').strip("'")
    return env


ENV = load_env()
N8N = (ENV.get("N8N_URL") or "http://localhost:5679").rstrip("/")
OLLAMA = (ENV.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")


def http(method, url, body=None, headers=None, timeout=300):
    """Returns (status, parsed JSON or text, seconds). Status 0 = could not connect."""
    req = urllib.request.Request(url, method=method, headers={"Content-Type": "application/json", **(headers or {})},
                                 data=json.dumps(body).encode() if body is not None else None)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, st = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read().decode(), e.code
    except Exception as e:
        return 0, str(e), time.time() - t
    try:
        return st, (json.loads(raw) if raw else {}), time.time() - t
    except json.JSONDecodeError:
        return st, raw[:500], time.time() - t


def n8n_api(method, path, body=None, timeout=30):
    return http(method, f"{N8N}/api/v1{path}", body,
                {"X-N8N-API-KEY": ENV.get("N8N_API_KEY", ""), "Accept": "application/json"}, timeout)


def workflows():
    """{'03': workflow, ...} - the published copy wins if a name exists twice."""
    st, data, _ = n8n_api("GET", "/workflows?limit=100")
    if st != 200:
        raise RuntimeError(f"n8n API at {N8N} answered HTTP {st} - check N8N_URL / N8N_API_KEY in .env "
                           f"(python3 scripts/doctor.py)")
    out = {}
    for w in data.get("data", []):
        k = w["name"][:2]
        if k.isdigit() and (k not in out or (w.get("active") and not out[k].get("active"))):
            out[k] = w
    return out


def chat_url():
    """Production chat URL of workflow 03 (always on N8N_URL's port, so the port problem cannot happen)."""
    wfs = workflows()
    w3 = wfs.get("03")
    if not w3:
        raise RuntimeError("workflow 03 not found in n8n - run: python3 scripts/import_to_n8n.py")
    missing = [k for k in ("03", "04", "06") if k in wfs and not wfs[k].get("active")]
    if missing:
        raise RuntimeError("publish these workflows in n8n first: " + ", ".join(missing) +
                           " (order: 04 and 06, then 03)")
    hook = next(n.get("webhookId") for n in w3["nodes"] if n["type"].endswith("chatTrigger"))
    return f"{N8N}/webhook/{hook}/chat"


def ask(question, session_id=None, url=None, timeout=300):
    """Send one message to the ShopAssist chat. Returns (answer_text_or_None, seconds, error_or_None)."""
    url = url or chat_url()
    st, r, sec = http("POST", url, {"action": "sendMessage", "sessionId": session_id or f"cli-{uuid.uuid4().hex[:8]}",
                                    "chatInput": question}, timeout=timeout)
    if st == 200 and isinstance(r, dict) and "output" in r:
        return str(r["output"]).strip(), sec, None
    return None, sec, f"HTTP {st}: {str(r)[:300]}"


def last_error(prefix="03"):
    """Failing node + message of the newest failed run of a workflow (or None)."""
    try:
        w = workflows().get(prefix)
    except RuntimeError:
        return None
    if not w:
        return None
    st, ex, _ = n8n_api("GET", f"/executions?workflowId={w['id']}&status=error&limit=1&includeData=true")
    if st != 200 or not ex.get("data"):
        return None
    rd = (ex["data"][0].get("data") or {}).get("resultData") or {}
    err = rd.get("error") or {}
    return f"node '{rd.get('lastNodeExecuted')}': {err.get('message')} {str(err.get('description') or '')[:200]}"


def db():
    """pg8000 connection to Supabase (or any Postgres) from .env."""
    try:
        import pg8000.native
    except ImportError:
        raise RuntimeError("database driver missing - run: pip3 install pg8000")
    need = [k for k in ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD") if not ENV.get(k)]
    if need:
        raise RuntimeError("missing in .env: " + ", ".join(need))
    ctx = None
    if (ENV.get("POSTGRES_SSL") or "require").lower() not in ("disable", "false", "0"):
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # encrypted; pooler cert not in system store
    return pg8000.native.Connection(user=ENV["POSTGRES_USER"], password=ENV["POSTGRES_PASSWORD"],
                                    host=ENV["POSTGRES_HOST"], port=int(ENV.get("POSTGRES_PORT") or 5432),
                                    database=ENV.get("POSTGRES_DB") or "postgres", ssl_context=ctx, timeout=20)


def rows(con, sql):
    """Run a query and return a list of dicts."""
    data = con.run(sql)
    cols = [c["name"] for c in con.columns] if con.columns else []
    return [dict(zip(cols, r)) for r in data]


# Business KPIs - used by scripts/kpi_report.py and the live dashboard in app/.
KPI_QUERIES = {
    "orders_by_status": "SELECT status, count(*) AS orders, sum(amount_inr) AS value_inr FROM orders GROUP BY status ORDER BY orders DESC",
    "tickets_by_type": "SELECT issue_type, priority, count(*) AS tickets FROM tickets GROUP BY issue_type, priority ORDER BY tickets DESC",
    "ticket_totals": "SELECT count(*) AS tickets, sum((priority = 'high')::int) AS high_priority, "
                     "sum((sentiment = 'angry')::int) AS angry, sum((status = 'open')::int) AS open FROM tickets",
    "chat_totals": "SELECT count(DISTINCT session_id) AS conversations, sum((message->>'type' = 'human')::int) AS customer_messages "
                   "FROM n8n_chat_histories",
    "low_stock": "SELECT sku, name, size, stock, reorder_level FROM products WHERE stock <= reorder_level ORDER BY stock - reorder_level",
    "purchase_orders": "SELECT po_id, sku, quantity, est_cost_inr, status, created_at FROM purchase_orders ORDER BY id DESC LIMIT 10",
    "recent_tickets": "SELECT ticket_id, customer_name, order_id, issue_type, priority, created_at FROM tickets ORDER BY id DESC LIMIT 8",
}


def kpis():
    """All KPI tables as {name: [rows]} (missing tables give an 'error' entry instead of failing)."""
    con = db()
    out = {}
    for name, sql in KPI_QUERIES.items():
        try:
            out[name] = rows(con, sql)
        except Exception as e:  # e.g. products table not created yet
            out[name] = {"error": str(e).split("'M': ")[-1][:120]}
    con.close()
    return out
