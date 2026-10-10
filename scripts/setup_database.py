"""Create / update the ShopAssist tables in Supabase and load the fake data (safe to run again).

    pip3 install pg8000
    python3 scripts/setup_database.py

Runs database/schema.sql (CREATE TABLE IF NOT EXISTS ...) and database/seed.sql (INSERT ... ON CONFLICT DO
NOTHING), so existing rows are never duplicated or overwritten. Reads POSTGRES_* from .env.
"""
import re
import sys

from shopassist_common import ROOT, db


def statements(path):
    sql = "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", sql) if s.strip()]


try:
    con = db()
except Exception as e:
    sys.exit(f"Cannot connect to the database: {e}\n"
             "Check POSTGRES_HOST / POSTGRES_USER / POSTGRES_PASSWORD in .env (Supabase -> Connect -> Session pooler).")
for f in ("schema.sql", "seed.sql"):
    for stmt in statements(ROOT / "database" / f):
        con.run(stmt)
    print(f"ran database/{f}")
for t in ("orders", "tickets", "products", "purchase_orders", "n8n_chat_histories"):
    print(f"   {t:20} {con.run(f'SELECT count(*) FROM {t}')[0][0]} rows")
con.close()
print("Database ready.")
