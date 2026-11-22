"""Structure checks for the generated n8n workflows (no n8n or AI needed)."""
import json
import re
import subprocess
import sys

from conftest import ROOT, WF_DIR, load_workflows

EXPECTED = ["01_ingest_faq_pdf.json", "02_scrape_and_summarize.json", "03_support_agent_chat.json",
            "04_escalation_subworkflow.json", "05_order_update_webhook.json", "06_inventory_agent.json",
            "07_po_approval.json"]


def test_all_seven_workflows_exist(workflows):
    assert sorted(workflows) == EXPECTED


def test_generated_files_are_up_to_date(tmp_path):
    """workflows/*.json must be exactly what scripts/build_workflows.py produces (never hand-edited)."""
    code = (f"import sys; sys.argv=['x']; sys.path.insert(0, {str(ROOT / 'scripts')!r}); import build_workflows as b; "
            f"from pathlib import Path; b.OUT_DIR = Path({str(tmp_path)!r}); "
            "[f() for f in (b.wf01, b.wf02, b.wf03, b.wf04, b.wf05, b.wf06, b.wf07)]")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
    for name in EXPECTED:
        assert (tmp_path / name).read_text(encoding="utf-8") == (WF_DIR / name).read_text(encoding="utf-8"), \
            f"{name} is out of date: run python3 scripts/build_workflows.py"


def test_connections_point_to_existing_nodes(workflows):
    for fname, wf in workflows.items():
        names = {n["name"] for n in wf["nodes"]}
        assert len(names) == len(wf["nodes"]), f"{fname}: duplicate node names"
        assert len({n["id"] for n in wf["nodes"]}) == len(wf["nodes"]), f"{fname}: duplicate node ids"
        for src, kinds in wf["connections"].items():
            assert src in names, f"{fname}: connection from unknown node {src}"
            for outs in kinds.values():
                for out in outs:
                    for c in out:
                        assert c["node"] in names, f"{fname}: {src} -> unknown node {c['node']}"


def test_every_workflow_has_a_time_limit(workflows):
    for fname, wf in workflows.items():
        if fname.startswith("0") and wf["nodes"]:
            assert wf["settings"].get("executionTimeout", 0) > 0, f"{fname}: no executionTimeout"


def test_sql_is_parameterised(workflows):
    """No {{ expressions }} inside SQL text: values must go through $1..$n query parameters (no SQL injection)."""
    for fname, wf in workflows.items():
        for n in wf["nodes"]:
            q = n["parameters"].get("query")
            if q:
                assert "{{" not in q, f"{fname} / {n['name']}: expression inside SQL"
                if re.search(r"\$\d", q):
                    assert n["parameters"]["options"].get("queryReplacement"), f"{fname} / {n['name']}: $n without parameters"


def test_ai_tool_inputs_have_defaults(workflows):
    """A small model that forgets a tool field must not break the tool ('did not match expected schema')."""
    wf = workflows["03_support_agent_chat.json"]
    for n in wf["nodes"]:
        if n["type"].endswith("toolWorkflow"):
            for k, v in n["parameters"]["workflowInputs"]["value"].items():
                assert v.count(",") >= 3, f"{n['name']}.{k} has no default: {v}"
    lookup = next(n for n in wf["nodes"] if n["name"] == "order_lookup")
    assert lookup["parameters"]["options"]["queryReplacement"].count("''") == 2  # both inputs default to ''


def test_order_lookup_requires_phone_digits(workflows):
    q = next(n for n in workflows["03_support_agent_chat.json"]["nodes"] if n["name"] == "order_lookup")["parameters"]["query"]
    assert "RIGHT(phone, 4)" in q and "verification_attempts" in q and "locked" in q
    assert "OR RIGHT(phone, 10)" not in q  # the old phone-only lookup is gone


def test_knowledge_bases_use_separate_namespaces(workflows):
    inserts = {f: n for f, wf in workflows.items() for n in wf["nodes"]
               if n["type"].endswith("vectorStorePinecone") and n["parameters"]["mode"] == "insert"}
    assert {n["parameters"]["options"]["pineconeNamespace"] for n in inserts.values()} == {"faq", "website"}
    assert all(n["parameters"]["options"]["clearNamespace"] for n in inserts.values())
    assert all(n["parameters"]["embeddingBatchSize"] >= 1000 for n in inserts.values())
    tools = [n for n in workflows["03_support_agent_chat.json"]["nodes"] if n["type"].endswith("vectorStorePinecone")]
    assert {n["parameters"]["options"]["pineconeNamespace"] for n in tools} == {"faq", "website"}


def test_webhooks_have_unique_paths(workflows):
    paths = [n["parameters"]["path"] for wf in workflows.values() for n in wf["nodes"] if n["type"].endswith(".webhook")]
    assert len(paths) == len(set(paths)) and {"order-update", "po-review", "po-decision"} <= set(paths)


def test_po_links_use_public_url_placeholder(workflows):
    text = json.dumps(workflows["06_inventory_agent.json"])
    assert "__N8N_PUBLIC_URL__/webhook/po-review" in text and "approval_token" in text


def test_no_real_secrets_in_repository():
    patterns = [r"xox[bp]-\d{6,}", r"\bAC[0-9a-f]{32}\b", r"\bsk-[A-Za-z0-9]{20,}", r"pcsk_[A-Za-z0-9_]{20,}",
                r"gsk_[A-Za-z0-9]{20,}", r"eyJhbGciOi[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}"]
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    for f in files:
        p = ROOT / f
        if p.suffix in (".png", ".pdf", ".docx", ".jpg") or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat in patterns:
            assert not re.search(pat, text), f"possible secret in {f} ({pat})"


def test_loader_does_not_need_n8n():
    assert len(load_workflows()) == 7
