"""Shared helpers for the ShopAssist test suite.

    pip install pytest pg8000
    pytest                                   # workflow + guardrail tests always run
    PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres PGPASSWORD=postgres pytest   # + SQL tests on a real Postgres

The SQL tests create (and drop) their own database `shopassist_test`; they never touch Supabase.
In GitHub Actions a Postgres 16 service container provides the database (see .github/workflows/ci.yml).
"""
import csv
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = ROOT / "workflows"
TEST_DB = "shopassist_test"


def load_workflows():
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(WF_DIR.glob("*.json"))}


def node(wf, name):
    return next(n for n in wf["nodes"] if n["name"] == name)


@pytest.fixture(scope="session")
def workflows():
    return load_workflows()


# ------------------------------------------------------------------ JavaScript (Code nodes) via Node.js
def run_js(code, json_input, other_nodes=None):
    """Run an n8n Code-node body with Node.js. `$json` is json_input; `$('Name').first().json` / `.item.json`
    return other_nodes[Name]. Returns the json of the first output item."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = (
        "const input = JSON.parse(process.argv[1]); const others = JSON.parse(process.argv[2]);\n"
        "const $ = (n) => ({ first: () => ({ json: others[n] }), item: { json: others[n] } });\n"
        "const fn = new Function('$json', '$', process.argv[3]);\n"
        "process.stdout.write(JSON.stringify(fn(input, $)[0].json));\n"
    )
    out = subprocess.run(["node", "-e", harness, json.dumps(json_input), json.dumps(other_nodes or {}), code],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ------------------------------------------------------------------ Postgres via psql
def _psql_base(db):
    return ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db]


@pytest.fixture(scope="session")
def pg():
    """A fresh `shopassist_test` database with schema.sql + seed.sql applied TWICE (proves both are re-runnable).
    Returns a function run(sql, *more_sql) -> list of dict rows of the last statement (CSV output of psql)."""
    if not shutil.which("psql"):
        pytest.skip("psql is not installed")
    admin = _psql_base(os.environ.get("PGDATABASE", "postgres"))
    probe = subprocess.run(admin + ["-c", "SELECT 1"], capture_output=True, text=True, timeout=15)
    if probe.returncode != 0:
        pytest.skip(f"no Postgres reachable (set PGHOST/PGPORT/PGUSER/PGPASSWORD): {probe.stderr.strip()[:120]}")
    subprocess.run(admin + ["-c", f"DROP DATABASE IF EXISTS {TEST_DB}", "-c", f"CREATE DATABASE {TEST_DB}"],
                   check=True, capture_output=True, timeout=30)
    for _ in range(2):
        for f in ("schema.sql", "seed.sql"):
            r = subprocess.run(_psql_base(TEST_DB) + ["-f", str(ROOT / "database" / f)], capture_output=True, text=True)
            assert r.returncode == 0, f"{f}: {r.stderr}"

    def run(*sql):
        args = _psql_base(TEST_DB) + ["--csv"]
        for s in sql:
            args += ["-c", s]
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        blocks = [b for b in r.stdout.strip().split("\n\n") if b.strip()]
        return list(csv.DictReader(io.StringIO(blocks[-1]))) if blocks else []

    yield run
    subprocess.run(admin + ["-c", f"DROP DATABASE IF EXISTS {TEST_DB}"], capture_output=True, timeout=30)


def prepared(name, sql, types):
    """PREPARE statement for a workflow query that uses $1..$n (like n8n's 'Query Parameters')."""
    return f"PREPARE {name} ({', '.join(types)}) AS {sql.rstrip().rstrip(';')}"


def lit(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"
