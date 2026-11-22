"""ShopAssist web app: customer chat + manager dashboard ("Ops HQ"), on http://localhost:8501

    pip3 install pg8000          # once, for the dashboard
    python3 app/server.py

- The chat goes straight to the published workflow 03 on N8N_URL, so it works even when n8n's own chat window
  posts to the wrong port.
- The dashboard reads live numbers from Postgres (orders, tickets, stock, purchase orders, CSAT, identity checks)
  and lets a manager approve / reject purchase orders (through workflow 07, so Slack + supplier SMS still happen).
- Public use (tunnel / cloud): set ADMIN_KEY in .env. The chat stays open; the dashboard and PO decisions then
  need the key. Each visitor IP may send 20 chat messages per 5 minutes (messages max 500 characters).
Settings (.env or environment): N8N_URL, POSTGRES_*, ADMIN_KEY, APP_HOST (default 127.0.0.1; 0.0.0.0 in Docker),
PORT / APP_PORT (default 8501). Only the Python standard library + pg8000.
"""
import collections
import datetime
import decimal
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from shopassist_common import ENV, N8N, OLLAMA, ask, chat_url, db, http, kpis, last_error, workflows  # noqa: E402

HOST = ENV.get("APP_HOST") or "127.0.0.1"
PORT = int(os.environ.get("PORT") or ENV.get("APP_PORT") or 8501)
ADMIN_KEY = ENV.get("ADMIN_KEY", "")
PAGE = (Path(__file__).resolve().parent / "index.html").read_bytes()
MAX_MSG, RATE_N, RATE_WINDOW = 500, 20, 300
_hits, _lock = collections.defaultdict(collections.deque), threading.Lock()


def to_json(obj):
    def default(o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, (datetime.date, datetime.datetime)):
            return o.isoformat()[:16].replace("T", " ")
        return str(o)
    return json.dumps(obj, default=default).encode()


def rate_limited(ip):
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and q[0] < now - RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_N:
            return True
        q.append(now)
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "ShopAssist"

    def send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def ip(self):
        return (self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def is_admin(self):
        return not ADMIN_KEY or hmac.compare_digest(self.headers.get("X-Admin-Key", ""), ADMIN_KEY)

    def body(self):
        n = min(int(self.headers.get("Content-Length") or 0), 20_000)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/health":
            return self.send(200, b'{"ok": true}')
        if path == "/api/config":
            return self.send(200, to_json({"admin_required": bool(ADMIN_KEY)}))
        if not self.is_admin():
            return self.send(401, to_json({"error": "admin key required"}))
        if path == "/api/kpis":
            try:
                return self.send(200, to_json(kpis()))
            except Exception as e:
                return self.send(200, to_json({"error": str(e)}))
        if path == "/api/status":
            st_o, _, _ = http("GET", f"{OLLAMA}/api/tags", timeout=5)
            try:
                pub, n8n_ok = {k: bool(w.get("active")) for k, w in workflows().items()}, True
            except Exception:
                st_n, _, _ = http("GET", f"{N8N}/healthz", timeout=5)
                pub, n8n_ok = {}, st_n == 200
            return self.send(200, to_json({"n8n": n8n_ok, "ollama": st_o == 200, "published": pub}))
        self.send(404, b"{}")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/chat":
            return self.chat()
        if path == "/api/feedback":
            return self.feedback()
        if path == "/api/po/decide":
            return self.po_decide()
        self.send(404, b"{}")

    def chat(self):
        b = self.body()
        msg = str(b.get("message") or "").strip()
        if not msg:
            return self.send(400, to_json({"error": "empty message"}))
        if len(msg) > MAX_MSG:
            return self.send(200, to_json({"error": f"Please keep messages under {MAX_MSG} characters."}))
        if rate_limited(self.ip()):
            return self.send(429, to_json({"error": "Too many messages - please wait a few minutes."}))
        session = str(b.get("sessionId") or "")[:64] or None
        try:
            answer, sec, err = ask(msg, session, chat_url())
        except RuntimeError as e:
            return self.send(200, to_json({"error": str(e)}))
        if answer is None:
            detail = last_error("03") if self.is_admin() and ENV.get("N8N_API_KEY") else None
            return self.send(200, to_json({"error": "The assistant could not answer just now.", "detail": detail or err,
                                           "seconds": sec}))
        self.send(200, to_json({"answer": answer, "seconds": round(sec, 1)}))

    def feedback(self):
        b = self.body()
        rating = 1 if b.get("rating") == 1 else -1 if b.get("rating") == -1 else 0
        if not rating:
            return self.send(400, to_json({"error": "rating must be 1 or -1"}))
        try:
            con = db()
            con.run("INSERT INTO chat_feedback (session_id, rating, question, answer) VALUES (:s, :r, :q, :a)",
                    s=str(b.get("sessionId") or "")[:255], r=rating, q=str(b.get("question") or "")[:1000],
                    a=str(b.get("answer") or "")[:2000])
            con.close()
        except Exception as e:
            return self.send(200, to_json({"ok": False, "error": str(e)[:120]}))
        self.send(200, b'{"ok": true}')

    def po_decide(self):
        """Manager decision from the dashboard. Goes through workflow 07 (token check, Slack, supplier SMS);
        the secret token is read here on the server and never sent to the browser."""
        if not self.is_admin():
            return self.send(401, to_json({"error": "admin key required"}))
        b = self.body()
        action = b.get("action")
        if action not in ("approve", "reject"):
            return self.send(400, to_json({"error": "action must be approve or reject"}))
        try:
            con = db()
            r = con.run("SELECT approval_token FROM purchase_orders WHERE po_id = :p AND status = 'pending_approval'",
                        p=str(b.get("po_id") or "").upper())
            con.close()
        except Exception as e:
            return self.send(200, to_json({"ok": False, "message": str(e)[:120]}))
        if not r:
            return self.send(200, to_json({"ok": False, "message": "Not pending (already decided?)"}))
        st, res, _ = http("POST", f"{N8N}/webhook/po-decision", {"po": b.get("po_id"), "token": r[0][0], "action": action,
                                                                "by": "dashboard", "format": "json"}, timeout=60)
        if st != 200 or not isinstance(res, dict):
            return self.send(200, to_json({"ok": False, "message": f"workflow 07 not reachable (HTTP {st}) - is it published?"}))
        self.send(200, to_json(res))

    def log_message(self, fmt, *args):
        if "/api/chat" in (args[0] if args else ""):
            sys.stderr.write("chat request %s\n" % (args[1] if len(args) > 1 else ""))


if __name__ == "__main__":
    print(f"ShopAssist app on http://{'localhost' if HOST == '127.0.0.1' else HOST}:{PORT}  (n8n: {N8N}) "
          f"{'- dashboard protected by ADMIN_KEY ' if ADMIN_KEY else ''}- Ctrl+C to stop")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nShopAssist app stopped.")
