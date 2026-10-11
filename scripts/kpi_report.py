"""Business KPIs from the live database (orders, tickets, chats, stock, purchase orders).

    pip3 install pg8000
    python3 scripts/kpi_report.py

Prints the KPIs and saves docs/kpi_report.md (for the report). The same numbers are shown live in the
web app dashboard (python3 app/server.py).
"""
import datetime

from shopassist_common import ROOT, kpis


def table(rows):
    if isinstance(rows, dict):
        return [f"_not available: {rows.get('error')}_"]
    if not rows:
        return ["_no rows yet_"]
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r[c])[:19] for c in cols) + " |")
    return out


try:
    k = kpis()
except Exception as e:
    raise SystemExit(f"Cannot read the database: {e}")

t = (k.get("ticket_totals") or [{}])
t = t[0] if isinstance(t, list) and t else {}
c = (k.get("chat_totals") or [{}])
c = c[0] if isinstance(c, list) and c else {}
conv, tickets = int(c.get("conversations") or 0), int(t.get("tickets") or 0)
rate = f"{(1 - tickets / conv) * 100:.0f}%" if conv else "n/a"

md = [f"# ShopAssist KPI report\n", f"Generated {datetime.datetime.now():%d %b %Y %H:%M} from the live database.\n",
      "## Headline numbers\n",
      f"- Conversations handled by the AI: **{conv}** ({c.get('customer_messages') or 0} customer messages)",
      f"- Escalated to a human (tickets): **{tickets}** ({t.get('high_priority') or 0} high priority, "
      f"{t.get('angry') or 0} angry customers, {t.get('open') or 0} still open)",
      f"- Conversations resolved without a human (approx.): **{rate}**",
      f"- Products at or below reorder level: **{len(k['low_stock']) if isinstance(k.get('low_stock'), list) else 'n/a'}**",
      f"- Purchase orders drafted by the Inventory Agent: **{len(k['purchase_orders']) if isinstance(k.get('purchase_orders'), list) else 'n/a'}**\n"]
for title, key in [("Orders by status", "orders_by_status"), ("Tickets by type and priority", "tickets_by_type"),
                   ("Low stock", "low_stock"), ("Latest purchase orders", "purchase_orders"),
                   ("Latest tickets", "recent_tickets")]:
    md += [f"## {title}\n"] + table(k.get(key)) + [""]
text = "\n".join(md)
print(text)
(ROOT / "docs" / "kpi_report.md").write_text(text + "\n", encoding="utf-8")
print("Saved docs/kpi_report.md")
