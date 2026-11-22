"""Unit tests for the evaluation helpers (no model needed)."""
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import evaluate  # noqa: E402


def test_judge_reply_is_parsed_even_with_extra_text():
    v = evaluate.parse_judge('Here you go: {"score": "4", "invented_facts": false, "reason": "fine"} thanks')
    assert v == {"score": 4, "invented_facts": False, "reason": "fine"}
    assert evaluate.parse_judge("no json here") is None
    assert evaluate.parse_judge('{"score": "high"}') is None


def test_keyword_check():
    missing, bad = evaluate.keyword_check("Your order UT1002 is with Delhivery", [["UT1002"], ["shipped", "delayed"]], ["DL555"])
    assert missing == [["shipped", "delayed"]] and bad == []
    assert evaluate.keyword_check("tracking DL55500112", [], ["dl555"])[1] == ["dl555"]


def test_every_test_has_an_expected_behaviour():
    assert len(evaluate.TESTS) == 17
    for t in evaluate.TESTS:
        assert len(t) == 6 and len(t[4]) > 20
