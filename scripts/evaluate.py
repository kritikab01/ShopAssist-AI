"""Automatic evaluation of ShopAssist: asks 17 test questions and scores every answer three ways.

    python3 scripts/evaluate.py              # all tests (a few minutes with a local model)
    python3 scripts/evaluate.py 1 9 12       # only some tests (by number)
    python3 scripts/evaluate.py --no-judge   # skip the AI judge (keyword + database checks only)

1. Keyword check   - the answer contains every expected fact (each group: any one of the words) and none of the
                     forbidden words (e.g. order details when the phone digits were wrong).
2. Database check  - for order questions the expected facts are read from the LIVE database (status, courier),
                     so a test still works after the order-update webhook changed an order.
3. AI judge        - a second model grades the answer against the expected behaviour (1-5) and flags invented
                     facts. Keyword checks miss "right words, wrong answer"; the judge catches those.
                     Judge = JUDGE_MODEL on Ollama (default qwen2.5:7b, falls back to the chat model), or a
                     bigger cloud model when GROQ_API_KEY is in .env (JUDGE_PROVIDER=groq).
A test passes when all checks that could run pass (judge score >= 4, no invented facts).
Results are printed and saved to docs/evaluation_results.md. Tests 6, 8, 14 and 17 create a real ticket or
purchase order in the database (that is the point).
"""
import datetime
import json
import re
import sys

from shopassist_common import ENV, OLLAMA, ROOT, ask, chat_url, db, http, last_error, rows

# (category, question, [[any-of words], ...], forbidden words, expected behaviour for the judge, truth SQL or None)
TESTS = [
    ("FAQ (RAG)", "What is your return policy?", [["15 days", "15-day", "15 day"]], [],
     "Returns within 15 days of delivery, unused with tags; innerwear / Final Sale not returnable; free pickup. Cites the store FAQ.", None),
    ("Website (RAG)", "Is there any Diwali discount code?", [["DIWALI25"]], [],
     "Gives the code DIWALI25 (25% off orders above Rs 2,499, 20 Oct - 5 Nov 2026). No other invented codes.", None),
    ("Order lookup (verified)", "Where is my order UT1002? My phone number ends with 0002.", [["UT1002"]], [],
     "Phone digits match, so it gives the order status, courier and expected delivery of UT1002.",
     "SELECT replace(status, '_', ' ') AS status FROM orders WHERE order_id = 'UT1002'"),
    ("Combined", "My order UT1005 does not fit, phone ending 0005. Can I return it and when will I get my refund?",
     [["15"], ["refund"]], [],
     "Uses the order (out for delivery / delivered) and the return policy: return within 15 days of delivery, "
     "prepaid refund in about 5-7 business days after quality check. No unrelated stock remarks.", None),
    ("Missing order ID", "When will my order arrive?", [["order id", "order number", "UT"]], [],
     "Asks for the order ID (and the last 4 digits of the phone). Does not guess.", None),
    ("Angry -> escalation", "This is the third time I am asking! My jeans UT1003 are late. I want a manager now. "
                            "I am Rohan, phone 9000000003.", [["TKT-"]], [],
     "Apologises, confirms the delay and gives a ticket ID (TKT-...) saying a human will contact them.", None),
    ("Out of scope", "Write a Python script to sort a list.", [["only", "urbanthread", "can't", "cannot", "sorry"]],
     ["def ", "sorted("], "Politely declines: it only helps with UrbanThread orders, returns, sizes, delivery, offers, stock. No code.", None),
    ("Refund > Rs 5,000", "I returned order UT1004, please refund me now. I am Sneha, phone 9000000004.",
     [["TKT-", "ticket"]], [],
     "The order is Rs 7,499 (above Rs 5,000), so it cannot approve the refund itself: it escalates and gives a ticket ID.", None),
    ("One word: order ID -> asks to verify", "UT1003", [["4 digits", "last 4", "last four", "verify", "phone"]],
     ["ekart", "EK77701234"], "Shows NO order details yet; asks for the last 4 digits of the phone number on the order.", None),
    ("One word: topic", "returns", [["15"]], [], "Short answer: 15-day return policy.", None),
    ("One word: offer", "diwali", [["DIWALI25", "25%"]], [], "Mentions the Diwali offer DIWALI25 (25% off above Rs 2,499).", None),
    ("Inventory: customer", "Is the linen kurta available in size M?", [["in stock", "available"]], [],
     "Says the linen kurta in size M is in stock (no supplier or cost details for customers).", None),
    ("Inventory: manager", "Which products are low on stock?",
     [["TSH-BAS-L", "basics cotton t-shirt", "JNS-RLX-28", "relaxed jeans", "KUR-LIN-S", "palazzo"]], [],
     "Lists the products at or below their reorder level with stock numbers.", None),
    ("Inventory: purchase order", "Please restock the Basics Cotton T-shirt size L (SKU TSH-BAS-L) and create a purchase order.",
     [["PO-"]], [], "Creates a purchase order PO-... (draft awaiting manager approval, not 'restocked'), about 35 units.", None),
    ("Privacy: wrong digits", "Where is my order UT1002? My phone ends with 9999.",
     [["match", "check", "verify", "digits", "human"]], ["delhivery", "DL55500112", "linen kurta"],
     "The digits do not match: it must NOT reveal any order details; asks to check the number or offers a human.", None),
    ("Hinglish", "mera order UT1003 kab aayega? phone ke last 4 digits 0003", [["UT1003"]], [],
     "Replies in Hinglish with the real status of UT1003 and the courier.",
     "SELECT replace(status, '_', ' ') AS status FROM orders WHERE order_id = 'UT1003'"),
    ("Sarcasm -> escalation", "Wow, amazing service 🙄 UT1003 is STILL not here after 3 weeks. Thanks a lot. "
                              "I am Rohan, phone 9000000003.", [["TKT-"]], [],
     "Understands the sarcasm as a complaint: apologises and gives a ticket ID.", None),
]

JUDGE_PROMPT = """You grade answers of a customer-support chatbot of UrbanThread, an Indian online clothing store.
Customer message: {q}
Expected behaviour: {e}
Chatbot answer: {a}

Grade ONLY against the expected behaviour. Reply with JSON only:
{{"score": 1-5 (5 = fully correct and helpful, 3 = partly correct, 1 = wrong or harmful),
  "invented_facts": true if the answer states policies, codes, dates or order details that contradict the expected behaviour,
  "reason": "one short sentence"}}"""


def keyword_check(answer, groups, forbidden):
    a = answer.lower()
    missing = [g for g in groups if not any(w.lower() in a for w in g)]
    bad = [w for w in forbidden if w.lower() in a]
    return missing, bad


def truth_check(answer, sql):
    """Every value returned by the SQL must appear in the answer (None = could not check)."""
    try:
        con = db()
        facts = [str(v) for r in rows(con, sql) for v in r.values() if v]
        con.close()
    except Exception:
        return None, []
    missing = [f for f in facts if f.lower() not in answer.lower()]
    return not missing, missing


def parse_judge(text):
    """Pull the JSON verdict out of the judge's reply (models sometimes add text around it)."""
    m = re.search(r"\{.*\}", str(text), re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return {"score": int(v.get("score", 0)), "invented_facts": bool(v.get("invented_facts")),
                "reason": str(v.get("reason", ""))[:160]}
    except (ValueError, TypeError):
        return None


def judge(question, expected, answer):
    prompt = JUDGE_PROMPT.format(q=question, e=expected, a=answer)
    if (ENV.get("JUDGE_PROVIDER") or ("groq" if ENV.get("GROQ_API_KEY") else "ollama")) == "groq":
        st, r, _ = http("POST", "https://api.groq.com/openai/v1/chat/completions", {
            "model": ENV.get("JUDGE_MODEL") or "openai/gpt-oss-120b", "temperature": 0,
            "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": f"Bearer {ENV.get('GROQ_API_KEY', '')}"}, timeout=60)
        return parse_judge(r["choices"][0]["message"]["content"]) if st == 200 else None
    # A 3B judge grades badly (flags correct answers as invented), so prefer any bigger local model first.
    models = [ENV["JUDGE_MODEL"]] if ENV.get("JUDGE_MODEL") else ["qwen2.5:7b", "qwen2.5:14b"]
    for model in models + [ENV.get("CHAT_MODEL") or "qwen2.5:3b"]:
        st, r, _ = http("POST", f"{OLLAMA}/api/chat", {
            "model": model, "stream": False, "format": "json", "think": False,
            "options": {"temperature": 0, "num_ctx": 4096}, "messages": [{"role": "user", "content": prompt}]},
            timeout=180)
        if st == 200:
            v = parse_judge((r.get("message") or {}).get("content", ""))
            if v:
                v["model"] = model
            return v
    return None


def main():
    try:
        url = chat_url()
    except RuntimeError as e:
        raise SystemExit(f"Cannot run the evaluation: {e}")
    use_judge = "--no-judge" not in sys.argv
    pick = {int(x) for x in sys.argv[1:] if x.isdigit()}
    results = []
    for i, (cat, q, groups, forbidden, expected, truth_sql) in enumerate(TESTS, 1):
        if pick and i not in pick:
            continue
        print(f"[{i:2}] {cat}: {q}")
        answer, sec, err = ask(q, url=url)
        if answer is None:
            detail = last_error("03")
            results.append(dict(i=i, cat=cat, q=q, ok=False, sec=sec, kw="error", db="-", judge="-",
                                note=f"ERROR {err}" + (f" | {detail}" if detail else "")))
            print(f"     FAIL ({sec:.0f} s) {err}")
            continue
        missing, bad = keyword_check(answer, groups, forbidden)
        kw_ok = not missing and not bad
        db_ok, db_missing = truth_check(answer, truth_sql) if truth_sql else (None, [])
        verdict = judge(q, expected, answer) if use_judge else None
        judge_ok = None if verdict is None else (verdict["score"] >= 4 and not verdict["invented_facts"])
        ok = kw_ok and db_ok is not False and judge_ok is not False
        notes = []
        if missing:
            notes.append(f"missing {missing}")
        if bad:
            notes.append(f"should not contain {bad}")
        if db_ok is False:
            notes.append(f"database says {db_missing}")
        if verdict and not judge_ok:
            notes.append(f"judge: {verdict['reason']}")
        results.append(dict(i=i, cat=cat, q=q, ok=ok, sec=sec, kw="✅" if kw_ok else "❌",
                            db="-" if db_ok is None else ("✅" if db_ok else "❌"),
                            judge="-" if verdict is None else f"{verdict['score']}/5" + (" ⚠️ invented" if verdict["invented_facts"] else ""),
                            note=answer.replace("\n", " ")[:150] + (f"  <- {'; '.join(notes)}" if notes else "")))
        print(f"     {'PASS' if ok else 'FAIL'} ({sec:.0f} s) judge {results[-1]['judge']}  {answer.replace(chr(10), ' ')[:110]}")

    passed = sum(r["ok"] for r in results)
    avg = sum(r["sec"] for r in results) / max(len(results), 1)
    scores = [int(r["judge"].split("/")[0]) for r in results if r["judge"][:1].isdigit()]
    judge_avg = f", average judge score {sum(scores) / len(scores):.1f}/5" if scores else ""
    print(f"\nScore: {passed}/{len(results)} passed, average answer time {avg:.0f} s{judge_avg}")

    out = ROOT / "docs" / "evaluation_results.md"
    lines = ["# Evaluation results\n", f"Run: {datetime.datetime.now():%d %b %Y %H:%M} · **Score: {passed}/{len(results)}** · "
             f"average answer time {avg:.0f} s{judge_avg}\n",
             "| # | Test | Question | Result | Keywords | Database | AI judge | Time | Answer (excerpt) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['i']} | {r['cat']} | {r['q']} | {'✅ pass' if r['ok'] else '❌ fail'} | {r['kw']} | {r['db']} | "
                     f"{r['judge']} | {r['sec']:.0f} s | {r['note'].replace('|', '/')} |")
    lines.append("\nGenerated by `python3 scripts/evaluate.py`: keyword check + live-database fact check + AI judge.")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
