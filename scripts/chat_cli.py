"""Chat with ShopAssist in the Terminal - type anything, one word is fine.

    python3 scripts/chat_cli.py

Commands:  /new  start a new conversation   /quit  exit
Talks to the published workflow 03 directly on N8N_URL (no browser chat window needed).
"""
import uuid

from shopassist_common import ask, chat_url, last_error

try:
    URL = chat_url()
except RuntimeError as e:
    raise SystemExit(f"Cannot start the chat: {e}")

session = f"cli-{uuid.uuid4().hex[:8]}"
print("ShopAssist (UrbanThread) - type a question or one word: UT1002, returns, diwali, stock, kurta, human")
print("Commands: /new = new conversation, /quit = exit. The first answer can take up to a minute.\n")
while True:
    try:
        q = input("you > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        break
    if not q:
        continue
    if q in ("/quit", "/exit", "quit", "exit"):
        break
    if q == "/new":
        session = f"cli-{uuid.uuid4().hex[:8]}"
        print("   (new conversation)\n")
        continue
    print("   ...thinking")
    answer, sec, err = ask(q, session, URL)
    if answer is not None:
        print(f"bot > {answer}\n      ({sec:.0f} s)\n")
    else:
        print(f"   ERROR after {sec:.0f} s: {err}")
        detail = last_error("03")
        if detail:
            print(f"   n8n says: {detail}")
        print()
