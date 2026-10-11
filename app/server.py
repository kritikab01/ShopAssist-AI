"""ShopAssist web app: chat + live business dashboard, on http://localhost:8501

    pip3 install pg8000          # once, for the live dashboard
    python3 app/server.py

- The chat goes straight to the published workflow 03 on N8N_URL (port 5679), so it works even when
  n8n's own chat window posts to the wrong port.
- The dashboard reads live numbers from Postgres every 10 seconds (orders, tickets, stock, purchase orders).
Only the Python standard library + pg8000. Reads .env from the repo folder.
"""
import datetime
import decimal
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from shopassist_common import OLLAMA, N8N, ask, chat_url, http, kpis, last_error, workflows  # noqa: E402

PORT = 8501
PAGE = (Path(__file__).resolve().parent / "index.html").read_bytes()


def to_json(obj):
    def default(o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, (datetime.date, datetime.datetime)):
            return o.isoformat()[:16].replace("T", " ")
        return str(o)
    return json.dumps(obj, default=default).encode()


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/api/kpis":
            try:
                return self.send(200, to_json(kpis()))
            except Exception as e:
                return self.send(200, to_json({"error": str(e)}))
        if self.path == "/api/status":
            st_o, _, _ = http("GET", f"{OLLAMA}/api/tags", timeout=5)
            try:
                wfs = workflows()
                pub = {k: bool(w.get("active")) for k, w in wfs.items()}
                n8n_ok = True
            except Exception:
                pub, n8n_ok = {}, False
            return self.send(200, to_json({"n8n": n8n_ok, "ollama": st_o == 200, "published": pub, "n8n_url": N8N}))
        self.send(404, b"{}")

    def do_POST(self):
        if self.path != "/api/chat":
            return self.send(404, b"{}")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        msg = (body.get("message") or "").strip()
        if not msg:
            return self.send(400, to_json({"error": "empty message"}))
        try:
            answer, sec, err = ask(msg, body.get("sessionId"), chat_url())
        except RuntimeError as e:
            return self.send(200, to_json({"error": str(e)}))
        if answer is None:
            return self.send(200, to_json({"error": err, "detail": last_error("03"), "seconds": sec}))
        self.send(200, to_json({"answer": answer, "seconds": round(sec, 1)}))

    def log_message(self, fmt, *args):
        if "/api/chat" in (args[0] if args else ""):
            sys.stderr.write("chat request %s\n" % (args[1] if len(args) > 1 else ""))


if __name__ == "__main__":
    print(f"ShopAssist app on http://localhost:{PORT}  (n8n: {N8N}, Ollama: {OLLAMA})  - Ctrl+C to stop")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nShopAssist app stopped.")
