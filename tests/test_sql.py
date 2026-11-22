"""Every SQL query of the workflows, run against a real Postgres with schema.sql + seed.sql.

Queries are read from the generated workflow JSON, so the tests check exactly what n8n runs.
Skipped automatically when no Postgres is reachable (see conftest.py).
"""
import pytest

from conftest import lit, node, prepared


@pytest.fixture(scope="module")
def q(workflows):
    def get(wf, name):
        return node(workflows[wf], name)["parameters"]["query"]
    return get


@pytest.fixture(scope="module")
def lookup(pg, q):
    sql = prepared("lookup", q("03_support_agent_chat.json", "order_lookup"), ["text", "text"])
    return lambda oid, digits: pg(sql, f"EXECUTE lookup({lit(oid)}, {lit(digits)})")[0]


def test_schema_and_seed_are_rerunnable(pg):
    counts = pg("SELECT (SELECT count(*) FROM orders) o, (SELECT count(*) FROM products) p, (SELECT count(*) FROM order_events) e")[0]
    assert counts == {"o": "10", "p": "12", "e": "20"}  # applied twice, no duplicates


def test_order_lookup_with_right_digits(lookup):
    r = lookup("ut1002", "0002")
    assert r["verification"] == "verified" and r["order_id"] == "UT1002" and r["courier"] == "Delhivery"
    assert r["history"].startswith("placed")


@pytest.mark.parametrize("digits,expected", [("", "need_phone"), ("12", "need_phone"), ("9999", "wrong_phone"),
                                             ("+91 90000 00002", "verified")])
def test_order_lookup_identity_check(lookup, digits, expected):
    r = lookup("UT1002", digits)
    assert r["verification"] == expected
    if expected != "verified":
        assert r["order_id"] == "" and r["items"] == "" and "Do NOT share" in r["instruction"]


def test_unknown_order(lookup):
    assert lookup("UT9999", "1234")["verification"] == "not_found"


def test_five_wrong_tries_lock_the_order(pg, lookup):
    for _ in range(5):
        assert lookup("UT1006", "1111")["verification"] == "wrong_phone"
    r = lookup("UT1006", "0006")  # even the right digits are refused now
    assert r["verification"] == "locked" and r["order_id"] == ""
    assert pg("SELECT count(*) AS n FROM verification_attempts WHERE order_id = 'UT1006' AND NOT success")[0]["n"] == "5"
    assert lookup("UT1007", "0007")["verification"] == "verified"  # other orders are not affected


def test_escalation_check_query_reports_verification(pg, q):
    sql = prepared("details", q("03_support_agent_chat.json", "Order Details (for escalation check)"), ["text", "text"])
    assert pg(sql, "EXECUTE details('UT1004', '0004')")[0]["verified"] == "t"
    assert pg(sql, "EXECUTE details('UT1004', '')")[0]["verified"] == "f"


def test_ticket_insert_returns_ticket_id(pg, q):
    sql = prepared("ticket", q("04_escalation_subworkflow.json", "Save Ticket in Postgres"), ["text"] * 9)
    r = pg(sql, "EXECUTE ticket('Rohan', '+919000000003', 'UT1003', 'delivery', 'angry', 'high', 's', 'a', 'hinglish')")[0]
    assert r["ticket_id"].startswith("TKT-") and r["priority"] == "high"


def test_order_update_webhook_writes_history(pg, q):
    sql = prepared("upd", q("05_order_update_webhook.json", "Update Order Status"), ["text"] * 4)
    r = pg(sql, "EXECUTE upd('ut1010', 'DELAYED', '2026-10-20', 'Ekart: hub backlog')")[0]
    assert r["status"] == "delayed" and r["expected_delivery"] == "2026-10-20"
    ev = pg("SELECT status, note FROM order_events WHERE order_id = 'UT1010' ORDER BY id DESC LIMIT 1")[0]
    assert ev == {"status": "delayed", "note": "Ekart: hub backlog"}
    assert pg(sql, "EXECUTE upd('UT9999', 'shipped', '', '')") == []  # unknown order -> nothing


def test_stock_lookup(pg, q):
    sql = prepared("stock", q("06_inventory_agent.json", "stock_lookup"), ["text"])
    low = {r["sku"] for r in pg(sql, "EXECUTE stock('low')")}
    assert low == {"TSH-BAS-L", "JNS-RLX-28", "KUR-LIN-S", "PLZ-COT-S", "HOD-OVR-XL"}
    assert [r["sku"] for r in pg(sql, "EXECUTE stock('linen kurta size M')")] == ["KUR-LIN-M"]


def test_purchase_order_quantity_rule_and_approval(pg, q):
    create = prepared("po", q("06_inventory_agent.json", "create_purchase_order"), ["text", "int", "text"])
    po = pg(create, "EXECUTE po('tsh-bas-l', 10, 'low stock')")[0]
    assert po["quantity"] == "35" and po["status"] == "pending_approval"  # never below 2 x 20 - 6 -> 35
    token = pg(f"SELECT approval_token FROM purchase_orders WHERE po_id = '{po['po_id']}'")[0]["approval_token"]
    assert len(token) == 32

    decide = prepared("dec", q("07_po_approval.json", "Apply Decision (token check)"), ["text"] * 4)
    assert pg(decide, f"EXECUTE dec('{po['po_id']}', 'approve', 'wrong-token', 'x')") == []
    assert pg(decide, f"EXECUTE dec('{po['po_id']}', 'delete', {lit(token)}, 'x')") == []
    r = pg(decide, f"EXECUTE dec('{po['po_id']}', 'approve', {lit(token)}, 'Asha')")[0]
    assert r["status"] == "approved" and r["decided_by"] == "Asha" and r["supplier_phone"].startswith("+91")
    assert pg(decide, f"EXECUTE dec('{po['po_id']}', 'reject', {lit(token)}, 'x')") == []  # decided only once

    review = prepared("rev", q("07_po_approval.json", "Find Purchase Order"), ["text", "text"])
    assert pg(review, f"EXECUTE rev('{po['po_id']}', {lit(token)})")[0]["status"] == "approved"
    assert pg(review, f"EXECUTE rev('{po['po_id']}', 'nope')") == []


def test_dashboard_kpi_queries_run(pg):
    import sys
    from conftest import ROOT
    sys.path.insert(0, str(ROOT / "scripts"))
    from shopassist_common import KPI_QUERIES
    for name, sql in KPI_QUERIES.items():
        pg(sql)  # raises on SQL errors
