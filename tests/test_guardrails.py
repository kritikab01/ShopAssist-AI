"""The deterministic guardrails around the AI agent, run with Node.js exactly as n8n runs them."""
import pytest

from conftest import node, run_js


@pytest.fixture(scope="module")
def detect(workflows):
    code = node(workflows["03_support_agent_chat.json"], "Detect Intent (rules)")["parameters"]["jsCode"]
    return lambda msg: run_js(code, {"chatInput": msg, "sessionId": "t"})


@pytest.mark.parametrize("msg", [
    "This is the THIRD time I'm asking, I want a manager",
    "Worst service ever",
    "Wow, amazing service 🙄 UT1003 is STILL not here after 3 weeks. Thanks a lot.",
    "Great job guys, still waiting for my order since 2 weeks",
    "WHERE IS MY ORDER I PAID ALREADY",
    "bhai paise wapas karo, bakwas service",
    "मुझे मैनेजर से बात करनी है",
])
def test_upset_customers_are_flagged(detect, msg):
    out = detect(msg)
    assert out["intent"]["escalate"] is True
    assert "escalate_to_human" in out["chatInput"]


@pytest.mark.parametrize("msg", ["Great, thanks for the help!", "what is the return policy", "UT1002", "diwali",
                                 "Is the linen kurta available in size M?", "Amazing kurta, love it"])
def test_calm_messages_are_not_escalated(detect, msg):
    assert detect(msg)["intent"]["escalate"] is False


@pytest.mark.parametrize("msg,lang", [
    ("mera order UT1003 kab aayega?", "hinglish"),
    ("bhai refund kab milega yaar", "hinglish"),
    ("मेरा ऑर्डर कहाँ है?", "hi"),
    ("Where is my order?", "en"),
    ("Do you have a kurta in size M?", "en"),
])
def test_language_detection(detect, msg, lang):
    out = detect(msg)
    assert out["intent"]["language"] == lang
    if lang != "en":
        assert "reply in" in out["chatInput"].lower()


@pytest.mark.parametrize("msg,oid,last4", [
    ("Where is UT1002? My phone ends with 0002", "UT1002", "0002"),
    ("ut1003 +91 90000 00003", "UT1003", "0003"),
    ("I am Rohan, phone 9000000003, UT1003", "UT1003", "0003"),
    ("UT1003", "UT1003", ""),
    ("0003", "", "0003"),
])
def test_identity_check_inputs(detect, msg, oid, last4):
    out = detect(msg)
    assert out["intent"]["order_id"] == oid and out["intent"]["last4"] == last4
    if oid and not last4:
        assert "Never share order details before they are verified" in out["chatInput"]


def test_order_id_digits_are_not_taken_as_phone_digits(detect):
    assert detect("UT1004 please")["intent"]["last4"] == ""


def test_out_of_scope_and_refund_notes(detect):
    assert "NOT about UrbanThread" in detect("Write me a Python script")["chatInput"]
    assert "Rs 5000" in detect("refund my order UT1004")["chatInput"]
    assert "Never invent a code" in detect("any coupon code?")["chatInput"]


def test_guaranteed_escalation_never_leaks_unverified_order(workflows):
    code = node(workflows["03_support_agent_chat.json"], "Needs a Ticket? (rules)")["parameters"]["jsCode"]
    order = {"order_id": "UT1002", "customer_name": "Priya", "phone": "+919000000002", "amount_inr": 2499,
             "items": "Linen Kurta", "status": "shipped", "expected_delivery": "2026-10-11", "courier": "Delhivery",
             "tracking_no": "DL1", "verified": False}
    intent = {"escalate": False, "refund": False, "order_id": "UT1002", "language": "en", "original": "UT1002"}
    others = {"Detect Intent (rules)": {"intent": intent}, "ShopAssist AI Agent": {"output": ""},
              "Order Details (for escalation check)": order}
    reply = run_js(code, order, others)["reply"]
    assert "Delhivery" not in reply and "Linen" not in reply
    order["verified"] = True
    assert "Delhivery" in run_js(code, order, others)["reply"]


def test_big_refund_creates_ticket_even_if_model_forgets(workflows):
    code = node(workflows["03_support_agent_chat.json"], "Needs a Ticket? (rules)")["parameters"]["jsCode"]
    order = {"order_id": "UT1004", "customer_name": "Sneha", "phone": "+919000000004", "amount_inr": 7499, "verified": False}
    intent = {"escalate": False, "refund": True, "order_id": "UT1004", "language": "hinglish", "original": "refund UT1004"}
    out = run_js(code, order, {"Detect Intent (rules)": {"intent": intent},
                               "ShopAssist AI Agent": {"output": "I have escalated it."},
                               "Order Details (for escalation check)": order})
    assert out["needs_ticket"] is True and out["language"] == "hinglish"
    assert out["customer_name"] == "Sneha" and out["order_id"] == "UT1004"


def test_ticket_is_normalised_when_model_returns_garbage(workflows):
    code = node(workflows["04_escalation_subworkflow.json"], "Normalize Ticket (fallback)")["parameters"]["jsCode"]
    inp = {"customer_name": "Rohan", "phone": "9000000003", "order_id": "", "reason": "angry customer",
           "conversation_summary": "bhai mera order UT1003 kab aayega, bakwas"}
    t = run_js(code, {"output": {"priority": "URGENT!!", "sentiment": "very angry"}},
               {"When Called by Agent": inp})["output"]
    assert t["phone"] == "+919000000003" and t["order_id"] == "UT1003"
    assert t["priority"] == "high" and t["sentiment"] == "angry" and t["language"] == "hinglish"
    assert t["issue_type"] in ("refund", "return", "delivery", "damaged_item", "payment", "size", "other")
